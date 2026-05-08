import sys
import os
import time
import json
import logging
import re
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings

import requests

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

_cache = {"data": None, "timestamp": None}
_CACHE_DURATION = 600

FALLBACK_MODELS = [
    {
        "id": "qwen/qwen3-8b:free",
        "name": "Qwen3 8B (free)",
        "context_length": 32768,
        "capabilities": ["coding", "long_context", "general"]
    },
    {
        "id": "google/gemma-3-4b-it:free",
        "name": "Gemma 3 4B (free)",
        "context_length": 8192,
        "capabilities": ["instruction", "general"]
    }
]

MODEL_QUALITY_RANKING = {
    "nvidia/nemotron-3-super-120b-a12b:free": 95,
    "qwen/qwen3-coder:free": 90,
    "qwen/qwen3-30b-a3b:free": 85,
    "qwen/qwen3-8b:free": 80,
    "google/gemma-4-31b-it:free": 75,
    "google/gemma-4-26b-a4b-it:free": 70,
    "google/gemma-3-27b-it:free": 65,
    "microsoft/phi-4-reasoning-plus:free": 88,
    "microsoft/phi-4:free": 82,
    "deepseek/deepseek-r1-0528:free": 93,
    "deepseek/deepseek-v3-0324:free": 91,
    "meta-llama/llama-4-maverick:free": 87,
    "meta-llama/llama-4-scout:free": 83,
    "google/gemma-3-12b-it:free": 60,
    "google/gemma-3-4b-it:free": 50,
    "liquid/lfm-2.5-1.2b-instruct:free": 40,
    "qwen/qwen3-next-80b-a3b-instruct:free": 84,
    "llama-3.3-70b-versatile": 88,
    "llama-3.1-70b-versatile": 86,
    "Meta-Llama-3.1-405B-Instruct": 92,
    "Mistral-large": 88,
    "gpt-4o": 95
}

FREE_TIER_MODELS = [
    {
        "id": "google/gemini-2.5-pro-preview",
        "name": "Gemini 2.5 Pro (free tier)",
        "context_length": 1000000,
        "capabilities": ["long_context", "instruction"],
        "quality_score": 97,
        "daily_limit": 50
    },
    {
        "id": "google/gemini-2.5-flash-preview",
        "name": "Gemini 2.5 Flash (free tier)",
        "context_length": 1000000,
        "capabilities": ["long_context", "instruction"],
        "quality_score": 88,
        "daily_limit": 200
    },
    {
        "id": "google/gemini-2.0-flash-exp:free",
        "name": "Gemini 2.0 Flash Exp (free tier)",
        "context_length": 1048576,
        "capabilities": ["long_context", "instruction"],
        "quality_score": 85,
        "daily_limit": 200
    },
    {
        "id": "anthropic/claude-3.5-haiku",
        "name": "Claude 3.5 Haiku (free tier)",
        "context_length": 200000,
        "capabilities": ["long_context", "instruction", "coding"],
        "quality_score": 92,
        "daily_limit": 25
    },
    {
        "id": "deepseek/deepseek-r1",
        "name": "DeepSeek R1 (free tier)",
        "context_length": 65536,
        "capabilities": ["long_context", "instruction", "coding"],
        "quality_score": 94,
        "daily_limit": 50
    },
    {
        "id": "mistralai/mistral-small-3.1-24b-instruct:free",
        "name": "Mistral Small 3.1 24B (free tier)",
        "context_length": 128000,
        "capabilities": ["long_context", "instruction"],
        "quality_score": 78,
        "daily_limit": 100
    }
]


def _infer_capabilities(model_id: str, context_length: int) -> list:
    caps = []
    mid = model_id.lower()
    if "coder" in mid or "code" in mid:
        caps.append("coding")
    if context_length >= 32000:
        caps.append("long_context")
    if "instruct" in mid:
        caps.append("instruction")
    if not caps:
        caps.append("general")
    return caps


