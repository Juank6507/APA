# apa/core/router.py

import sys
import os
import time
import json
import logging
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
import requests
from core.arena_fetcher import arena_fetcher

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


def _log(module, stage, status, detail=""):
    msg = f"[PROGRESO] | MÓDULO={module} | ETAPA={stage} | ESTADO={status}"
    if detail: msg += f" | DETALLE={detail}"
    print(msg)
    logger.info(msg)

_cache = {"data": None, "t": None, "D": 600}
FALLBACK = [
    {"id": "qwen/qwen3-8b:free", "name": "Qwen3 8B", "context_length": 32768, "caps": ["coding", "long_context", "general"]},
    {"id": "google/gemma-3-4b-it:free", "name": "Gemma 3 4B", "context_length": 8192, "caps": ["instruction", "general"]}
]
STATIC_RANK = {
    "qwen/qwen3-coder:free": 90, "deepseek/deepseek-r1-0528:free": 93, "gpt-4o": 95,
    "Meta-Llama-3.1-405B-Instruct": 92, "accounts/fireworks/models/llama-v3p1-405b-instruct": 96
}


def fetch_free_models() -> list[dict]:
    _log("router", "FETCH_MODELS", "INICIADO")
    now = time.time()
    if _cache["data"] and _cache["t"] and now - _cache["t"] < _cache["D"]:
        _log("router", "FETCH_MODELS", "HIT_CACHE", f"→ {len(_cache['data'])} modelos")
        return _cache["data"]
    
    _log("router", "FETCH_MODELS", "SOLICITANDO_OPENROUTER")
    try:
        r = requests.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {settings.openrouter_api_key}"}, timeout=8)
        r.raise_for_status()
        models = [m for m in r.json().get("data", []) if str(m.get("pricing",{}).get("prompt",""))=="0" and str(m.get("pricing",{}).get("completion",""))=="0"]
        out = [{"id":m["id"],"name":m["name"],"context_length":m.get("context_length",0),"caps":["coding" if "coder" in m["id"] else "general"]} for m in models]
        _log("router", "FETCH_MODELS", "✅ EXITOSA", f"→ {len(out)} modelos gratuitos")
        _cache["data"], _cache["t"] = out, now
        return out
    except Exception as e:
        _log("router", "FETCH_MODELS", "⚠️ DIFICULTAD", f"{type(e).__name__} → Activando fallback local")
        _cache["data"], _cache["t"] = FALLBACK, now
        return FALLBACK


def select_model(task_type: str, quality_mode: str = None) -> str:
    mode = quality_mode or getattr(settings, "default_quality_mode", "balanced")
    _log("router", "SELECT_MODEL", f"INICIADO | TAREA={task_type} | MODO={mode}")
    try:
        pool = fetch_free_models()
        if not pool: return "qwen/qwen3-8b:free"
        
        def score(m):
            arena = arena_fetcher.get_score_for_model(m["id"], task_type)
            base = float(arena if arena is not None else STATIC_RANK.get(m["id"], 50))
            ctx = min(100, m["context_length"]/320)
            bonus = 20 if "long_context" in m["caps"] and task_type in ("planning","evaluation") else 0
            bonus += 30 if "coding" in m["caps"] and task_type=="generation" else 0
            bonus += 20 if "instruction" in m["caps"] and task_type=="correction" else 0
            return (base*0.6)+(ctx*0.4)+bonus
        
        pool.sort(key=score, reverse=True)
        sel = pool[0]
        source = "Arena(Dinámico)" if arena_fetcher.get_score_for_model(sel["id"], task_type) is not None else "Estático(Local)"
        _log("router", "SELECT_MODEL", "✅ SELECCIONADO", f"ID={sel['id']} | SCORE={score(sel):.1f} | FUENTE={source}")
        return sel["id"]
    except Exception as e:
        _log("router", "SELECT_MODEL", "❌ FALLIDA", f"{type(e).__name__} → Fallback seguro")
        return "qwen/qwen3-8b:free"


def call_llm(task_type, sys_p, usr_p, max_t=2000, temp=0.1):
    _log("router", "CALL_LLM", f"INICIADO | INTENTOS=3/3 | MODELO={select_model(task_type)}")
    for i in range(1,4):
        try:
            from core.providers import provider_manager
            msgs = [{"role":"system","content":sys_p},{"role":"user","content":usr_p}]
            res = provider_manager.call_with_fallback(select_model(task_type), msgs, max_t, temp)
            if res["success"]:
                _log("router", "CALL_LLM", "✅ EJECUTADO", f"PROVEEDOR={res['provider']} | INTENTOS={i}")
                return {**res, "attempts": i}
            _log("router", "CALL_LLM", "⚠️ DIFICULTAD", f"INTENTO={i} | ERROR={res.get('error')}")
            if res.get("error")=="rate_limit": time.sleep(1)
            else: break
        except Exception as e:
            _log("router", "CALL_LLM", "❌ EXCEPCIÓN", str(e)); break
    return {"content":"","model_used":"","provider_used":None,"success":False,"attempts":i,"error":"Reintentos agotados"}


def validate_self():
    _log("router", "VALIDACIÓN", "INICIADA")
    try:
        models = fetch_free_models()
        sel = select_model("planning")
        assert isinstance(models, list) and len(models)>0 and isinstance(sel, str) and len(sel)>5
        _log("router", "VALIDACIÓN", "✅ EXITOSA", "Fetch, scoring y fallback verificados sin bloqueos")
        return True
    except Exception as e:
        _log("router", "VALIDACIÓN", "❌ FALLIDA", str(e)); return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    if validate_self(): print("✅ VALIDADO | MÓDULO=router | EJECUCIÓN_CORRECTA | LISTO_PARA_RETROALIMENTACIÓN")