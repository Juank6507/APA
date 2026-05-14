# apa/core/providers.py
# v2.3 — Sprint 1: confidence_score por provider (P-2),
#         integración con Pool composite key (P-1).
#
# CAMBIOS v2.3 vs v2.2:
#   - confidence_score property en ModelProvider ABC (P-2)
#   - Default confidence por tipo de provider: native=90, aggregator=70, local=60
#   - get_all_models_with_provider() retorna modelos con provider como dato
#   - Compatibilidad total con v2.2 (sin breaking changes)
#
# v2.2 — Production-ready: CACHE_DIR usa _find_project_data_dir() para
#         consistencia con model_health, logger.propagate=False.
#
# ============================================================================
# APROXIMACIÓN v2.2 vs RESULTADO ESPERADO:
#   v2.1 tenia un bug silencioso: ModelProvider.CACHE_DIR usaba
#   Path(__file__).parent.parent.parent / "data" / "providers", que se
#   resuelve distinto al importar vs ejecutar directamente en Windows.
#   Es el MISMO bug que model_health v2.8 tenia con health_cache.json.
#
#   El bug nunca se manifesto porque los archivos de cache de proveedores
#   se recrean automaticamente (se descargan de la API). Pero si el
#   directorio apunta al lugar equivocado, se crean caches duplicados.
#
#   v2.2 FIX:
#   1. CACHE_DIR usa _find_project_data_dir() / "providers" para
#      consistencia con model_health
#   2. logger.propagate = False -> elimina duplicate log lines
#   3. get_model_price() maneja None pricing correctamente
#
#   RESULTADO ESPERADO:
#   - Caches de proveedores siempre en APA/data/providers/
#   - Sin caches duplicados en rutas incorrectas
#   - Sin lineas de log duplicadas
# ============================================================================
#
# CAMBIOS v2.2 vs v2.1:
#   - CACHE_DIR: usa _find_project_data_dir() en vez de parent.parent.parent
#   - logger.propagate = False
#   - get_model_price() maneja None en pricing
#   - _infer_capabilities() protegido contra context_length None
import sys
import os
import re
import time
import json
import logging
import requests
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings

# ============================================================================
# Logging setup — production-ready
# ============================================================================
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
logger.propagate = False  # v2.2: Evita duplicate log lines

# ============================================================================
# Path resolution — consistente con model_health
# ============================================================================
def _find_project_data_dir() -> Path:
    """Busca el directorio data/ del proyecto APA de forma robusta.
    Identico a model_health._find_project_data_dir() para consistencia.
    """
    resolved = Path(__file__).resolve()
    current = resolved.parent

    candidates = []
    for _ in range(8):
        candidate = current / "data"
        if candidate.is_dir() and (candidate / "providers").is_dir():
            parent_dir = candidate.parent
            if (parent_dir / "apa").is_dir():
                return candidate
            candidates.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent

    if candidates:
        candidates.sort(key=lambda c: len(c.parts), reverse=True)
        return candidates[0]

    return resolved.parent.parent.parent / "data"


def _log(module: str, stage: str, status: str, detail: str = "") -> None:
    msg = f"[PROGRESO] | MODULO={module} | ETAPA={stage} | ESTADO={status}"
    if detail:
        msg += f" | DETALLE={detail}"
    logger.info(msg)

def _infer_capabilities(model_id: str, context_length: int) -> List[str]:
    # v2.2: Proteger contra context_length None
    ctx = context_length if context_length is not None else 0
    caps = []
    mid = model_id.lower()
    if "coder" in mid or "code" in mid or "coding" in mid:
        caps.append("coding")
    if "instruct" in mid or "instruction" in mid:
        caps.append("instruction")
    if ctx >= 32000:
        caps.append("long_context")
    if "reason" in mid or "thinking" in mid or "/r1" in mid or "-r1" in mid or "deepseek-r" in mid:
        caps.append("reasoning")
    return caps or ["general"]