def fetch_free_models() -> list[dict]:
    global _cache
    now = time.time()
    
    if _cache["data"] is not None and _cache["timestamp"] is not None:
        if now - _cache["timestamp"] < _CACHE_DURATION:
            logger.debug("Returning cached models")
            return _cache["data"]
    
    logger.info("Fetching free models from OpenRouter...")
    
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch models: {e}")
        return []
    
    filtered = []
    models = data.get("data", [])
    
    for model in models:
        pricing = model.get("pricing", {})
        prompt_price = str(pricing.get("prompt", ""))
        completion_price = str(pricing.get("completion", ""))
        
        if prompt_price == "0" and completion_price == "0":
            model_id = model.get("id", "")
            context_length = model.get("context_length", 0)
            ctx_int = int(context_length) if context_length else 0
            
            filtered.append({
                "id": model_id,
                "name": model.get("name", model_id),
                "context_length": ctx_int,
                "capabilities": _infer_capabilities(model_id, ctx_int)
            })
    
    filtered.sort(key=lambda x: x["context_length"], reverse=True)
    
    if not filtered:
        logger.warning("No free models found, using fallback")
        filtered = FALLBACK_MODELS.copy()
    
    _cache["data"] = filtered
    _cache["timestamp"] = now
    logger.info(f"Found {len(filtered)} free models")
    
    return filtered


def fetch_free_tier_models() -> list[dict]:
    global _cache
    now = time.time()
    
    if _cache.get("free_tier_data") is not None and _cache.get("free_tier_timestamp") is not None:
        if now - _cache["free_tier_timestamp"] < _CACHE_DURATION:
            logger.debug("Returning cached free tier models")
            return _cache["free_tier_data"]
    
    logger.info("Fetching available models from OpenRouter for free tier check...")
    
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch models for free tier check: {e}")
        return []
    
    available_ids = {m.get("id") for m in data.get("data", []) if m.get("id")}
    
    result = []
    for ft_model in FREE_TIER_MODELS:
        if ft_model["id"] in available_ids:
            result.append({
                "id": ft_model["id"],
                "name": ft_model["name"],
                "context_length": ft_model["context_length"],
                "capabilities": ft_model["capabilities"],
                "quality_score": ft_model["quality_score"],
                "is_free_tier": True
            })
    
    _cache["free_tier_data"] = result
    _cache["free_tier_timestamp"] = now
    
    logger.info(f"Free tier models available: {len(result)}/{len(FREE_TIER_MODELS)} from curated list")
    return result


def get_all_available_models() -> list[dict]:
    openrouter_free = fetch_free_models()
    for m in openrouter_free:
        m["provider"] = "openrouter"
        m["quality_score"] = m.get("quality_score",
            MODEL_QUALITY_RANKING.get(m["id"], 50))
        m["is_free_tier"] = False

    openrouter_tier = fetch_free_tier_models()
    for m in openrouter_tier:
        m["provider"] = "openrouter"

    seen = {}
    for m in openrouter_free + openrouter_tier:
        mid = m["id"]
        if mid not in seen or m.get("quality_score", 0) > seen[mid].get("quality_score", 0):
            seen[mid] = m

    try:
        from core.providers import provider_manager
        other_models = [
            m for m in provider_manager.get_all_models()
            if m.get("provider") != "openrouter"
        ]
        for m in other_models:
            mid = m["id"]
            if mid not in seen or m.get("quality_score", 0) > seen[mid].get("quality_score", 0):
                seen[mid] = m
    except Exception as e:
        logger.warning(f"No se pudieron obtener modelos de otros proveedores: {e}")

    combined = list(seen.values())
    combined.sort(key=lambda x: x.get("quality_score", 50), reverse=True)
    return combined


def _filter_text_models(models: list[dict]) -> list[dict]:
    excluded_keywords = ["lyria", "audio", "music", "imagen", "image", "vision", "video", "clip"]
    filtered = []
    for model in models:
        model_id_lower = model["id"].lower()
        if not any(kw in model_id_lower for kw in excluded_keywords):
            filtered.append(model)
    return filtered


