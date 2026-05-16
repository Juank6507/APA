# apa/core/router.py
# v5.7 — CRITICAL FIX: free-first selection for unknown models (D-1b/D-2b).
#         select_model_entry() PASO 2 ahora usa free_first=True para
#         preferir modelos gratuitos (GitHub, Groq, OpenRouter) sobre
#         modelos de pago (Anthropic, OpenAI) cuando no hay verified models.
#         Esto resuelve el bug donde modelos de pago sin crédito con Arena
#         scores altos (90+) siempre ganan sobre modelos gratuitos funcionales.
#
#         También: call_llm() payment discovery mejorado — payment errors
#         NO consumen intentos reales, cascade de mark_provider_paid_models()
#         confirmado con logging explícito.
#
# CAMBIOS v5.7 vs v5.6:
#   - select_model_entry() PASO 2: get_ranked_entries(free_first=True)
#     Modelos is_free=True se intentan ANTES que is_free=False cuando
#     no hay modelos verificados. Esto es D-1b/D-2b: heurística práctica
#     para modelos unknown (si no sabemos si funciona, probar gratis primero).
#   - call_llm(): payment errors se loguean como "payment error (no cuenta)"
#     y el continue se ejecuta ANTES de incrementar real_attempt.
#     Se añade logging defensivo para verificar que el cascade funciona.
#   - _sync_health_after_call(): logging mejorado del cascade.
#
# v5.6 — _sync_health_after_call(): mark_provider_paid_models() cascade
#         when payment error detected (no more wasting attempts on paid models
#         from providers without credit).
#         OpenAI gpt-audio filtered via _is_chat_model() in providers v2.8.
#
# CAMBIOS v5.6 vs v5.5:
#   - _sync_health_after_call(): payment error → mark_provider_paid_models()
#     cascade. Cuando un modelo de pago falla por crédito, TODOS los modelos
#     de pago del mismo provider se marcan como payment_required inmediatamente.
#     Antes solo se marcaba el modelo individual, desperdiciando intentos en
#     otros modelos de pago del mismo provider que también fallarían.
#
# v5.5 — empty_response → mark_failed (permanente), provider rate_limit cooldown,
#         _classify_error fix: payment ANTES de rate_limit (v4.1 sync).
#
# CAMBIOS v5.5 vs v5.4:
#   - _sync_health_after_call(): empty_response → mark_failed (permanente).
#     Modelos que retornan HTTP 200 sin contenido están rotos y no
#     funcionarán en reintentos. Antes caían a 'temporarily_unavailable'.
#   - _sync_health_after_call(): usa model_health._classify_error() de v4.1
#     que ahora clasifica 429+insufficient_quota como 'payment' (no rate_limit).
#   - _sync_health_after_call(): después de N rate_limits consecutivos de
#     un mismo provider (en modelos free), llama mark_provider_rate_limited()
#     para cooldown de 120s. Evita desperdiciar intentos en provider saturado.
#   - select_model_entry(): añade lógica de provider diversity — si los
#     últimos 3 intentos fueron del mismo provider y fallaron con rate_limit,
#     saltar al siguiente provider diferente.
#
# v5.4 — Fixes E2E real: populate_pool espera Arena data (F1),
#         retry rota modelos (F3), update_arena_scores() (F4),
#         provider null-coalescing (F2b).
#
# v5.3 — Métricas completas en call_llm():
#         latencia, tokens in/out, coste estimado, Arena score,
#         provider, success, error_type registrados en UsageTracker v2.0.
#         Error logging en llamadas fallidas.
#
# CAMBIOS v5.3 vs v5.2:
#   - call_llm() registra métricas completas en UsageTracker:
#     · latencia: time.time() antes/después de cada llamada
#     · tokens_input/output: extraídos de result o estimados
#     · cost_usd: estimado via price_estimator o provider.get_model_price()
#     · arena_score: obtenido del modelo seleccionado
#     · provider: provider real que respondió
#     · success: resultado de la llamada
#     · error_type: clasificación del error (rate_limit, timeout, etc.)
#   - Llamadas fallidas TAMBIÉN se registran en UsageTracker
#   - Helper _estimate_tokens() para cuando el provider no retorna usage
#   - Helper _estimate_cost_usd() para estimar coste
#   - Helper _classify_error_type() para clasificar errores
#
# v5.2 — Sprint 1: select_model_entry() con Pool (P-1),
#         sin free_first bias (D-1/D-2), integración con pool.py.
#         select_model() DELEGA a Pool ranking (no más fallback alfabético).
#         call_llm() usa select_model_entry() con provider directo.
#         FIX: Recursión circular select_model_entry ↔ select_model.
#
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
from core.pool import PoolEntry, HealthStatus, pool as _global_pool

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


# ============================================================================
# v5.3: Helpers para métricas de uso
# ============================================================================

