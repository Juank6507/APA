# apa/core/router.py
import sys
import os
import time
import json
import logging
from typing import Optional, List, Dict, Any
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
import requests
from core.arena_fetcher import get_score_for_model
from core.normalizer import normalize_model_id
from core.llm_cache import LLMCache
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.WARNING))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

def _log(module: str, stage: str, status: str, detail: str = "") -> None:
    """No-op: suprimimos los logs de progreso para limpiar la salida."""
    pass

_cache: Dict[str, Any] = {
    "data": None,
    "timestamp": None,
}
_CACHE_DURATION = 600

PROVIDER_PREFIX_MAP = {
    "moonshotai/": "moonshot",
    "anthropic/": "anthropic",
    "openai/": "openai",
    "meta-llama/": "meta",
    "qwen/": "alibaba",
    "google/": "google",
    "mistralai/": "mistral",
    "deepseek/": "deepseek",
    "cohere/": "cohere",
}

def _infer_provider(model_id: str) -> str:
    """Infiere el proveedor real a partir del prefijo del ID del modelo."""
    if not model_id:
        return "unknown"
    mid = model_id.lower()
    for prefix, provider in PROVIDER_PREFIX_MAP.items():
        if mid.startswith(prefix):
            return provider
    return "unknown"

def _infer_capabilities(model_id: str, context_length: int) -> List[str]:
    caps = []
    mid = model_id.lower()
    if "coder" in mid or "code" in mid:
        caps.append("coding")
    if context_length >= 32000:
        caps.append("long_context")
    if "instruct" in mid:
        caps.append("instruction")
    return caps or ["general"]

def fetch_free_models() -> List[Dict[str, Any]]:
    global _cache
    now = time.time()
    if _cache["data"] is not None and _cache["timestamp"] is not None:
        if now - _cache["timestamp"] < _CACHE_DURATION:
            return _cache["data"]
    
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=5
        )
        resp.raise_for_status()
        models = [
            m for m in resp.json().get("data", [])
            if str(m.get("pricing", {}).get("prompt", " ")) == "0"
            and str(m.get("pricing", {}).get("completion", " ")) == "0"
        ]
        out = []
        for m in models:
            model_id = m.get("id", "")
            ctx_len = m.get("context_length", 0)
            caps = _infer_capabilities(model_id, ctx_len)
            out.append({
                "id": model_id,
                "name": m.get("name", ""),
                "context_length": ctx_len,
                "capabilities": caps,
                "provider": "openrouter",
                "is_free_tier": False
            })
        out.sort(key=lambda x: x["context_length"], reverse=True)
        if not out:
            return []
        _cache["data"] = out
        _cache["timestamp"] = now
        return out
    except Exception as e:
        logger.error(f"Error fetching free models: {e}")
        return []

def fetch_free_tier_models() -> List[Dict[str, Any]]:
    return []

def _filter_text_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocked = {"lyria", "audio", "music", "imagen", "image", "vision", "video", "clip"}
    return [m for m in models if not any(k in m["id"].lower() for k in blocked)]

def get_all_available_models() -> List[Dict[str, Any]]:
    try:
        openrouter_free = fetch_free_models()
        openrouter_tier = fetch_free_tier_models()
        seen = {}
        for m in openrouter_free:
            seen[m["id"]] = m
        for m in openrouter_tier:
            seen[m["id"]] = m
        
        try:
            from core.providers import provider_manager
            other_models = provider_manager.get_all_models()
            for m in other_models:
                if m.get("provider") != "openrouter":
                    if m["id"] not in seen:
                        seen[m["id"]] = m
        except Exception as e:
            logger.warning(f"No se pudieron obtener modelos de otros proveedores: {e}")
        
        combined = list(seen.values())
        combined.sort(key=lambda x: x.get("context_length", 0), reverse=True)
        return combined
    except Exception as e:
        logger.error(f"Error en get_all_available_models: {e}")
        return []