def select_model(task_type: str) -> str:
    logger.info(f"Selecting model for task_type: {task_type}")
    
    try:
        all_models = get_all_available_models()
        text_models = _filter_text_models(all_models)
        
        if not text_models:
            logger.warning("No text models available, returning fallback")
            return "qwen/qwen3-8b:free"
        
        def calculate_score(model: dict) -> float:
            ranking_score = float(model.get("quality_score",
                MODEL_QUALITY_RANKING.get(model["id"], 50)))
            context_score = min(100, model["context_length"] / 320)
            context_score = min(100.0, context_score)
            base_score = ranking_score * 0.6 + context_score * 0.4
            
            caps = model.get("capabilities", [])
            bonus = 0
            
            if task_type in ("planning", "evaluation"):
                if "long_context" in caps:
                    bonus += 20
                if "instruction" in caps:
                    bonus += 10
            elif task_type == "generation":
                if "coding" in caps:
                    bonus += 30
                if "long_context" in caps:
                    bonus += 10
            elif task_type == "correction":
                if "instruction" in caps:
                    bonus += 20
                if model["context_length"] > 100000:
                    bonus -= 10
            
            return base_score + bonus
        
        if task_type == "correction":
            fast_models = [
                m for m in text_models
                if m.get("context_length", 0) <= 32000
            ]
            if fast_models:
                selected_model = max(fast_models,
                                     key=lambda x: (
                                         x.get("quality_score",
                                             MODEL_QUALITY_RANKING.get(x["id"], 50))
                                         + (20 if "instruction" in x["capabilities"] else 0)
                                     ))
                criterion = "fast + best quality (ctx<=32k)"
            else:
                instruct = [
                    m for m in text_models
                    if "instruction" in m["capabilities"]
                ]
                if instruct:
                    selected_model = min(instruct,
                                         key=lambda x: x.get("context_length", 999999))
                    criterion = "instruction + min context"
                else:
                    selected_model = min(text_models,
                                         key=lambda x: x.get("context_length", 999999))
                    criterion = "min context_length (fast)"
            final_score = calculate_score(selected_model)
            logger.info(f"Selected model '{selected_model['id']}' for task '{task_type}' (criterion: {criterion}, score: {final_score:.2f})")
            return selected_model["id"]
        else:
            scored = [(m, calculate_score(m)) for m in text_models]
            scored.sort(key=lambda x: x[1], reverse=True)
            
            selected_model = scored[0][0]
            final_score = scored[0][1]
            
            logger.info(f"Selected model '{selected_model['id']}' for task '{task_type}' (score: {final_score:.2f})")
            return selected_model["id"]
        
    except Exception as e:
        logger.error(f"Error in select_model: {e}")
        return "qwen/qwen3-8b:free"


def escalate_model(current_model_id: str) -> str:
    try:
        all_models = get_all_available_models()
        text_models = _filter_text_models(all_models)
        
        if not text_models:
            return current_model_id
        
        for i, model in enumerate(text_models):
            if model["id"] == current_model_id:
                if i < len(text_models) - 1:
                    next_model = text_models[i + 1]["id"]
                    logger.info(f"Escalated from '{current_model_id}' to '{next_model}'")
                    return next_model
                else:
                    logger.info(f"Already at last model, keeping '{current_model_id}'")
                    return current_model_id
        
        logger.warning(f"Model '{current_model_id}' not found in filtered list, returning unchanged")
        return current_model_id
        
    except Exception as e:
        logger.error(f"Error in escalate_model: {e}")
        return current_model_id