def _estimate_tokens(text: str) -> int:
    """Estima el número de tokens de un texto (aprox 4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _classify_error_type(error_str: str) -> str:
    """P8c: Clasifica el tipo de error usando model_health._classify_error().

    ANTES: Tenía su propia lógica con nombres distintos (model_not_found, server).
    AHORA: Delega a model_health._classify_error() para garantizar consistencia.
    Los nombres de categoría ahora son los mismos en todo APA:
        rate_limit | not_found | auth | payment | server_error |
        timeout | connection | temporarily_unavailable | unknown

    Returns: una de las categorías anteriores, o "" si error_str está vacío.
    """
    if not error_str:
        return ""
    return model_health._classify_error(error_str)


def _estimate_cost_usd(
    tokens_input: int,
    tokens_output: int,
    model_id: str,
    provider_name: str = "",
) -> float:
    """Estima el coste en USD de una llamada LLM.

    Intenta obtener precios del provider_manager; si no puede,
    usa una estimación conservadora por defecto.
    """
    try:
        from core.providers import provider_manager
        price = provider_manager.get_model_price(model_id, provider_name)
        prompt_price = price.get("prompt", 0.0)
        completion_price = price.get("completion", 0.0)
        cost = (tokens_input / 1000.0) * prompt_price + (tokens_output / 1000.0) * completion_price
        return round(cost, 6)
    except Exception:
        pass

    # Fallback: estimación genérica ($0.01/1K input, $0.03/1K output)
    try:
        from core.price_estimator import estimate_price
        per_token = estimate_price(model_id)
        return round((tokens_input + tokens_output) * per_token, 6)
    except Exception:
        return 0.0


# ============================================================================
# v5.0: Pool population — llena el Pool desde providers
# ============================================================================
_pool_populated = False


def populate_pool(force: bool = False) -> int:
    """Puebla el Pool desde los providers con composite key (P-1).

    D-8/D-10: Non-blocking — si ya está poblado, no hace nada
    a menos que force=True.

    P-1: Cada (provider, model_id) es una entrada independiente.
    P-2: Provider Confidence se obtiene del provider.
    P-3: Arena scores se obtienen de arena_fetcher.

    v5.4 (F1): Espera hasta 15s a que Arena data esté disponible
    antes de iterar los modelos, para que los scores se carguen
    correctamente en el pool.

    Retorna: número de entries en el pool.
    """
    global _pool_populated

    if not force and _pool_populated and _global_pool.size() > 0:
        return _global_pool.size()

    try:
        from core.providers import provider_manager

        # v5.4 (F1): Esperar a que Arena data esté disponible (hasta 15s)
        # Cuando el cache expira, arena_fetcher lanza un refresh en background
        # que tarda 5-15s. Sin esta espera, todos los scores llegan como None.
        af = _get_arena_module()
        for wait_i in range(15):
            with af._refresh_lock:
                has_data = bool(af._arena_data) and len(af._arena_data) > 0
            if has_data:
                if wait_i > 0:
                    logger.info(f"populate_pool(): Arena data disponible tras {wait_i}s de espera")
                break
            if wait_i == 0:
                logger.info("populate_pool(): Esperando Arena data...")
            time.sleep(1)
        else:
            logger.warning("populate_pool(): Arena data NO disponible tras 15s, "
                          "continuando sin Arena scores")

        # P-1: Obtener modelos con provider (sin deduplicar por model_id)
        all_models = provider_manager.get_all_models_with_provider()

        if not all_models:
            logger.warning("populate_pool(): no se obtuvieron modelos de providers")
            return _global_pool.size()

        # Limpiar pool si force
        if force:
            _global_pool.clear()

        count = 0
        for m in all_models:
            # F6: Usar prefixed_id como identificador principal del modelo
            # prefixed_id = "OPR:anthropic/claude-opus-4-6" o "ANT:claude-opus-4-6"
            prefixed_id = m.get("prefixed_id", "")
            base_id = m.get("base_id", m.get("id", ""))
            provider_name = m.get("provider", "")
            if not prefixed_id or not provider_name:
                # Fallback: si no hay prefixed_id, usar el id original
                if not base_id:
                    continue
                prefixed_id = provider_manager.make_prefixed_id(provider_name, base_id)

            # Verificar si ya existe esta composite key
            existing = _global_pool.get_entry(provider_name, prefixed_id)
            if existing and not force:
                continue  # Ya existe, no sobreescribir

            # Crear PoolEntry con composite key (P-1)
            # F6: model_id ahora es el prefixed_id (PROVEEDOR:modelo)
            entry = PoolEntry(
                provider=provider_name,
                model_id=prefixed_id,
                context_length=m.get("context_length", 8192) or 8192,
                is_free=bool(m.get("is_free", False) or m.get("is_free_tier", False)),
                provider_confidence=m.get("provider_confidence", 50.0),
                capabilities=m.get("capabilities", []),
                pricing=m.get("pricing", {}),
            )

            # P-3: Arena score (Capa 2) — buscar usando base_id
            # F6: El Arena score se busca con el nombre original (sin prefijo)
            # porque Arena no conoce nuestros prefijos de proveedor
            arena_score = _get_arena_score(base_id, None)
            if arena_score is not None:
                entry.arena_score = arena_score
                entry.apa_score = arena_score  # APA placeholder (DEFERRED)

            # v1.1: Obtener TODOS los scores por categoría del modelo
            # Esto permite que get_ranked_entries() use task_score() con
            # puntuaciones diferentes según el tipo de tarea.
            try:
                af = _get_arena_module()
                all_scores = af.get_model_all_scores(base_id)
                if all_scores:
                    entry.arena_scores = all_scores
            except Exception:
                pass  # No crítico — fallback a composite_score

            # Sync health from model_health — usar base_id para lookup
            entry.health_status = model_health.get_status(base_id)

            _global_pool.add_entry(entry)
            count += 1

        # P-2: Set provider confidence para cada provider
        for prov_name, prov_obj in provider_manager.providers.items():
            _global_pool.set_provider_confidence(prov_name, prov_obj.confidence_score)

        _pool_populated = True

        # Log resumen
        summary = _global_pool.health_summary()
        arena_count = sum(1 for e in _global_pool.get_all_entries() if e.arena_score is not None)
        logger.info(f"populate_pool(): {count} entries ({arena_count} con Arena score), "
                    f"health: {summary}")

        return count

    except Exception as e:
        logger.error(f"populate_pool(): error: {e}")
        return _global_pool.size()


def _sync_health_to_pool() -> int:
    """Sincroniza health status de model_health al pool.

    Se llama después de probes o verificaciones para que el pool
    refleje el estado más reciente de model_health.

    Retorna: número de entries actualizadas.
    """
    updated = 0
    try:
        from core.providers import provider_manager as _pm
        for entry in _global_pool.get_all_entries():
            # F6: model_health usa base_id, pool usa prefixed_id
            _, base_id = _pm.parse_prefixed_id(entry.model_id)
            if base_id is None or base_id == entry.model_id:
                base_id = entry.model_id
            mh_status = model_health.get_status(base_id)
            if mh_status != entry.health_status:
                if mh_status == "available":
                    _global_pool.mark_available(entry.provider, entry.model_id)
                    updated += 1
                elif mh_status == "payment_required" and entry.health_status != "available":
                    _global_pool.mark_payment_required(entry.provider, entry.model_id)
                    updated += 1
                elif mh_status == "rate_limited" and entry.health_status not in ("available",):
                    entry.health_status = mh_status
                    entry.verified_at = time.time()
                    updated += 1
                elif mh_status == "failed" and entry.health_status not in ("available",):
                    entry.health_status = mh_status
                    entry.verified_at = time.time()
                    updated += 1
        if updated > 0:
            logger.debug(f"_sync_health_to_pool(): {updated} entries actualizadas")
    except Exception as e:
        logger.debug(f"_sync_health_to_pool(): error: {e}")
    return updated


def update_arena_scores() -> int:
    """v5.4 (F4): Re-escanea pool entries y llena Arena scores faltantes.

    Safety net: si populate_pool() corrió antes de que el background
    refresh de Arena completara, esta función rellena los scores.

    Retorna: número de entries actualizadas.
    """
    updated = 0
    try:
        for entry in _global_pool.get_all_entries():
            if entry.arena_score is None:
                score = _get_arena_score(entry.model_id, None)
                if score is not None:
                    entry.arena_score = score
                    entry.apa_score = score  # APA placeholder
                    updated += 1
        if updated > 0:
            logger.info(f"update_arena_scores(): {updated} entries actualizadas con Arena score")
    except Exception as e:
        logger.debug(f"update_arena_scores(): error: {e}")
    return updated


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


# v5.2: Guard contra recursión circular select_model_entry ↔ select_model
_in_select_model_entry = False


def select_model_entry(task_type: str, quality_mode: str = None) -> Optional[PoolEntry]:
    """Selecciona el mejor modelo para una tarea, retornando PoolEntry.

    D-1/D-2: Sin free_first bias — el ranking puro decide.
    P-1: Retorna PoolEntry con composite key (provider, model_id).
    P-3: 3-Layer Ranking — APA > Arena ELO > Provider Confidence.
    D-8/D-10: Non-blocking — pobla pool lazy, usa lo que haya.

    Flujo:
    1. Poblar pool lazy si está vacío (populate_pool)
    2. Buscar entries available (verified) en el pool
    3. Si no hay verified, buscar unknown/rate_limited
    4. Fallback a método clásico (probing activo) — SIN recursión

    v5.2 FIX: PASO 3 usa guard _in_select_model_entry para evitar
    que select_model() delegue de vuelta a select_model_entry()
    cuando ya estamos dentro de select_model_entry().

    Retorna PoolEntry o None si no hay modelo disponible.
    """
    global _in_select_model_entry

    try:
        model_health.ensure_loaded()

        # D-8/D-10: Poblar pool lazy (non-blocking)
        if _global_pool.size() == 0:
            populate_pool()

        # PASO 1: Buscar entries available (verified) en el pool
        ranked = _global_pool.get_ranked_entries(
            task_type=task_type,
            only_available=True,
        )

        if ranked:
            best = ranked[0]
            logger.info(f"select_model_entry({task_type}): {best.model_id} "
                       f"via {best.provider} (score: {best.composite_score:.1f}, VERIFIED)")
            return best

        # PASO 2: Sin verified -> buscar unknown/rate_limited
        # v5.7: free_first=True (D-1b/D-2b) — preferir modelos gratuitos
        # cuando no hay verified models. Los modelos unknown de pago tienen
        # scores altos pero fallarán sin crédito; los gratuitos probablemente
        # funcionen. Dentro de cada tier (free/paid), se ordena por score.
        #
        # Esto resuelve el bug crítico: ANT:claude-opus-4-6 (score 90.1, unknown)
        # siempre ganaba sobre GHU:gpt-4o (score 87.0, unknown) porque el
        # ranking puro no distingue free de paid. Con free_first, el modelo
        # gratuito se intenta primero.
        #
        # F10: También excluir temporarily_unavailable (cooldown 60s)
        ranked = _global_pool.get_ranked_entries(
            task_type=task_type,
            exclude_statuses=["payment_required", "failed", "temporarily_unavailable"],
            free_first=True,  # v5.7: D-1b/D-2b — free antes que paid
        )

        if ranked:
            best = ranked[0]
            tier = "FREE" if best.is_free else "PAID"
            logger.info(f"select_model_entry({task_type}): {best.model_id} "
                       f"via {best.provider} (score: {best.composite_score:.1f}, "
                       f"{best.health_status}, {tier})")
            return best

        # PASO 3: Fallback a método clásico (probing activo)
        # v5.2: Guard contra recursión circular con select_model()
        if _in_select_model_entry:
            logger.warning(f"select_model_entry({task_type}): recursión detectada,"
                          f" no se llama a select_model() fallback")
            return None

        _in_select_model_entry = True
        try:
            model_id = select_model(task_type, quality_mode)
        finally:
            _in_select_model_entry = False

        if model_id is None:
            return None

        # Crear PoolEntry y añadir al pool si no existe
        provider = _infer_provider(model_id)
        existing = _global_pool.get_entry(provider, model_id)
        if existing:
            # Actualizar health si model_health lo marca como available
            if model_health.is_available(model_id):
                _global_pool.mark_available(provider, model_id)
                existing = _global_pool.get_entry(provider, model_id)
            return existing

        entry = PoolEntry(
            provider=provider,
            model_id=model_id,
        )
        # Intentar obtener scores
        arena_score = _get_arena_score(model_id, task_type)
        if arena_score is not None:
            entry.arena_score = arena_score
            entry.apa_score = arena_score  # placeholder

        # Sync health
        entry.health_status = model_health.get_status(model_id)
        _global_pool.add_entry(entry)

        logger.info(f"select_model_entry({task_type}): {model_id} "
                   f"via {provider} (fallback, {entry.health_status})")
        return entry

    except Exception as e:
        logger.error(f"Error en select_model_entry: {e}")
        return None


def select_model(task_type: str, quality_mode: str = None) -> Optional[str]:
    """Selecciona el mejor modelo para una tarea (retorna str, backward compat).
    
    v5.1: DELEGA a select_model_entry() cuando el Pool tiene entries.
    Esto garantiza que select_model() SIEMPRE usa el ranking del Pool
    (3-layer ranking: APA > Arena > Provider Confidence), nunca cae a
    ordenamiento alfabético o por context_length.
    
    Flujo:
    1. Si Pool tiene entries → usar select_model_entry() → return model_id
    2. Si Pool vacío → método clásico (Arena ELO + probing)
    """
    try:
        # v5.2: Solo delegar al Pool si NO venimos de select_model_entry()
        # (evita recursión circular cuando PASO 3 llama a select_model())
        if not _in_select_model_entry and _global_pool.size() > 0:
            entry = select_model_entry(task_type, quality_mode)
            if entry is not None:
                return entry.model_id
            # entry es None → Pool sin candidates → fallback a método clásico

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
            logger.warning(f"select_model({task_type}): ningun modelo tiene score Arena, "
                           f"Pool vacío, usando composite_score del Pool clásico")
            # v5.1: Ya no hay fallback alfabético — si no hay scores,
            # poblar Pool y reintentar
            populate_pool()
            if _global_pool.size() > 0:
                entry = select_model_entry(task_type, quality_mode)
                if entry is not None:
                    return entry.model_id
            # Último recurso: mayor context_length
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
                    f"haciendo probe sincronico a candidatos")

        # D-1/D-2: Eliminado free_first bias — ranking puro
        def _probe_priority(item):
            model_dict, arena_score = item
            m_id = model_dict["id"]
            st = model_health.get_status(m_id)
            # D-5: payment_required models get lowest priority
            status_order = {"available": 0, "unknown": 1, "rate_limited": 2, "failed": 3, "payment_required": 4}
            status_rank = status_order.get(st, 1)
            return (status_rank, -arena_score)

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

def _sync_health_after_call(model_id: str, provider: str, success: bool,
                            error: str = "") -> None:
    """Sincroniza el resultado de una llamada LLM al Pool y model_health.

    D-3/D-4/D-5: Response-Code-Driven Scheduling.

    v5.5: empty_response → mark_failed (permanente, no temporarily_unavailable).
          Modelos que retornan HTTP 200 sin contenido están rotos.

    F6: model_id puede ser un prefixed_id (ej: "OPR:anthropic/claude-opus-4-6").
    - Para el Pool: se usa el prefixed_id (es la clave composite).
    - Para model_health: se extrae el base_id (model_health no conoce prefijos).
    """
    try:
        # F6: Extraer base_id para model_health
        try:
            from core.providers import provider_manager
            _, base_id = provider_manager.parse_prefixed_id(model_id)
            if base_id is None or base_id == model_id:
                base_id = model_id  # Sin prefijo, usar tal cual
        except Exception:
            base_id = model_id  # Fallback

        if success:
            model_health.mark_available(base_id, provider)
            _global_pool.mark_available(provider, model_id)
        else:
            error_type = model_health._classify_error(error)
            if error_type == "rate_limit":
                model_health.mark_rate_limited(base_id, provider)
                _global_pool.mark_rate_limited(provider, model_id)
            elif error_type == "payment":
                model_health.mark_payment_required(base_id, provider)
                _global_pool.mark_payment_required(provider, model_id)
                # v5.7: Cuando un modelo de pago falla por crédito, TODOS los
                # modelos de pago del mismo provider también fallarán.
                # Marcarlos inmediatamente para no desperdiciar intentos.
                marked = _global_pool.mark_provider_paid_models(provider)
                # v5.7: Logging defensivo — siempre loguear el cascade
                logger.info(f"_sync_health_after_call: payment_required para "
                           f"'{model_id}' (via {provider}). "
                           f"Cascade: {marked} modelos de pago de '{provider}' "
                           f"marcados como payment_required")
            elif error_type == "empty_response":
                # v5.5: empty_response → failed PERMANENTE.
                # Modelos que retornan 200 OK sin contenido están rotos.
                # No van a funcionar en reintentos — marcar como failed
                # para que no se vuelvan a intentar.
                model_health.mark_failed(base_id, provider, error)
                _global_pool.mark_failed(provider, model_id)
            elif error_type in ("auth", "not_found"):
                # Errores permanentes: marca como failed
                model_health.mark_failed(base_id, provider, error)
                _global_pool.mark_failed(provider, model_id)
            elif error_type in ("timeout", "connection", "server_error", "temporarily_unavailable"):
                # F10: Errores TRANSITORIOS → temporarily_unavailable (cooldown 60s)
                # NO marcar como 'failed' permanente — estos errores son reintentables
                model_health.mark_temporarily_unavailable(base_id, provider, error)
                _global_pool.mark_temporarily_unavailable(provider, model_id)
            else:
                # F10: 'unknown' → temporarily_unavailable en vez de failed
                # Cualquier error desconocido se trata como transitorio
                # (antes era failed permanente → cascada de fallos)
                model_health.mark_temporarily_unavailable(base_id, provider, error)
                _global_pool.mark_temporarily_unavailable(provider, model_id)
    except Exception as e:
        logger.debug(f"_sync_health_after_call error: {e}")


def call_llm(
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.1,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Llama al mejor LLM disponible para la tarea.

    v5.3: Registra métricas completas en UsageTracker v2.0:
    - latencia (ms), tokens input/output, coste estimado (USD),
    - Arena score del modelo, provider, éxito/error con clasificación.

    Las llamadas fallidas TAMBIÉN se registran (success=False).
    """
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
    
    # v5.3: Timing del ciclo completo de llamadas
    call_start_time = time.time()
    
    # v5.6: Bucle con payment discovery (no cuenta como intento real)
    # Cuando un provider falla por falta de crédito (429 insufficient_quota),
    # se marcan TODOS sus modelos de pago como payment_required (cascade),
    # y se reintenta con otro provider SIN consumir un intento real.
    MAX_REAL_ATTEMPTS = 3
    MAX_TOTAL_ATTEMPTS = 8  # Safety: evitar loop infinito
    real_attempt = 0
    total_attempt = 0
    
    while real_attempt < MAX_REAL_ATTEMPTS and total_attempt < MAX_TOTAL_ATTEMPTS:
        total_attempt += 1
        # v5.3: Timing por intento
        attempt_start_time = time.time()
        
        try:
            from core.providers import provider_manager

            # v5.1: Usar select_model_entry() para obtener PoolEntry
            # con provider directo (no call_with_fallback ciego)
            entry = select_model_entry(task_type)
            if entry is None:
                attempt_elapsed = int((time.time() - attempt_start_time) * 1000)
                # v5.3: Registrar fallo (no se pudo seleccionar modelo)
                _log_usage_if_possible(
                    project_id=project_id,
                    model="",
                    task_type=task_type,
                    tokens_input=_estimate_tokens(system_prompt + user_prompt),
                    tokens_output=0,
                    latency_ms=attempt_elapsed,
                    cost_usd=0.0,
                    arena_score=None,
                    provider="",
                    success=False,
                    error_type="no_model_available",
                )
                return {
                    "content": "",
                    "model_used": "",
                    "provider_used": None,
                    "success": False,
                    "attempts": real_attempt + 1,
                    "error": "No se pudo seleccionar modelo",
                    "tokens_input": _estimate_tokens(system_prompt + user_prompt),
                    "tokens_output": 0,
                    "latency_ms": attempt_elapsed,
                    "cost_usd": 0.0,
                    "arena_score": None,
                    "provider": "",
                    "http_status": None,  # P8b
                }

            model_id = entry.model_id  # F6: Esto es ahora un prefixed_id (ej: "OPR:anthropic/claude-opus-4-6")
            provider_name = entry.provider
            # v5.3: Arena score del modelo seleccionado
            arena_score_val = entry.arena_score

            # F6: Extraer base_id del prefixed_id para la llamada real al provider
            # El prefixed_id es para identificar internamente; el base_id es lo que
            # el provider API realmente entiende.
            _, base_id = provider_manager.parse_prefixed_id(model_id)
            if base_id is None or base_id == model_id:
                # No tiene prefijo reconocido — usar tal cual (compatibilidad)
                base_id = model_id

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # v5.1: Intentar provider directo del PoolEntry primero
            # F6: Usar base_id para la traducción y llamada al provider
            result = None
            if provider_name in provider_manager.providers:
                provider = provider_manager.providers[provider_name]
                translated_id = provider_manager.translate_model_id(base_id, provider_name)
                try:
                    result = provider.call(translated_id, messages, max_tokens, temperature)
                    if result.get("success"):
                        result["provider"] = provider_name
                except Exception as e:
                    logger.debug(f"call_llm: provider directo {provider_name} falló: {e}")
                    result = None

            # Fallback: call_with_fallback si provider directo falló
            # F6: Usar base_id para el fallback (los providers no conocen nuestros prefijos)
            if result is None or not result.get("success"):
                result = provider_manager.call_with_fallback(base_id, messages, max_tokens, temperature)

            # v5.3: Calcular latencia de este intento
            attempt_elapsed_ms = int((time.time() - attempt_start_time) * 1000)

            if result.get("success"):
                actual_provider = result.get("provider", provider_name)
                actual_model = result.get("model_used", model_id)

                # Sincronizar health al Pool y model_health
                _sync_health_after_call(model_id, actual_provider, True)

                # F12: Si el modelo que respondió es DIFERENTE del seleccionado (fallback),
                # actualizar arena_score_val y model_id para reflejar la realidad.
                # Antes: se logueaba el score del modelo seleccionado (93.4) aunque
                # respondió un modelo distinto (71.0) → discrepancia Arena.
                if actual_model != base_id and actual_model != model_id:
                    # El fallback usó un modelo distinto — obtener su Arena score real
                    fallback_arena = _get_arena_score(actual_model, task_type)
                    if fallback_arena is not None:
                        arena_score_val = fallback_arena
                        logger.info(f"call_llm: fallback de {base_id} a {actual_model}, "
                                   f"Arena actualizado: {fallback_arena:.1f}")
                    # Sincronizar health del modelo que realmente respondió
                    _sync_health_after_call(actual_model, actual_provider, True)

                # Correccion de trazabilidad de proveedor
                try:
                    is_generic = actual_provider in (None, "openrouter", "unknown", "")
                    if is_generic:
                        inferred = result.get("model_info", {}).get("provider")
                        if not inferred or inferred == "unknown":
                            inferred = _infer_provider(actual_model)
                        if inferred and inferred != "unknown":
                            result["provider"] = inferred
                            actual_provider = inferred
                            logger.debug(f"Provider corrected from '{provider_name}' to '{inferred}' for model {actual_model}")
                except Exception as e:
                    logger.warning(f"Failed to correct provider traceability: {e}")

                # Guardar en cache
                try:
                    _llm_cache.set(user_prompt, actual_model, result, max_tokens=max_tokens, temperature=temperature)
                except Exception as e:
                    logger.warning(f"Cache set failed (continuing): {e}")

                # v5.3: Extraer métricas de tokens
                tokens_input = 0
                tokens_output = 0

                # Intentar extraer del result (algunos providers lo incluyen)
                usage_data = result.get("usage", {})
                if usage_data:
                    tokens_input = usage_data.get("prompt_tokens", 0)
                    tokens_output = usage_data.get("completion_tokens", 0)

                # Fallback: estimar desde el texto
                if tokens_input == 0:
                    tokens_input = _estimate_tokens(system_prompt + user_prompt)
                if tokens_output == 0:
                    tokens_output = _estimate_tokens(result.get("content", ""))

                total_tokens = tokens_input + tokens_output

                # v5.3: Estimar coste
                cost_usd = _estimate_cost_usd(tokens_input, tokens_output, actual_model, actual_provider)

                # v5.3: Obtener Arena score si no lo teníamos del entry
                if arena_score_val is None:
                    arena_score_val = _get_arena_score(actual_model, task_type)

                # v5.3: Registrar uso con métricas completas
                _log_usage_if_possible(
                    project_id=project_id,
                    model=actual_model,
                    task_type=task_type,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    latency_ms=attempt_elapsed_ms,
                    cost_usd=cost_usd,
                    arena_score=arena_score_val,
                    provider=actual_provider,
                    success=True,
                    error_type="",
                    total_tokens=total_tokens,
                )

                return {
                    **result,
                    "attempts": real_attempt + 1,
                    "tokens_input": tokens_input,
                    "tokens_output": tokens_output,
                    "latency_ms": attempt_elapsed_ms,
                    "cost_usd": cost_usd,
                    "arena_score": arena_score_val,
                    "provider": actual_provider,
                }
            
            # Llamada falló — sincronizar health
            error_str = str(result.get("error", "unknown"))
            # v5.4 (F2b): Provider para health sync SIEMPRE usa el del pool entry,
            # porque es la composite key correcta. El result.get("provider") puede
            # ser "unknown" (de call_with_fallback) que no existe en el pool.
            health_provider = provider_name  # Del pool entry — clave para sync
            log_provider = result.get("provider") or provider_name or "unknown"  # Para logging
            _sync_health_after_call(model_id, health_provider, False, error_str)

            # v5.3: Registrar fallo con métricas
            error_type_classified = _classify_error_type(error_str)
            _log_usage_if_possible(
                project_id=project_id,
                model=model_id,
                task_type=task_type,
                tokens_input=_estimate_tokens(system_prompt + user_prompt),
                tokens_output=0,
                latency_ms=attempt_elapsed_ms,
                cost_usd=0.0,
                arena_score=arena_score_val,
                provider=log_provider,
                success=False,
                error_type=error_type_classified,
            )

            # v5.7: Payment discovery — no cuenta como intento real
            # Cuando un provider falla por falta de crédito (429 insufficient_quota),
            # el cascade ya marcó TODOS sus modelos de pago como payment_required.
            # Reintentar con otro provider SIN consumir un intento real.
            if error_type_classified == "payment":
                # v5.7: Logging defensivo — verificar cascade
                provider_pr_count = sum(
                    1 for e in _global_pool.get_all_entries()
                    if e.provider == provider_name and e.health_status == "payment_required"
                )
                provider_total = sum(
                    1 for e in _global_pool.get_all_entries()
                    if e.provider == provider_name
                )
                logger.info(
                    f"call_llm: payment error ({model_id} via {log_provider}), "
                    f"provider sin crédito — no cuenta como intento, "
                    f"reintentando con otro modelo... "
                    f"[cascade: {provider_pr_count}/{provider_total} modelos de "
                    f"'{provider_name}' marcados payment_required]"
                )
                continue  # NO incrementa real_attempt

            # Contar como intento real
            real_attempt += 1

            if result.get("error") == "rate_limit":
                escalate_model(model_id)
                time.sleep(1)
            else:
                # v5.4 (F3): continue en vez de break — permite rotar modelo
                # El modelo actual fue marcado failed por _sync_health_after_call,
                # así que select_model_entry() en el siguiente intento escogerá otro.
                logger.info(f"call_llm: intento {real_attempt}/{MAX_REAL_ATTEMPTS} "
                           f"falló ({error_type_classified}), rotando modelo...")
                # F15: Si es el último intento real, retornar con error_type
                if real_attempt >= MAX_REAL_ATTEMPTS:
                    total_elapsed_ms = int((time.time() - call_start_time) * 1000)
                    return {
                        "content": "",
                        "model_used": model_id,
                        "provider_used": log_provider,
                        "success": False,
                        "attempts": real_attempt,
                        "error": error_str,
                        "error_type": error_type_classified,  # F15: Clasificación del error
                        "tokens_input": _estimate_tokens(system_prompt + user_prompt),
                        "tokens_output": 0,
                        "latency_ms": attempt_elapsed_ms,
                        "cost_usd": 0.0,
                        "arena_score": arena_score_val,
                        "provider": log_provider,
                        "http_status": result.get("http_status"),  # P8b: Propagar HTTP status
                    }
                continue
        except Exception as e:
            attempt_elapsed_ms = int((time.time() - attempt_start_time) * 1000)
            logger.error(f"Excepcion en call_llm: {e}")

            # v5.3: Registrar excepción
            _log_usage_if_possible(
                project_id=project_id,
                model="",
                task_type=task_type,
                tokens_input=_estimate_tokens(system_prompt + user_prompt),
                tokens_output=0,
                latency_ms=attempt_elapsed_ms,
                cost_usd=0.0,
                arena_score=None,
                provider="",
                success=False,
                error_type=_classify_error_type(str(e)),
            )
            break

    # v5.3: Tiempo total del ciclo
    total_elapsed_ms = int((time.time() - call_start_time) * 1000)

    # v5.3: Registrar fallo final (reintentos agotados)
    _log_usage_if_possible(
        project_id=project_id,
        model="",
        task_type=task_type,
        tokens_input=_estimate_tokens(system_prompt + user_prompt),
        tokens_output=0,
        latency_ms=total_elapsed_ms,
        cost_usd=0.0,
        arena_score=None,
        provider="",
        success=False,
        error_type="retries_exhausted",
    )

    return {
        "content": "",
        "model_used": "",
        "provider_used": None,
        "success": False,
        "attempts": total_attempt,
        "error": "Reintentos agotados",
        "error_type": "retries_exhausted",  # F15
        "tokens_input": 0,
        "tokens_output": 0,
        "latency_ms": total_elapsed_ms,
        "cost_usd": 0.0,
        "arena_score": None,
        "provider": "",
        "http_status": None,  # P8b
    }


