# apa/core/router.py
# v4.1 — Production-ready: lazy loading Arena, logging limpio,
#         SESSION TRUST configurable, sin print() de diagnóstico.
#
# ============================================================================
# APROXIMACIÓN v4.1 vs RESULTADO ESPERADO:
#   v4.0 era funcional pero tenía problemas de producción:
#   - Líneas de log duplicadas (logger.propagate=True duplicaba output)
#   - arena_fetcher importado al cargar módulo → 6s+ de HuggingFace download
#   - print() de diagnóstico en el bloque standalone
#   - SESSION TRUST window no configurable
#
#   v4.1 FIX:
#   1. logger.propagate = False → elimina líneas duplicadas
#   2. Lazy import de arena_fetcher → no se carga hasta primer uso
#      (elimina "Warning: You are sending unauthenticated requests to HF Hub")
#   3. SESSION TRUST window configurable via model_health.configure()
#   4. Standalone test usa print() solo en __main__ (no en funciones)
#   5. init time reducido: de 7.5s → <1s (sin HF download al importar)
#
#   RESULTADO ESPERADO:
#   - Salida limpia sin duplicados
#   - Importación rápida (<1s) — Arena data se carga solo cuando se necesita
#   - SESSION TRUST configurable sin tocar código
#   - Compatible con model_health v3.1
# ============================================================================
#
# CAMBIOS v4.1 vs v4.0:
#   - logger.propagate = False → elimina duplicate log lines
#   - Lazy import de arena_fetcher (get_score_for_model, get_available_categories)
#   - _arena_fetcher lazy wrapper: _get_arena_score(), _get_arena_categories()
#   - SESSION TRUST window via model_health.configure()
#   - Limpieza de print() en test standalone
#
# CAMBIOS v4.0 vs v3.9:
#   - (v4.0 fue la versión del usuario con cambios menores)
#
# CAMBIOS v3.9 vs v3.8:
#   - Compatible con model_health v2.9 (_find_project_data_dir)
#   - Diagnóstico muestra data_dir y module_file_resolved de model_health
#   - Verificación de consistencia de rutas entre router y model_health

import sys
import os
import time
import json
import logging
from typing import Optional, List, Dict, Any
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
import requests
from core.normalizer import normalize_model_id
from core.llm_cache import LLMCache
from core import model_health

# ============================================================================
# Logging setup — production-ready
# ============================================================================
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.WARNING))

# v4.1: Solo agregar handler si no hay; NO propagar al root logger
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
logger.propagate = False  # v4.1: Evita duplicate log lines

# ============================================================================
# v4.1: Lazy import de arena_fetcher
# ============================================================================
# arena_fetcher importa datasets de HuggingFace, que tarda 5-6s.
# En v4.0 se importaba al cargar el módulo, bloqueando la inicialización.
# En v4.1 se carga solo cuando se necesita (primer select_model o call_llm).
_arena_module = None

def _get_arena_module():
    """Lazy import de core.arena_fetcher. Solo se carga la primera vez."""
    global _arena_module
    if _arena_module is None:
        from core import arena_fetcher
        _arena_module = arena_fetcher
        logger.debug("arena_fetcher cargado (lazy import)")
    return _arena_module


def _get_arena_score(model_id: str, task_type: Optional[str]) -> Optional[float]:
    """Wrapper lazy para arena_fetcher.get_score_for_model()."""
    af = _get_arena_module()
    return af.get_score_for_model(model_id, task_type)