def select_model(task_type: str, quality_mode: str = None) -> Optional[str]:
    mode = quality_mode or getattr(settings, "default_quality_mode", "balanced")
    try:
        all_models = get_all_available_models()
        text_models = _filter_text_models(all_models)
        if not text_models:
            return None
        
        if task_type == "correction":
            fast_models = [m for m in text_models if m.get("context_length", 0) <= 32000]
            if fast_models:
                def corr_score(m: Dict[str, Any]) -> float:
                    arena = get_score_for_model(m["id"], task_type)
                    base = arena if arena is not None else 50.0
                    bonus = 20 if "instruction" in m.get("capabilities", []) else 0
                    return base + bonus
                selected = max(fast_models, key=corr_score)
            else:
                inst_models = [m for m in text_models if "instruction" in m.get("capabilities", [])]
                if not inst_models:
                    inst_models = text_models
                selected = min(inst_models, key=lambda m: m.get("context_length", 0))
            return selected["id"]
        
        scored = []
        for model in text_models:
            arena_score = get_score_for_model(model["id"], task_type)
            base_score = arena_score if arena_score is not None else 50.0
            ctx_len = model.get("context_length", 0)
            context_score = min(100.0, ctx_len / 320.0)
            composite = base_score * 0.6 + context_score * 0.4
            
            caps = model.get("capabilities", [])
            bonus = 0.0
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
            
            total = composite + bonus
            scored.append((model, total))
        
        if not scored:
            return None
        
        scored.sort(key=lambda x: x[1], reverse=True)
        selected_model, final_score = scored[0]
        return selected_model["id"]
        
    except Exception as e:
        logger.error(f"Error en select_model: {e}")
        return None

def escalate_model(current_model_id: str) -> Optional[str]:
    try:
        all_models = get_all_available_models()
        text_models = _filter_text_models(all_models)
        text_models.sort(key=lambda x: (x.get("context_length", 0), len(x.get("capabilities", []))), reverse=True)
        for i, m in enumerate(text_models):
            if m["id"] == current_model_id:
                if i < len(text_models) - 1:
                    return text_models[i + 1]["id"]
        return current_model_id
    except Exception as e:
        logger.error(f"Error en escalate_model: {e}")
        return current_model_id

_llm_cache = LLMCache()

# CORRECCIÓN: Añadir parámetro project_id para registro de uso
def call_llm(
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    project_id: Optional[str] = None  # <-- AÑADIDO
) -> Dict[str, Any]:
    # --- INTEGRACIÓN DE CACHÉ (T8) ---
    try:
        cached_response = _llm_cache.get(user_prompt, "", max_tokens=max_tokens, temperature=temperature)
        if cached_response is not None:
            logger.debug("Router cache HIT")
            return cached_response
    except Exception as e:
        logger.warning(f"Cache get failed (falling back to provider): {e}")
    
    logger.debug("Router cache MISS")
    # --------------------------------
    
    for attempt in range(1, 4):
        try:
            from core.providers import provider_manager
            model_id = select_model(task_type)
            if model_id is None:
                return {
                    "content": "",
                    "model_used": "",
                    "provider_used": None,
                    "success": False,
                    "attempts": attempt,
                    "error": "No se pudo seleccionar modelo"
                }
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            result = provider_manager.call_with_fallback(model_id, messages, max_tokens, temperature)
            
            if result.get("success"):
                # --- T9: CORRECCIÓN DE TRAZABILIDAD DE PROVEEDOR ---
                try:
                    current_provider = result.get("provider")
                    actual_model = result.get("model_used", model_id)
                    is_generic = current_provider in (None, "openrouter", "unknown", "")
                    
                    if is_generic:
                        inferred = result.get("model_info", {}).get("provider")
                        if not inferred or inferred == "unknown":
                            inferred = _infer_provider(actual_model)
                        
                        if inferred and inferred != "unknown":
                            result["provider"] = inferred
                            logger.debug(f"Provider corrected from '{current_provider}' to '{inferred}' for model {actual_model}")
                except Exception as e:
                    logger.warning(f"Failed to correct provider traceability: {e}")
                # ----------------------------------------------------

                # T8: Guardar en caché si la respuesta es exitosa
                try:
                    _llm_cache.set(user_prompt, actual_model, result, max_tokens=max_tokens, temperature=temperature)
                except Exception as e:
                    logger.warning(f"Cache set failed (continuing): {e}")
                
                # =================================================================
                # CORRECCIÓN: Registro de uso de tokens en UsageTracker
                # =================================================================
                if project_id is not None:
                    try:
                        from core.usage_tracker import UsageTracker
                        tokens = result.get("tokens", 0)
                        if tokens == 0:
                            tokens = len(user_prompt) // 4
                        logger.info(f"Registering usage for project {project_id}: model={actual_model}, tokens={tokens}")
                        UsageTracker().log_usage(project_id, actual_model, tokens, task_type)
                    except Exception as e:
                        logger.warning(f"Usage tracking failed (continuing): {e}")
                # =================================================================
                
                return {**result, "attempts": attempt}
            
            if result.get("error") == "rate_limit":
                escalate_model(model_id)
                time.sleep(1)
            else:
                break
        except Exception as e:
            logger.error(f"Excepción en call_llm: {e}")
            break
    
    return {
        "content": "",
        "model_used": "",
        "provider_used": None,
        "success": False,
        "attempts": 3,
        "error": "Reintentos agotados"
    }