def call_llm(
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.1
) -> dict:
    from core.providers import provider_manager
    
    logger.info(f"Calling LLM for task_type: {task_type}")
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    model_id = select_model(task_type)
    last_error = None
    
    for attempt in range(1, 4):
        result = provider_manager.call_with_fallback(
            model_id, messages, max_tokens, temperature
        )
        
        if result["success"]:
            return {
                "content": result["content"],
                "model_used": result["model_used"],
                "provider_used": result["provider"],
                "success": True,
                "attempts": attempt
            }
        
        if result.get("error") == "rate_limit":
            logger.warning(f"Rate limit on model '{model_id}', attempt {attempt}/3")
            model_id = escalate_model(model_id)
            time.sleep(1)
            continue
        
        last_error = result.get("error", "unknown")
        logger.warning(f"LLM call failed on attempt {attempt}: {last_error}")
        break
    
    return {
        "content": "",
        "model_used": model_id,
        "provider_used": None,
        "success": False,
        "attempts": 3,
        "error": last_error
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== PRUEBA 1: fetch_free_models ===")
    models = fetch_free_models()
    print(f"Modelos gratuitos encontrados: {len(models)}")
    for i, model in enumerate(models[:5]):
        print(f"[{i+1}] {model['id']} | ctx:{model['context_length']} | caps:{model['capabilities']}")
    
    print("\n=== PRUEBA 2: select_model por tipo de tarea ===")
    for task in ["planning", "generation", "correction", "evaluation"]:
        model = select_model(task)
        print(f"Tarea '{task}' → modelo: {model}")
    
    print("\n=== PRUEBA 3: escalate_model ===")
    all_m = fetch_free_models()
    text_m = _filter_text_models(all_m)[:3]
    if len(text_m) >= 2:
        first = text_m[0]["id"]
        escalated = escalate_model(first)
        print(f"Escalado desde '{first}' → '{escalated}'")
        print("ESCALADO OK" if escalated != first else "SIN CAMBIO (solo hay un modelo)")
    
    result = escalate_model("modelo/inexistente:free")
    print(f"Modelo inexistente → retorna: {result}")
    print("FALLBACK OK" if result == "modelo/inexistente:free" else "ERROR: no retornó el mismo modelo")
    
    print("\n=== PRUEBA 4: caché ===")
    t1 = time.time()
    fetch_free_models()
    t2 = time.time()
    elapsed = t2 - t1
    print(f"Segunda llamada tardó: {elapsed:.4f}s")
    print("CACHÉ OK" if elapsed < 0.01 else "ADVERTENCIA: caché no funcionó")
    
    print("\n=== PRUEBA 5: call_llm ===")
    result = call_llm(
        task_type="generation",
        system_prompt="Responde solo con JSON válido.",
        user_prompt='{"test": true}'
    )
    print(f"call_llm success: {result['success']}")
    print(f"call_llm model: {result['model_used']}")
    print(f"call_llm attempts: {result['attempts']}")
    if result["success"]:
        print("CALL_LLM OK")
    else:
        print(f"CALL_LLM FALLÓ: {result.get('error')}")
    
    print("\n=== PRUEBA 6: fetch_free_tier_models ===")
    free_tier = fetch_free_tier_models()
    print(f"Modelos free tier disponibles: {len(free_tier)}")
    for m in free_tier:
        print(f"  {m['id']} | score:{m['quality_score']} | ctx:{m['context_length']}")
    
    print(f"\n=== PRUEBA 7: pool combinado ===")
    all_models = get_all_available_models()
    print(f"Total modelos disponibles: {len(all_models)}")
    print(f"Top 5 por quality_score:")
    for m in all_models[:5]:
        tier = "free-tier" if m.get("is_free_tier") else "free"
        provider = m.get("provider", "?")
        print(f"  [{provider}] {m['id']} | score:{m.get('quality_score', 50)}")
    
    print(f"\nSelect model con pool combinado:")
    for task in ["planning", "generation", "correction"]:
        model = select_model(task)
        print(f"  '{task}' → {model}")
    
    print(f"\n=== PRUEBA 8: proveedores disponibles ===")
    from core.providers import provider_manager
    available = provider_manager.get_available_providers()
    print(f"Proveedores activos: {available}")
    all_provider_models = provider_manager.get_all_models()
    print(f"Total modelos todos proveedores: {len(all_provider_models)}")
    print(f"Top 5:")
    for m in all_provider_models[:5]:
        print(f"  [{m.get('provider','?')}] {m['id']} | score:{m.get('quality_score',50)}")
    
    print(f"\n=== PRUEBA 9: call_llm multi-proveedor ===")
    result = call_llm(
        task_type="generation",
        system_prompt="Responde solo con JSON válido.",
        user_prompt='{"test": true}'
    )
    print(f"success: {result['success']}")
    print(f"model: {result['model_used']}")
    print(f"provider: {result.get('provider_used','?')}")
    print(f"attempts: {result['attempts']}")
    print("MULTI-PROVIDER OK" if result["success"]
          else f"FALLÓ: {result.get('error')}")
    
    print(f"\n=== PRUEBA 10: health check ===")
    report = provider_manager.health_check()
    print(f"Timestamp: {report['timestamp']}")
    print(f"Total modelos disponibles: {report['total_models']}")
    print(f"Proveedores:")
    for name, info in report['providers'].items():
        status = "OK" if info['available'] else "NO DISPONIBLE"
        if info['available']:
            print(f"  [{status}] {name}: {info['models_count']} modelos | top: {info['top_model']}")
        else:
            print(f"  [{status}] {name}")
    print(f"Mejor modelo planning: {report['best_model_planning']}")
    print(f"Mejor modelo generation: {report['best_model_generation']}")
    print(f"Mejor modelo correction: {report['best_model_correction']}")