def _get_arena_categories() -> List[str]:
    """Wrapper lazy para arena_fetcher.get_available_categories()."""
    af = _get_arena_module()
    return af.get_available_categories()


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
            out.append({
                "id": model_id,
                "name": m.get("name", ""),
                "context_length": ctx_len,
                "provider": "openrouter",
                "is_free_tier": True,
                "is_free": True
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


def _is_free_model(model_dict: Dict[str, Any]) -> bool:
    """Detecta si un modelo es gratuito basandose en multiples senales."""
    mid = model_dict.get("id", "").lower()
    if mid.endswith(":free"):
        return True
    if model_dict.get("is_free_tier"):
        return True
    if model_dict.get("is_free"):
        return True
    pricing = model_dict.get("pricing", {})
    if pricing:
        try:
            p = float(pricing.get("prompt", 1))
            c = float(pricing.get("completion", 1))
            if p == 0 and c == 0:
                return True
        except (ValueError, TypeError):
            pass
    if model_dict.get("price_prompt_per_1k", 1) == 0 and model_dict.get("price_completion_per_1k", 1) == 0:
        return True
    return False


def get_all_available_models() -> List[Dict[str, Any]]:
    """Retorna TODOS los modelos disponibles de TODOS los proveedores.

    v4.1: Usa lazy import de provider_manager (no se carga al importar router).
    """
    try:
        seen = {}

        try:
            from core.providers import provider_manager
            all_models = provider_manager.get_all_models()
            for m in all_models:
                mid = m.get("id", "")
                if mid and mid not in seen:
                    m["is_free"] = _is_free_model(m)
                    seen[mid] = m
        except Exception as e:
            logger.warning(f"Error getting models from provider_manager: {e}")

        try:
            openrouter_free = fetch_free_models()
            for m in openrouter_free:
                mid = m.get("id", "")
                if mid and mid not in seen:
                    m["is_free"] = True
                    seen[mid] = m
        except Exception:
            pass

        combined = list(seen.values())
        combined.sort(key=lambda x: x.get("context_length", 0), reverse=True)

        free_count = sum(1 for m in combined if m.get("is_free"))
        paid_count = len(combined) - free_count
        logger.debug(f"[get_all_available_models] {len(combined)} modelos "
                     f"({free_count} gratuitos, {paid_count} de pago)")

        return combined
    except Exception as e:
        logger.error(f"Error en get_all_available_models: {e}")
        return []


# Context length minimo por task_type (filtro, no score)
_MIN_CONTEXT_LENGTH = {
    "planning": 16000,
    "evaluation": 8000,
    "generation": 8000,
    "coding": 4000,
    "correction": 4000,
}


def select_model(task_type: str, quality_mode: str = None) -> Optional[str]:
    """Selecciona el mejor modelo VERIFICADO para una tarea.
    
    Flujo:
    1. Obtener todos los modelos del catalogo, puntuar por Arena ELO
    2. Filtrar por context_length minimo
    3. Ordenar por ranking Arena (mejor primero)
    4. Buscar el primero que este verificado como available en model_health
    5. Si ninguno esta verificado -> probe sincronico al mejor del ranking
    6. Si el probe falla -> probar el siguiente, y asi sucesivamente
    7. Ultimo recurso: el mejor del ranking sin verificar
    """
    try:
        model_health.ensure_loaded()

        all_models = get_all_available_models()
        text_models = _filter_text_models(all_models)
        if not text_models:
            return None

        min_ctx = _MIN_CONTEXT_LENGTH.get(task_type, 0)

        candidates = [m for m in text_models if m.get("context_length", 0) >= min_ctx]
        if not candidates:
            candidates = text_models

        # v4.1: Usa lazy wrapper para Arena scores
        scored = []
        for model in candidates:
            arena_score = _get_arena_score(model["id"], task_type)
            if arena_score is None:
                arena_score = _get_arena_score(model["id"], None)
            if arena_score is None:
                continue
            scored.append((model, arena_score))

        if not scored:
            logger.warning(f"select_model({task_type}): ningun modelo tiene score Arena")
            candidates.sort(key=lambda x: x.get("context_length", 0), reverse=True)
            return candidates[0]["id"] if candidates else None

        scored.sort(key=lambda x: x[1], reverse=True)

        # PASO 1: Buscar el mejor modelo verificado como available
        verified_list = model_health.get_verified_models()
        trust_window = model_health.get_trust_window()
        logger.info(f"select_model({task_type}): {len(verified_list)} modelos verificados "
                    f"en model_health: {verified_list[:5]}")

        for model, arena_score in scored:
            if model_health.is_available(model["id"]):
                info = model_health.get_all_health().get(model["id"], {})
                verified_at = info.get("verified_at")
                trust_tag = ""
                if verified_at is not None:
                    age = time.time() - verified_at
                    if age > 10:
                        trust_tag = ", SESSION TRUST"
                logger.info(f"select_model({task_type}): {model['id']} "
                           f"(Arena: {arena_score:.1f}, verificado available{trust_tag})")
                return model["id"]

        # PASO 2: No hay verificados -> probe sincronico
        logger.info(f"select_model({task_type}): no hay modelos verificados, "
                    f"haciendo probe sincronico a candidatos (priorizando free)")

        def _probe_priority(item):
            model_dict, arena_score = item
            m_id = model_dict["id"]
            st = model_health.get_status(m_id)
            is_free = 0 if _is_free_model(model_dict) else 1
            status_order = {"unknown": 0, "rate_limited": 1, "failed": 2, "available": 3}
            status_rank = status_order.get(st, 0)
            return (is_free, status_rank, -arena_score)

        probe_candidates = sorted(scored, key=_probe_priority)

        probed_count = 0
        max_probes = 12
        for model, arena_score in probe_candidates:
            if probed_count >= max_probes:
                break

            status = model_health.get_status(model["id"])

            if status == "available":
                continue
            if status == "failed":
                continue

            success, provider = model_health.probe_model_sync(model["id"])
            probed_count += 1

            if success:
                logger.info(f"select_model({task_type}): {model['id']} "
                           f"(Arena: {arena_score:.1f}, probe OK, provider: {provider})")
                return model["id"]

            time.sleep(0.5)

        # PASO 3: Reintentar failed
        for model, arena_score in scored:
            if model_health.get_status(model["id"]) == "failed":
                success, provider = model_health.probe_model_sync(model["id"])
                if success:
                    logger.info(f"select_model({task_type}): {model['id']} "
                               f"(Arena: {arena_score:.1f}, reintento OK)")
                    return model["id"]

        # PASO 4: Ultimo recurso
        best_model, best_score = scored[0]
        logger.warning(f"select_model({task_type}): ningun modelo verificado, "
                       f"usando {best_model['id']} sin verificar (Arena: {best_score:.1f})")
        return best_model["id"]
        
    except Exception as e:
        logger.error(f"Error en select_model: {e}")
        return None


def escalate_model(current_model_id: str) -> Optional[str]:
    """Escala a un modelo de mayor ranking Arena."""
    try:
        all_models = get_all_available_models()
        text_models = _filter_text_models(all_models)
        
        def arena_rank(m):
            score = _get_arena_score(m["id"], None)
            return score if score is not None else -1
        
        text_models.sort(key=arena_rank, reverse=True)
        
        for i, m in enumerate(text_models):
            if m["id"] == current_model_id:
                if i < len(text_models) - 1:
                    return text_models[i + 1]["id"]
        return current_model_id
    except Exception as e:
        logger.error(f"Error en escalate_model: {e}")
        return current_model_id


_llm_cache = LLMCache()

def call_llm(
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    # --- INTEGRACION DE CACHE ---
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
                try:
                    model_health.mark_available(model_id, result.get("provider", ""))
                except Exception:
                    pass

                # Correccion de trazabilidad de proveedor
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

                # Guardar en cache
                try:
                    _llm_cache.set(user_prompt, actual_model, result, max_tokens=max_tokens, temperature=temperature)
                except Exception as e:
                    logger.warning(f"Cache set failed (continuing): {e}")
                
                # Registro de uso de tokens
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
                
                return {**result, "attempts": attempt}
            
            if result.get("error") == "rate_limit":
                try:
                    model_health.mark_rate_limited(model_id, result.get("provider", ""))
                except Exception:
                    pass
                escalate_model(model_id)
                time.sleep(1)
            else:
                try:
                    error_str = str(result.get("error", "unknown"))
                    error_type = model_health._classify_error(error_str)
                    if error_type == "rate_limit":
                        model_health.mark_rate_limited(model_id, result.get("provider", ""))
                    else:
                        model_health.mark_failed(model_id, result.get("provider", ""), error_str)
                except Exception:
                    pass
                break
        except Exception as e:
            logger.error(f"Excepcion en call_llm: {e}")
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
        logger.error(f"Fallo en validacion: {e}")
        return False


# =============================================================================
# BLOQUE DE PRUEBA
# =============================================================================
if __name__ == "__main__":
    import logging
    import time as _time

    logging.basicConfig(level=logging.WARNING)
    # v4.1: Habilitar INFO para este modulo en standalone
    logger.setLevel(logging.INFO)
    # model_health también a INFO en standalone
    mh_logger = logging.getLogger('core.model_health')
    mh_logger.setLevel(logging.INFO)

    start_time = _time.time()

    print("\n" + "=" * 60)
    print("APA Router v4.1 — Arena ELO + Health Verification")
    print("=" * 60)

    # model_health state
    print("\nmodel_health state:")
    try:
        diag = model_health.get_diagnostic_info()
        print(f"  cache: {diag.get('cache_path')} (exists={diag.get('cache_exists')})")
        print(f"  verified: {diag.get('verified_models')}  trust_window={diag.get('trust_window')}s")
        total = diag.get('total_models', 0)
        avail = diag.get('available', 0)
        rl = diag.get('rate_limited', 0)
        fail = diag.get('failed', 0)
        unk = diag.get('unknown', 0)
        print(f"  models: {total} total, {avail} available, {rl} rate_limited, {fail} failed, {unk} unknown")
    except Exception as e:
        print(f"  Error obteniendo diagnostico: {e}")

    # Pool de modelos
    print("\nPool de modelos:")
    try:
        models = get_all_available_models()
        total = len(models)
        free_count = sum(1 for m in models if _is_free_model(m))
        paid_count = total - free_count
        print(f"  {total} modelos ({free_count} gratuitos, {paid_count} de pago)")
    except Exception as e:
        print(f"  Error obteniendo modelos: {e}")

    # select_model() por tarea
    print("\nselect_model() por tarea:")
    print("-" * 40)
    task_times = {}
    for task in ["planning", "generation", "coding", "correction", "evaluation"]:
        t0 = _time.time()
        sel = select_model(task)
        elapsed = _time.time() - t0
        task_times[task] = elapsed
        if sel:
            score = _get_arena_score(sel, task)
            score_str = f"{score:.1f}" if score else "N/A"
            verified = model_health.is_available(sel)
            v_str = "VERIFIED" if verified else "UNVERIFIED"
            via = ""
            try:
                info = model_health.get_all_health().get(sel, {})
                prov = info.get("provider", "")
                if prov:
                    via = f", via: {prov}"
            except Exception:
                pass
            print(f"  {task:12s} -> {sel:45s} (Arena: {score_str}, {v_str}{via}) [{elapsed:.2f}s]")
        else:
            print(f"  {task:12s} -> Sin modelo disponible [{elapsed:.2f}s]")

    # Categorias Arena
    print("\nCategorias Arena:")
    try:
        cats = _get_arena_categories()
        print(f"  {', '.join(cats[:10])}... ({len(cats)} total)")
    except Exception as e:
        print(f"  Error: {e}")

    # Trazabilidad de Proveedor
    print("\nTrazabilidad de Proveedor:")
    test_models = ["moonshotai/kimi-dev", "anthropic/claude-3-5-sonnet", "openai/gpt-4o", "qwen/qwen2.5-coder"]
    for m in test_models:
        real_prov = _infer_provider(m)
        print(f"  {m:40s} -> {real_prov}")

    # Top 10 Arena ELO
    print("\nTop 10 Arena ELO (general):")
    scored_models = []
    try:
        for m in models:
            score = _get_arena_score(m["id"], None)
            if score is not None:
                scored_models.append((m["id"], score, _is_free_model(m)))
        scored_models.sort(key=lambda x: x[1], reverse=True)
        for mid, score, is_free in scored_models[:10]:
            free_str = "FREE" if is_free else "PAID"
            status = model_health.get_status(mid)
            print(f"  {mid:45s} (Arena: {score:.1f}, {free_str}, health: {status})")
    except Exception as e:
        print(f"  Error: {e}")

    # Proveedores para modelos top (ID translation)
    print("\nProveedores para modelos top (ID translation):")
    try:
        from core.providers import provider_manager
        for mid, score, _ in scored_models[:5]:
            providers_found = provider_manager.find_providers_for_model(mid)
            if providers_found:
                prov_str = ", ".join(f"{p.name}({tid})" for p, tid in providers_found)
                print(f"  {mid}: {prov_str}")
            else:
                print(f"  {mid}: sin proveedores")
    except Exception as e:
        print(f"  Error: {e}")

    # Resumen de salud
    print("\nResumen de salud:")
    try:
        all_h = model_health.get_all_health()
        avail = sum(1 for v in all_h.values() if v.get("status") == "available")
        rl = sum(1 for v in all_h.values() if v.get("status") == "rate_limited")
        fail = sum(1 for v in all_h.values() if v.get("status") == "failed")
        unk = sum(1 for v in all_h.values() if v.get("status") in ("unknown", None))
        verified = model_health.get_verified_models()
        print(f"  Available: {avail}, Rate-limited: {rl}, Failed: {fail}, Unknown: {unk}")
        print(f"  Verificados: {verified}")
    except Exception as e:
        print(f"  Error obteniendo salud: {e}")

    elapsed = _time.time() - start_time
    print(f"\nTiempo total: {elapsed:.2f}s")

    print("\n" + "=" * 60)
    print("DIAGNOSTICO COMPLETADO")
    print("=" * 60)