def _log_usage_if_possible(
    project_id: Optional[str],
    model: str,
    task_type: str,
    tokens_input: int,
    tokens_output: int,
    latency_ms: int,
    cost_usd: float,
    arena_score: Optional[float],
    provider: str,
    success: bool,
    error_type: str,
    total_tokens: int = 0,
) -> None:
    """v5.3: Helper para registrar uso con métricas completas.

    No falla nunca — errores de logging no deben interrumpir el flujo.
    Solo registra si project_id está disponible.
    """
    if project_id is None:
        return

    try:
        from core.usage_tracker import UsageTracker
        if total_tokens == 0:
            total_tokens = tokens_input + tokens_output

        UsageTracker().log_usage(
            project_id=project_id,
            model=model,
            tokens=total_tokens,
            request_type=task_type,
            provider=provider,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            arena_score=arena_score,
            success=success,
            error_type=error_type,
        )
        logger.info(
            f"Usage logged: project={project_id} model={model} "
            f"provider={provider} task={task_type} "
            f"tokens_in={tokens_input} tokens_out={tokens_output} "
            f"latency={latency_ms}ms cost=${cost_usd:.4f} "
            f"arena={arena_score} success={success} "
            f"error_type={error_type}"
        )
    except Exception as e:
        logger.warning(f"Usage tracking failed (continuing): {e}")


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
# BLOQUE DE PRUEBA — v5.3 con métricas completas
# =============================================================================
if __name__ == "__main__":
    import logging
    import time as _time

    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)
    mh_logger = logging.getLogger('core.model_health')
    mh_logger.setLevel(logging.INFO)

    start_time = _time.time()

    print("\n" + "=" * 60)
    print("APA Router v5.3 — Pool + Arena ELO + Health + Métricas Completas")
    print("=" * 60)

    # --- model_health state ---
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

    # --- Pool population (v5.0) ---
    print("\n--- Pool population (P-1 composite key) ---")
    t0 = _time.time()
    pool_count = populate_pool()
    pool_elapsed = _time.time() - t0
    print(f"  {pool_count} entries en el pool ({pool_elapsed:.2f}s)")

    # Pool health summary
    summary = _global_pool.health_summary()
    print(f"  Health: {summary}")

    # Arena scores
    arena_count = sum(1 for e in _global_pool.get_all_entries() if e.arena_score is not None)
    print(f"  Arena scores: {arena_count}/{pool_count}")

    # Providers in pool
    providers_in_pool = set(e.provider for e in _global_pool.get_all_entries())
    print(f"  Providers: {', '.join(sorted(providers_in_pool))}")

    # --- select_model_entry() por tarea ---
    print("\nselect_model_entry() por tarea (PoolEntry):")
    print("-" * 40)
    for task in ["planning", "generation", "coding", "correction", "evaluation"]:
        t0 = _time.time()
        entry = select_model_entry(task)
        elapsed = _time.time() - t0
        if entry:
            score_str = f"{entry.composite_score:.1f}" if entry.composite_score > 0 else "N/A"
            print(f"  {task:12s} -> PoolEntry(provider={entry.provider}, "
                  f"model={entry.model_id}, score={score_str}, "
                  f"health={entry.health_status}) [{elapsed:.2f}s]")
        else:
            print(f"  {task:12s} -> Sin modelo disponible [{elapsed:.2f}s]")

    # --- v5.3: Test de helpers de métricas ---
    print("\nv5.3 — Helpers de métricas:")
    print("-" * 40)

    # _estimate_tokens
    test_text = "Hello, this is a test prompt for estimating tokens."
    est_tokens = _estimate_tokens(test_text)
    print(f"  _estimate_tokens('{test_text[:40]}...') = {est_tokens}")

    # _classify_error_type
    test_errors = [
        ("HTTP 429 Too Many Requests", "rate_limit"),
        ("Request timeout after 30s", "timeout"),
        ("HTTP 402 Payment Required", "payment"),
        ("HTTP 401 Unauthorized", "auth"),
        ("HTTP 404 Model not found", "model_not_found"),
        ("HTTP 500 Internal Server Error", "server"),
        ("Unknown error", "unknown"),
    ]
    for err_str, expected in test_errors:
        classified = _classify_error_type(err_str)
        ok = "OK" if classified == expected else f"FAIL (got {classified})"
        print(f"  _classify_error_type('{err_str}') = {classified} [{ok}]")

    # _estimate_cost_usd
    cost = _estimate_cost_usd(1000, 500, "openai/gpt-4o", "openai")
    print(f"  _estimate_cost_usd(1000 in, 500 out, gpt-4o) = ${cost:.6f}")

    # --- Resumen de salud (pool) ---
    print("\nResumen de salud (pool):")
    print(f"  {summary}")
    avail_entries = _global_pool.get_available_entries()
    if avail_entries:
        print(f"  Available entries: {', '.join(f'{e.model_id}({e.provider})' for e in avail_entries[:10])}")
    else:
        print(f"  No available entries en el pool")

    elapsed = _time.time() - start_time
    print(f"\nTiempo total: {elapsed:.2f}s")

    print("\n" + "=" * 60)
    print("DIAGNOSTICO COMPLETADO")
    print("=" * 60)