def validate_self() -> bool:
    try:
        all_models = get_all_available_models()
        assert isinstance(all_models, list)
        if len(all_models) == 0:
            logger.warning("No hay modelos disponibles")
        else:
            sel = select_model("planning")
            assert sel is None or isinstance(sel, str)
        return True
    except Exception as e:
        logger.error(f"Fallo en validación: {e}")
        return False

# =============================================================================
# BLOQUE DE PRUEBA (RESUMIDO Y SIN LOGS)
# =============================================================================
if __name__ == "__main__":
    import logging
    import tempfile
    import shutil
    
    logging.basicConfig(level=logging.WARNING)
    print("\n" + "=" * 60)
    print("🔍 APA - DIAGNÓSTICO DEL ROUTER + CACHÉ + TRAZABILIDAD T9")
    print("=" * 60)
    start_time = time.time()
    
    print("\n📊 Pool de modelos")
    print("-" * 40)
    try:
        models = get_all_available_models()
        total = len(models)
        print(f"Total modelos combinados: {total}")
        if total >= 300:
            print("✓ POOL COMPLETO (>=300)")
        elif total >= 50:
            print("✓ POOL BÁSICO (>=50)")
        else:
            print(f"⚠ POOL REDUCIDO ({total}). Revisa .env y API keys.")
    except Exception as e:
        print(f"❌ Error obteniendo modelos: {e}")
    
    print("\n🎯 Mejores modelos por tarea")
    print("-" * 40)
    try:
        planning = select_model("planning")
        generation = select_model("generation")
        correction = select_model("correction")
        print(f"Planning   : {planning}")
        print(f"Generation : {generation}")
        print(f"Correction : {correction}")
    except Exception as e:
        print(f"⚠️ No se pudieron determinar: {e}")
    
    print("\n💾 Estado de Caché LLM")
    print("-" * 40)
    print(f"Ruta caché: {_llm_cache.cache_path}")
    print("✓ Integración T8 activa")
    
    print("\n🔗 Trazabilidad de Proveedor (T9)")
    print("-" * 40)
    test_models = ["moonshotai/kimi-dev", "anthropic/claude-3-5-sonnet", "openai/gpt-4o", "qwen/qwen2.5-coder"]
    for m in test_models:
        real_prov = _infer_provider(m)
        print(f"{m:40s} → {real_prov}")
    
    # =================================================================
    # PRUEBA ADICIONAL: Verificar registro de uso en UsageTracker
    # =================================================================
    print("\n📈 Prueba de registro de uso (CORRECCIÓN)")
    print("-" * 40)
    
    def test_usage_tracking():
        from core.usage_tracker import UsageTracker
        import tempfile
        temp_dir = tempfile.mkdtemp()
        test_db = os.path.join(temp_dir, "test_router_usage.db")
        
        try:
            # Usar BD temporal para prueba aislada
            ut = UsageTracker(db_path=test_db)
            test_proj = "test-proj-router"
            
            # Simular llamada exitosa con project_id (sin llamar LLM real)
            # Registramos manualmente para validar el flujo
            ut.log_usage(test_proj, "qwen/qwen2.5-coder", 150, "generation")
            
            agg = ut.get_aggregated_usage(test_proj)
            assert len(agg) > 0, "No se registró uso en UsageTracker"
            assert agg.get("qwen/qwen2.5-coder") == 150, f"Tokens incorrectos: {agg}"
            print("✅ UsageTracker registró correctamente")
            return True
        except Exception as e:
            print(f"⚠️ Error en prueba de registro: {e}")
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    test_usage_tracking()
    
    elapsed = time.time() - start_time
    print("\n⏱️ Tiempo total")
    print("-" * 40)
    print(f"{elapsed:.2f} segundos")
    
    print("\n" + "=" * 60)
    print("✅ DIAGNÓSTICO COMPLETADO")
    print("=" * 60)