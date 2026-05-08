# apa/core/providers.py
import sys
import os
import time
import json
import logging
import requests
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

def _log(module: str, stage: str, status: str, detail: str = "") -> None:
    msg = f"[PROGRESO] | MÓDULO={module} | ETAPA={stage} | ESTADO={status}"
    if detail:
        msg += f" | DETALLE={detail}"
    logger.info(msg)

def _infer_capabilities(model_id: str, context_length: int) -> List[str]:
    caps = []
    mid = model_id.lower()
    if "coder" in mid or "code" in mid or "coding" in mid:
        caps.append("coding")
    if "instruct" in mid or "instruction" in mid:
        caps.append("instruction")
    if context_length >= 32000:
        caps.append("long_context")
    if "reason" in mid or "thinking" in mid:
        caps.append("reasoning")
    return caps or ["general"]

class ModelProvider(ABC):
    CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "providers"
    CACHE_TTL = 3600

    @property
    @abstractmethod
    def name(self) -> str: pass

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
                ctx_len = m.get("context_length", 8192)
                caps = _infer_capabilities(model_id, ctx_len)
                pricing = m.get("pricing", {})
                # Extraer precios de prompt y completion (OpenRouter retorna strings)
                try:
                    prompt_price = float(pricing.get("prompt", 0)) if pricing.get("prompt") else 0.0
                except (ValueError, TypeError):
                    prompt_price = 0.0
                    logger.warning(f"OpenRouter: precio prompt inválido para {model_id}")
                try:
                    completion_price = float(pricing.get("completion", 0)) if pricing.get("completion") else 0.0
                except (ValueError, TypeError):
                    completion_price = 0.0
                    logger.warning(f"OpenRouter: precio completion inválido para {model_id}")
                models.append({
                    "id": model_id,
                    "name": m.get("name", model_id),
                    "context_length": ctx_len,
                    "capabilities": caps,
                    "quality_score": 50,
                    "is_free_tier": False,
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
                mid, ctx = m.get("id", ""), m.get("context_window", 8192)
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
                mid, ctx = m.get("id", ""), m.get("context_window", 8192)
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
                mid, ctx = m.get("id", ""), m.get("context_length", 4096)
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
                mid, ctx = m.get("name", ""), m.get("max_seq_len", 4096)
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
                    models = [{"id": m["id"], "name": m.get("display_name", m["id"]), "context_length": m.get("context_window", 200000), "capabilities": _infer_capabilities(m["id"], m.get("context_window", 200000)), "quality_score": 50, "is_free_tier": False, "provider": "anthropic"} for m in resp.json().get("data", [])]
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
                    models = [{"id": m["id"], "name": m.get("owned_by", m["id"]), "context_length": m.get("context_window", 128000), "capabilities": _infer_capabilities(m["id"], m.get("context_window", 128000)), "quality_score": 50, "is_free_tier": False, "provider": "openai"} for m in resp.json().get("data", []) if not any(k in m["id"].lower() for k in ("embedding", "dall-e"))]
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

    # A1: Nuevo método añadido según contrato
    def get_available_models(self) -> List[str]:
        """
        Retorna una lista con los IDs de todos los modelos disponibles
        (provenientes de todos los proveedores que están disponibles).
        """
        try:
            return [m.get("id") for m in self.get_all_models() if m.get("id")]
        except Exception:
            return []

    def get_model_price(self, model_id: str, provider_name: str = "openrouter") -> Dict[str, float]:
        """
        Retorna los precios de un modelo específico (prompt y completion por 1k tokens).
        Solo soporta OpenRouter por ahora; otros proveedores retornan {0.0, 0.0}.
        """
        try:
            provider = self.providers.get(provider_name)
            if not provider:
                return {"prompt": 0.0, "completion": 0.0}
            models = provider.get_models()
            for m in models:
                if m.get("id") == model_id:
                    return {
                        "prompt": m.get("price_prompt_per_1k", 0.0),
                        "completion": m.get("price_completion_per_1k", 0.0)
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

    def call_with_fallback(self, model_id: str, messages: List[Dict], max_tokens: int = 2000, temperature: float = 0.1) -> Dict[str, Any]:
        target = None
        for p in self.providers.values():
            try:
                if any(m["id"] == model_id for m in p.get_models()): target = p; break
            except: continue
        if not target:
            for p in self.providers.values():
                try:
                    if p.is_available(): target = p; break
                except: continue
        if not target: return {"content": "", "model_used": model_id, "provider": None, "success": False, "error": "No providers available"}
        res = target.call(model_id, messages, max_tokens, temperature)
        if res.get("success"): return res
        try:
            for m in sorted(self.get_all_models(), key=lambda x: x.get("context_length", 0), reverse=True):
                if m["id"] != model_id:
                    fb = self.providers.get(m["provider"])
                    if fb and fb.is_available():
                        fr = fb.call(m["id"], messages, max_tokens, temperature)
                        if fr.get("success"): return fr
        except: pass
        return res

provider_manager = ProviderManager()

if __name__ == "__main__":
    import time
    import logging
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from config.settings import settings
    from core.router import select_model

    loggers_to_silence = ["core.router", "core.providers", "core.arena_fetcher"]
    original_levels = {}
    for name in loggers_to_silence:
        lg = logging.getLogger(name)
        original_levels[name] = lg.level
        lg.setLevel(logging.ERROR)

    print("\n" + "=" * 60)
    print("🔍 APA - DIAGNÓSTICO DE PROVEEDORES Y RESILIENCIA")
    print("=" * 60)

    start_time = time.time()
    manager = ProviderManager()

    print("\n📡 Proveedores activos y modelos")
    print("-" * 40)
    report = manager.health_check()
    available_providers = [n for n, i in report["providers"].items() if i["available"]]
    print(f"Proveedores activos: {available_providers} ({len(available_providers)}/{len(report['providers'])})")
    print(f"Total modelos combinados: {report['total_models']}")

    print("\n🎯 Mejores modelos por tarea")
    print("-" * 40)
    try:
        print(f"Planning   : {select_model('planning')}")
        print(f"Generation : {select_model('generation')}")
        print(f"Correction : {select_model('correction')}")
    except Exception as e:
        print(f"⚠️ No se pudieron determinar: {e}")

    print("\n🛡️ Prueba de resiliencia (call_with_fallback)")
    print("-" * 40)
    models = manager.get_all_models()
    if models:
        test_model = models[0]["id"]
        print(f"Modelo de prueba: {test_model}")
        result = manager.call_with_fallback(test_model, [{"role": "user", "content": "Di 'OK'"}], max_tokens=10)
        print(f"Resultado: success={result['success']}, attempts={result.get('attempts', 0)}")
        if not result['success']: print(f"Error: {result.get('error', 'Desconocido')}")
    else:
        print("⚠️ No hay modelos para probar")

    print("\n💰 Prueba de precios OpenRouter")
    print("-" * 40)
    try:
        for model_id in ["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "google/gemini-flash-1.5"]:
            prices = manager.get_model_price(model_id, "openrouter")
            if prices["prompt"] > 0 or prices["completion"] > 0:
                print(f"{model_id}: prompt=${prices['prompt']:.6f}/1k, completion=${prices['completion']:.6f}/1k")
            else:
                print(f"{model_id}: sin precio disponible")
    except Exception as e:
        print(f"⚠️ Error en prueba de precios: {e}")

    print("\n⏱️ Tiempo total")
    print("-" * 40)
    print(f"{time.time() - start_time:.2f} segundos")

    for n, lvl in original_levels.items(): logging.getLogger(n).setLevel(lvl)
    print("\n" + "=" * 60)
    print("✅ DIAGNÓSTICO COMPLETADO")
    print("=" * 60)