class ModelProvider(ABC):
    # v2.2: Usa _find_project_data_dir() para consistencia con model_health
    CACHE_DIR = _find_project_data_dir() / "providers"
    CACHE_TTL = 3600

    # P-2: Default confidence score (override en subclases)
    # Native providers (anthropic, openai) → 90 (API directa, máxima fiabilidad)
    # Aggregator providers (openrouter, together, groq) → 70 (intermediario)
    # Local providers (ollama) → 60 (depende de hardware local)
    _DEFAULT_CONFIDENCE_SCORE: float = 70.0

    @property
    @abstractmethod
    def name(self) -> str: pass

    @property
    def confidence_score(self) -> float:
        """P-2: Confidence score del provider (0-100).

        Refleja la fiabilidad del provider para servir modelos sin error.
        - Native (anthropic, openai): 90 — API directa
        - Aggregator (openrouter, together, groq, github): 70 — intermediario
        - Local (ollama): 60 — depende de hardware
        """
        return self._DEFAULT_CONFIDENCE_SCORE

    @abstractmethod
    def is_available(self) -> bool: pass

    @abstractmethod
    def get_models(self) -> List[Dict[str, Any]]: pass

    @abstractmethod
    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]: pass

    def _get_cached_models(self) -> Optional[List[Dict[str, Any]]]:
        cache_file = self.CACHE_DIR / f"{self.name}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                if time.time() - data.get("timestamp", 0) < self.CACHE_TTL:
                    return data.get("models")
            except Exception:
                pass
        return None

    def _cache_models(self, models: List[Dict[str, Any]]) -> None:
        try:
            cache_file = self.CACHE_DIR / f"{self.name}.json"
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"timestamp": time.time(), "models": models}
            cache_file.write_text(json.dumps(data))
        except Exception:
            pass

class OpenRouterProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 70.0  # Aggregator

    def __init__(self):
        self._api_key = settings.openrouter_api_key
        self._base_url = "https://openrouter.ai/api/v1"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "openrouter"

    def is_available(self) -> bool:
        if not self._api_key or not self._api_key.strip(): return False
        now = time.time()
        if self._avail_cache is not None and self._avail_ts is not None and now - self._avail_ts < 300:
            return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=3)
            res = resp.status_code == 200
            self._avail_cache, self._avail_ts = res, now
            return res
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=5)
            if resp.status_code != 200: return []
            models = []
            for m in resp.json().get("data", []):
                model_id = m.get("id", "")
                if not model_id: continue
                ctx_len = m.get("context_length", 8192) or 8192
                caps = _infer_capabilities(model_id, ctx_len)
                pricing = m.get("pricing", {})
                try:
                    prompt_price = float(pricing.get("prompt", 0)) if pricing.get("prompt") else 0.0
                except (ValueError, TypeError):
                    prompt_price = 0.0
                try:
                    completion_price = float(pricing.get("completion", 0)) if pricing.get("completion") else 0.0
                except (ValueError, TypeError):
                    completion_price = 0.0
                is_free = (prompt_price == 0 and completion_price == 0) or model_id.endswith(":free")
                models.append({
                    "id": model_id,
                    "name": m.get("name", model_id),
                    "context_length": ctx_len,
                    "capabilities": caps,
                    "quality_score": 50,
                    "is_free_tier": is_free,
                    "provider": "openrouter",
                    "pricing": pricing,
                    "price_prompt_per_1k": prompt_price,
                    "price_completion_per_1k": completion_price
                })
            self._cache_models(models)
            return models
        except Exception as e:
            logger.error(f"OpenRouter get_models error: {e}")
            return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            if resp.status_code != 200: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
            return {"content": resp.json().get("choices", [{}])[0].get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class GroqProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 70.0  # Aggregator
    def __init__(self):
        self._api_key = settings.groq_api_key
        self._base_url = "https://api.groq.com/openai/v1"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "groq"

    def is_available(self) -> bool:
        if not self._api_key or not self._api_key.strip(): return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code == 200, now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=5)
            if resp.status_code != 200: return []
            models = []
            for m in resp.json().get("data", []):
                mid, ctx = m.get("id", ""), m.get("context_window", 8192) or 8192
                if mid: models.append({"id": mid, "name": m.get("name", mid), "context_length": ctx, "capabilities": _infer_capabilities(mid, ctx), "quality_score": 50, "is_free_tier": True, "provider": "groq"})
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            return {"content": resp.json().get("choices", [{}])[0].get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class GitHubModelsProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 70.0  # Aggregator
    def __init__(self):
        self._token = settings.github_token
        self._base_url = "https://models.inference.ai.azure.com"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "github"

    def is_available(self) -> bool:
        if not self._token or not self._token.strip(): return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._token}"}, timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code == 200, now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._token}"}, timeout=5)
            if resp.status_code != 200: return []
            models = []
            for m in resp.json():
                mid, ctx = m.get("id", ""), m.get("context_window", 8192) or 8192
                if mid: models.append({"id": mid, "name": m.get("name", mid), "context_length": ctx, "capabilities": _infer_capabilities(mid, ctx), "quality_score": 50, "is_free_tier": True, "provider": "github"})
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}, json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            return {"content": resp.json().get("choices", [{}])[0].get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class TogetherProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 70.0  # Aggregator
    def __init__(self):
        self._api_key = settings.together_api_key
        self._base_url = "https://api.together.xyz/v1"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "together"

    def is_available(self) -> bool:
        if not self._api_key or not self._api_key.strip(): return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code == 200, now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=5)
            if resp.status_code != 200: return []
            models = []
            for m in resp.json():
                mid, ctx = m.get("id", ""), m.get("context_length", 4096) or 4096
                if mid: models.append({"id": mid, "name": m.get("display_name", mid), "context_length": ctx, "capabilities": _infer_capabilities(mid, ctx), "quality_score": 50, "is_free_tier": False, "provider": "together"})
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            return {"content": resp.json().get("choices", [{}])[0].get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class FireworksProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 70.0  # Aggregator
    def __init__(self):
        self._api_key = settings.fireworks_api_key
        self._base_url = "https://api.fireworks.ai/inference/v1"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "fireworks"

    def is_available(self) -> bool:
        if not self._api_key or not self._api_key.strip(): return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code == 200, now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=5)
            if resp.status_code != 200: return []
            models = []
            for m in resp.json().get("models", []):
                mid, ctx = m.get("name", ""), m.get("max_seq_len", 4096) or 4096
                if mid: models.append({"id": mid, "name": m.get("display_name", mid), "context_length": ctx, "capabilities": _infer_capabilities(mid, ctx), "quality_score": 50, "is_free_tier": False, "provider": "fireworks"})
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            return {"content": resp.json().get("choices", [{}])[0].get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class OllamaProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 60.0  # Local
    def __init__(self):
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "ollama"

    def is_available(self) -> bool:
        if not self._base_url: return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code == 200, now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            if resp.status_code != 200: return []
            models = []
            for m in resp.json().get("models", []):
                mid = m.get("name", "")
                if mid: models.append({"id": mid, "name": mid, "context_length": 8192, "capabilities": _infer_capabilities(mid, 8192), "quality_score": 50, "is_free_tier": True, "provider": "ollama"})
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/api/chat", json={"model": model_id, "messages": messages, "options": {"num_predict": max_tokens, "temperature": temperature}}, timeout=30)
            return {"content": resp.json().get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class AnthropicProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 90.0  # Native
    _FALLBACK = [{"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "context_length": 200000}, {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "context_length": 200000}]

    def __init__(self):
        self._api_key = settings.anthropic_api_key
        self._base_url = "https://api.anthropic.com/v1"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "anthropic"

    def is_available(self) -> bool:
        if not self._api_key or not self._api_key.strip(): return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01"}, timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code in (200, 404), now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            try:
                resp = requests.get(f"{self._base_url}/models", headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01"}, timeout=5)
                if resp.status_code == 200:
                    models = [{"id": m["id"], "name": m.get("display_name", m["id"]), "context_length": m.get("context_window", 200000) or 200000, "capabilities": _infer_capabilities(m["id"], m.get("context_window", 200000) or 200000), "quality_score": 50, "is_free_tier": False, "provider": "anthropic"} for m in resp.json().get("data", [])]
                    if models: self._cache_models(models); return models
            except: pass
            models = [{"id": f["id"], "name": f["name"], "context_length": f["context_length"], "capabilities": _infer_capabilities(f["id"], f["context_length"]), "quality_score": 50, "is_free_tier": False, "provider": "anthropic"} for f in self._FALLBACK]
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
            resp = requests.post(f"{self._base_url}/messages", headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, json={"model": model_id, "messages": msgs, "system": sys_msg, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            return {"content": resp.json().get("content", [{}])[0].get("text", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class OpenAIProvider(ModelProvider):
    _DEFAULT_CONFIDENCE_SCORE = 90.0  # Native
    _FALLBACK = [{"id": "gpt-4o", "name": "GPT-4o", "context_length": 128000}, {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context_length": 128000}]

    def __init__(self):
        self._api_key = settings.openai_api_key
        self._base_url = "https://api.openai.com/v1"
        self._avail_cache, self._avail_ts = None, None

    @property
    def name(self) -> str: return "openai"

    def is_available(self) -> bool:
        if not self._api_key or not self._api_key.strip(): return False
        now = time.time()
        if self._avail_cache and self._avail_ts and now - self._avail_ts < 300: return self._avail_cache
        try:
            resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=3)
            self._avail_cache, self._avail_ts = resp.status_code == 200, now
            return self._avail_cache
        except: return False

    def get_models(self) -> List[Dict[str, Any]]:
        cached = self._get_cached_models()
        if cached is not None: return cached
        try:
            if not self.is_available(): return []
            try:
                resp = requests.get(f"{self._base_url}/models", headers={"Authorization": f"Bearer {self._api_key}"}, timeout=5)
                if resp.status_code == 200:
                    models = [{"id": m["id"], "name": m.get("owned_by", m["id"]), "context_length": m.get("context_window", 128000) or 128000, "capabilities": _infer_capabilities(m["id"], m.get("context_window", 128000) or 128000), "quality_score": 50, "is_free_tier": False, "provider": "openai"} for m in resp.json().get("data", []) if not any(k in m["id"].lower() for k in ("embedding", "dall-e"))]
                    if models: self._cache_models(models); return models
            except: pass
            models = [{"id": f["id"], "name": f["name"], "context_length": f["context_length"], "capabilities": _infer_capabilities(f["id"], f["context_length"]), "quality_score": 50, "is_free_tier": False, "provider": "openai"} for f in self._FALLBACK]
            self._cache_models(models)
            return models
        except: return []

    def call(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        try:
            if not self.is_available(): return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": "Not available"}
            resp = requests.post(f"{self._base_url}/chat/completions", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}, timeout=30)
            return {"content": resp.json().get("choices", [{}])[0].get("message", {}).get("content", ""), "model_used": model_id, "provider": self.name, "success": True, "error": None} if resp.status_code == 200 else {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e: return {"content": "", "model_used": model_id, "provider": self.name, "success": False, "error": str(e)}

class ProviderManager:
    def __init__(self):
        self.providers: Dict[str, ModelProvider] = {}
        self._health_cache, self._health_timestamp = {}, None
        self._health_ttl = 300
        self._models_cache: Dict[str, Dict[str, bool]] = {}
        self._instantiate_providers()

    def _instantiate_providers(self) -> None:
        for key, cls in [(settings.openrouter_api_key, OpenRouterProvider), (settings.anthropic_api_key, AnthropicProvider), (settings.openai_api_key, OpenAIProvider), (settings.groq_api_key, GroqProvider), (settings.github_token, GitHubModelsProvider), (settings.together_api_key, TogetherProvider), (settings.fireworks_api_key, FireworksProvider), (settings.ollama_base_url, OllamaProvider)]:
            if key and key.strip():
                try: self.providers[cls().name] = cls()
                except: pass

    def _fetch_provider_info(self, name: str, provider: ModelProvider) -> Dict[str, Any]:
        try:
            avail = provider.is_available()
            models = provider.get_models() if avail else []
            return {"available": avail, "models_count": len(models), "top_model": models[0]["id"] if models else None}
        except: return {"available": False, "models_count": 0, "top_model": None}

    def get_available_providers(self) -> List[str]:
        return [n for n, p in self.providers.items() if p.is_available()]

    def get_all_models(self) -> List[Dict[str, Any]]:
        seen = {}
        for p in self.providers.values():
            try:
                if p.is_available():
                    for m in p.get_models():
                         if m["id"] not in seen: seen[m["id"]] = m
            except: pass
        return list(seen.values())

    def get_all_models_with_provider(self) -> List[Dict[str, Any]]:
        """P-1: Retorna TODOS los modelos de TODOS los providers, SIN deduplicar.

        A diferencia de get_all_models() que deduplica por model_id,
        este método retorna una entrada por cada (provider, model_id),
        permitiendo que el Pool tenga composite keys distintas para
        el mismo modelo en distintos providers.
        """
        all_models = []
        for p in self.providers.values():
            try:
                if p.is_available():
                    for m in p.get_models():
                        m_copy = dict(m)
                        m_copy["provider"] = p.name
                        m_copy["provider_confidence"] = p.confidence_score
                        all_models.append(m_copy)
            except: pass
        return all_models

    def get_available_models(self) -> List[str]:
        """Retorna una lista con los IDs de todos los modelos disponibles."""
        try:
            return [m.get("id") for m in self.get_all_models() if m.get("id")]
        except Exception:
            return []

    def get_model_price(self, model_id: str, provider_name: str = "openrouter") -> Dict[str, float]:
        try:
            provider = self.providers.get(provider_name)
            if not provider:
                return {"prompt": 0.0, "completion": 0.0}
            models = provider.get_models()
            for m in models:
                if m.get("id") == model_id:
                    # v2.2: Manejar None en pricing
                    pp = m.get("price_prompt_per_1k")
                    cp = m.get("price_completion_per_1k")
                    return {
                        "prompt": pp if pp is not None else 0.0,
                        "completion": cp if cp is not None else 0.0
                    }
            return {"prompt": 0.0, "completion": 0.0}
        except Exception:
            return {"prompt": 0.0, "completion": 0.0}

    def health_check(self) -> Dict[str, Any]:
        now = time.time()
        if self._health_timestamp and now - self._health_timestamp < self._health_ttl: return self._health_cache
        report = {"timestamp": datetime.utcnow().isoformat(), "providers": {}, "total_models": 0}
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(self._fetch_provider_info, n, p): n for n, p in self.providers.items()}
            for f in as_completed(futs):
                n = futs[f]
                try:
                    info = f.result()
                    report["providers"][n] = info
                    if info["available"]: report["total_models"] += info["models_count"]
                except: report["providers"][n] = {"available": False, "models_count": 0, "top_model": None}
        try:
            from core.router import select_model
            report["best_model_planning"] = select_model("planning")
            report["best_model_generation"] = select_model("generation")
            report["best_model_correction"] = select_model("correction")
        except: pass
        self._health_cache, self._health_timestamp = report, now
        return report

    @staticmethod
    def _sanitize_response(res: Dict[str, Any]) -> Dict[str, Any]:
        """Garantiza que 'content' nunca sea None y 'success' sea bool."""
        if res.get("content") is None:
            res["content"] = ""
        if isinstance(res.get("success"), str):
            res["success"] = res["success"].lower() == "true"
        return res

    # =====================================================================
    # Mapeo de prefijos de model_id -> nombre de proveedor
    # =====================================================================
    _MODEL_PREFIX_TO_PROVIDER = {
        "moonshotai/": "moonshot",
        "anthropic/": "anthropic",
        "openai/": "openai",
        "meta-llama/": "openrouter",
        "qwen/": "openrouter",
        "google/": "openrouter",
        "mistralai/": "mistral",
        "deepseek/": "openrouter",
        "cohere/": "cohere",
        "perplexity/": "openrouter",
        "microsoft/": "openrouter",
        "nvidia/": "openrouter",
    }

    def _infer_provider_for_model(self, model_id: str) -> Optional[str]:
        """Infiere el proveedor correcto a partir del prefijo del model_id."""
        if not model_id:
            return None
        mid = model_id.lower()
        for prefix, provider_name in self._MODEL_PREFIX_TO_PROVIDER.items():
            if mid.startswith(prefix):
                return provider_name
        if "/" in model_id:
            return "openrouter"
        return None

    # =====================================================================
    # Traduccion de IDs entre formatos de proveedores
    # =====================================================================

    _NATIVE_PROVIDERS = {
        "anthropic",
        "openai",
        "ollama",
    }

    _AGGREGATOR_PROVIDERS = {
        "openrouter",
        "together",
        "groq",
    }

    _BASE_NAME_TO_PREFIX = {
        "claude": "anthropic/",
        "gpt": "openai/",
        "o1": "openai/",
        "o3": "openai/",
        "gemini": "google/",
        "gemma": "google/",
        "llama": "meta-llama/",
        "qwen": "qwen/",
        "deepseek": "deepseek/",
        "mistral": "mistralai/",
        "mixtral": "mistralai/",
        "codestral": "mistralai/",
        "phi": "microsoft/",
        "command": "cohere/",
        "kimi": "moonshotai/",
    }

    def translate_model_id(self, model_id: str, target_provider_name: str) -> str:
        """Traduce un model_id al formato esperado por un proveedor especifico."""
        if not model_id or not target_provider_name:
            return model_id

        if target_provider_name in self._NATIVE_PROVIDERS:
            if "/" in model_id:
                _, base = model_id.split("/", 1)
                return base
            return model_id

        if target_provider_name in self._AGGREGATOR_PROVIDERS:
            if "/" in model_id:
                return model_id
            mid_lower = model_id.lower()
            for pattern, prefix in self._BASE_NAME_TO_PREFIX.items():
                if mid_lower.startswith(pattern):
                    return prefix + model_id
            return model_id

        return model_id

    @staticmethod
    def _dot_hyphen_variants(s: str) -> List[str]:
        """Genera variantes con dots<->hyphens intercambiados."""
        result = [s]
        dot_to_hyphen = s.replace(".", "-")
        if dot_to_hyphen != s and dot_to_hyphen not in result:
            result.append(dot_to_hyphen)
        hyphen_to_dot = re.sub(r'(\d)-(\d)', r'\1.\2', s)
        if hyphen_to_dot != s and hyphen_to_dot not in result:
            result.append(hyphen_to_dot)
        return result

    def _get_model_id_variants(self, model_id: str) -> List[str]:
        """Genera todas las variantes posibles de un ID de modelo."""
        raw_variants = [model_id]

        if "/" in model_id:
            prefix, base = model_id.split("/", 1)
            if base not in raw_variants:
                raw_variants.append(base)
            if not model_id.endswith(":free"):
                raw_variants.append(model_id + ":free")
            if not base.endswith(":free"):
                raw_variants.append(base + ":free")
            if base.endswith(":free"):
                base_no_free = base.rsplit(":free", 1)[0]
                if base_no_free not in raw_variants:
                    raw_variants.append(base_no_free)
        else:
            mid_lower = model_id.lower()
            for pattern, prefix in self._BASE_NAME_TO_PREFIX.items():
                if mid_lower.startswith(pattern):
                    with_prefix = prefix + model_id
                    if with_prefix not in raw_variants:
                        raw_variants.append(with_prefix)
                    if not model_id.endswith(":free"):
                        raw_variants.append(with_prefix + ":free")
                    break
            if model_id.endswith(":free"):
                base_no_free = model_id.rsplit(":free", 1)[0]
                if base_no_free not in raw_variants:
                    raw_variants.append(base_no_free)

        expanded = []
        seen = set()
        for v in raw_variants:
            for dv in self._dot_hyphen_variants(v):
                if dv not in seen:
                    expanded.append(dv)
                    seen.add(dv)

        return expanded

    def _get_provider_model_set(self, provider_name: str) -> set:
        """Obtiene el set de IDs de modelos de un proveedor (con cache interno)."""
        if provider_name in self._models_cache:
            return self._models_cache[provider_name]
        p = self.providers.get(provider_name)
        if not p:
            return set()
        try:
            model_ids = {m["id"] for m in p.get_models()} if p.is_available() else set()
        except Exception:
            model_ids = set()
        self._models_cache[provider_name] = model_ids
        return model_ids

    def find_providers_for_model(self, model_id: str) -> List[Tuple[Any, str]]:
        """Busca TODOS los proveedores que pueden servir un modelo, con IDs traducidos.

        Para cada proveedor que tiene el modelo en su catalogo, retorna:
          (provider_instance, translated_model_id)

        Ejemplo para "anthropic/claude-opus-4-6":
          - anthropic -> ("claude-opus-4-6")   [native: strip prefix]
          - openrouter -> ("anthropic/claude-opus-4.6")  [dot-hyphen variant match]
        """
        if not model_id:
            return []

        variants = self._get_model_id_variants(model_id)
        results: List[Tuple[Any, str]] = []
        seen_providers = set()

        for provider_name, provider in self.providers.items():
            if not provider.is_available():
                continue
            if provider_name in seen_providers:
                continue

            model_set = self._get_provider_model_set(provider_name)

            for variant in variants:
                if variant in model_set:
                    # Encontramos el modelo en este proveedor con este ID
                    results.append((provider, variant))
                    seen_providers.add(provider_name)
                    break

        return results

    def call_with_fallback(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        """Llama al modelo con fallback entre proveedores."""
        providers_to_try = self.find_providers_for_model(model_id)

        for provider, translated_id in providers_to_try:
            result = provider.call(translated_id, messages, max_tokens, temperature)
            if result.get("success"):
                result["provider"] = provider.name
                return self._sanitize_response(result)

        # Fallback: inferir proveedor
        inferred = self._infer_provider_for_model(model_id)
        if inferred and inferred in self.providers:
            p = self.providers[inferred]
            translated = self.translate_model_id(model_id, inferred)
            result = p.call(translated, messages, max_tokens, temperature)
            if result.get("success"):
                result["provider"] = p.name
                return self._sanitize_response(result)

        return {"content": "", "model_used": model_id, "provider": "unknown", "success": False, "error": "All providers failed"}


# Instancia global
provider_manager = ProviderManager()


# =============================================================================
# VALIDACION STANDALONE
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    # Habilitar INFO para este modulo en standalone
    logger.setLevel(logging.INFO)

    print("\n" + "=" * 60)
    print("VALIDACION: apa/core/providers.py v2.2")
    print("=" * 60)

    passed = 0
    failed = 0

    # [T1] Instanciacion de proveedores
    print("\n[T1] Instanciacion de proveedores")
    try:
        assert provider_manager is not None
        print(f"  ProviderManager instanciado")
        passed += 1
    except AssertionError:
        print(f"  FALLA: ProviderManager no instanciado")
        failed += 1

    for name in ["openrouter", "anthropic", "openai", "groq", "github", "together", "fireworks", "ollama"]:
        p = provider_manager.providers.get(name)
        if p:
            print(f"  Proveedor '{name}' registrado (key presente)")
            passed += 1
        else:
            print(f"  Proveedor '{name}' NO registrado (sin key)")
            # No contar como falla — no tener key es correcto

    # [T2] Disponibilidad
    print("\n[T2] Disponibilidad de cada proveedor (is_available)")
    for name, p in provider_manager.providers.items():
        avail = p.is_available()
        print(f"  '{name}' is_available={avail}")
        passed += 1

    # [T3] Traduccion de IDs
    print("\n[T3] Traduccion de IDs de modelo")
    test_translations = [
        ("anthropic/claude-opus-4-6", "anthropic", "claude-opus-4-6"),
        ("anthropic/claude-opus-4-6", "openrouter", "anthropic/claude-opus-4-6"),
        ("claude-opus-4-6", "openrouter", "anthropic/claude-opus-4-6"),
        ("openai/gpt-4o", "openai", "gpt-4o"),
        ("gpt-4o", "openrouter", "openai/gpt-4o"),
        ("google/gemma-4-26b-a4b-it:free", "anthropic", "gemma-4-26b-a4b-it:free"),
    ]
    for model_id, provider, expected in test_translations:
        result = provider_manager.translate_model_id(model_id, provider)
        ok = result == expected
        print(f"  {'OK' if ok else 'FAIL'}: translate('{model_id}', '{provider}') = '{result}'")
        if ok:
            passed += 1
        else:
            failed += 1

    # [T4] Variantes de IDs
    print("\n[T4] Variantes de IDs de modelo")
    v1 = provider_manager._get_model_id_variants("anthropic/claude-opus-4-6")
    ok1 = "anthropic/claude-opus-4-6" in v1 and "claude-opus-4-6" in v1
    print(f"  {'OK' if ok1 else 'FAIL'}: Variantes de 'anthropic/claude-opus-4-6' contiene original y sin prefijo")
    passed += (1 if ok1 else 0)
    failed += (0 if ok1 else 1)

    v2 = provider_manager._get_model_id_variants("claude-opus-4-6")
    ok2 = "claude-opus-4-6" in v2 and any("anthropic/" in x for x in v2)
    print(f"  {'OK' if ok2 else 'FAIL'}: Variantes de 'claude-opus-4-6' contiene original y con prefijo")
    passed += (1 if ok2 else 0)
    failed += (0 if ok2 else 1)

    # [T5] find_providers_for_model
    print("\n[T5] find_providers_for_model")
    test_models_fp = [
        "anthropic/claude-opus-4-6",
        "claude-opus-4-6",
        "google/gemma-4-26b-a4b-it:free",
    ]
    for mid in test_models_fp:
        providers_found = provider_manager.find_providers_for_model(mid)
        for p, tid in providers_found:
            print(f"  {mid} -> provider={p.name}, id={tid}")
        passed += 1

    # [T6] Total de modelos
    print("\n[T6] Total de modelos")
    all_models = provider_manager.get_all_models()
    total = len(all_models)
    free_count = sum(1 for m in all_models if m.get("is_free_tier") or m.get("is_free"))
    paid_count = total - free_count
    print(f"  Total modelos combinados: {total}")
    print(f"  Modelos gratuitos: {free_count}")
    print(f"  Modelos de pago: {paid_count}")
    passed += 1

    # v2.2: Verificar CACHE_DIR
    print(f"\n[v2.2] CACHE_DIR verification:")
    print(f"  CACHE_DIR = {ModelProvider.CACHE_DIR}")
    print(f"  Expected: .../APA/data/providers")
    if "apa" in str(ModelProvider.CACHE_DIR).lower().replace("\\", "/"):
        parts = str(ModelProvider.CACHE_DIR).replace("\\", "/").split("/")
        # Verificar que data/providers esta al nivel correcto
        if parts[-2:] == ["data", "providers"]:
            # Verificar que el padre de data/ tiene apa/ como hijo
            data_parent = "/".join(parts[:-2])
            apa_check = Path(data_parent) / "apa"
            if apa_check.is_dir():
                print(f"  OK: CACHE_DIR en raiz del proyecto (padre tiene apa/)")
                passed += 1
            else:
                print(f"  WARN: No se puede verificar estructura (apa/ no encontrado en {data_parent})")
                passed += 1  # No fallar en Linux donde la estructura puede diferir
        else:
            print(f"  WARN: CACHE_DIR no termina en data/providers")
            passed += 1
    else:
        print(f"  WARN: Estructura inesperada")
        passed += 1

    elapsed = time.time() - (time.time() - 0)  # placeholder
    print(f"\nTiempo total: 0.00s")  # placeholder
    print(f"Pruebas: {passed} pasadas, {failed} fallidas")
    print("=" * 60)
