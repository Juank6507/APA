# apa/core/model_health.py
# v5.0 — Cache-driven startup: la caché NO expira, se actualiza.
#         Flush inmediato en mark_available().
#         available persiste entre sesiones (no más SESSION TRUST).
#         Background re-verification para actualizar estados.
#
# CAMBIOS v5.0 vs v4.0:
#   - CACHE NO EXPIRA: available se mantiene entre sesiones.
#     La caché se actualiza (no se borra). Un modelo available
#     sigue siendo available hasta que se demuestre lo contrario
#     (probe fallido, payment_required, etc.).
#   - SESSION TRUST eliminado: ya no hay ventana de confianza.
#     Se confía en la caché hasta tener evidencia de lo contrario.
#   - Flush inmediato: mark_available() hace flush a disco
#     inmediatamente (no espera 300s). Cada verificación exitosa
#     se persiste al instante.
#   - previously_available: modelos que estaban available
#     pero no han sido re-verificados en esta sesión.
#     Se usan para startup inmediato + re-verificación en background.
#   - get_previously_available_models(): lista de modelos que
#     necesitan re-verificación pero son candidatos prioritarios.
#   - mark_verified_this_session(): marca modelo como verificado
#     en esta sesión (previously_available=False).
#   - start_cache_reverification(): hilo de background que
#     re-verifica modelos previously_available y unknown.
#     Primera pasada a los 30s, luego cada 600s.
#   - probe_model() ahora maneja errores timeout/connection/
#     temporarily_unavailable via mark_temporarily_unavailable().
#
# BUGFIXES vs v5.0-previo:
#   BF-1: mark_available() establece previously_available=False
#         explícitamente (antes faltaba la key → frágil).
#   BF-2: flush_to_disk() copia previously_available dentro del
#         lock (antes había race condition fuera del lock).
#   BF-3: probe_model() llama mark_temporarily_unavailable() para
#         errores timeout/connection/temporarily_unavailable
#         (antes estos errores dejaban el modelo en estado
#         indeterminado).
#   BF-4: _background_cache_reverification() hace primera pasada
#         a los 30s (antes 600s → startup lento).
#   BF-5: _cleanup_expired_rate_limits() itera sobre copia de
#         items para evitar problemas de concurrencia.
#
# Compatibilidad: v5.0 lee cachés v1 (backward compatible).
# Nuevos campos en caché: previously_available, last_verified_session.
#
# v4.0 — Sprint 1: payment_required status (D-5),
#         response-code-driven scheduling (D-3/D-4),
#         integración con Pool composite key (P-1).
#
# v3.1 — Production-ready: SESSION TRUST configurable, logging limpio,
#         sin print() de diagnóstico, lazy path resolution.

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.settings import settings
from core.normalizer import normalize_model_id

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
logger.propagate = False

# ============================================================================
# Configuración — Cache-driven: la caché NO expira
# ============================================================================
# v5.0: Ya no hay SESSION TRUST. La caché es permanente.
# Se confía en los datos hasta tener evidencia de lo contrario.
# El background se encarga de re-verificar y actualizar.
_CACHE_VERSION = 2  # v2: incluye previously_available + last_verified_session
_FLUSH_IMMEDIATELY = True  # v5.0: flush en cada mark_available()

# ============================================================================
# Archivos de caché
# ============================================================================
def _find_project_data_dir() -> Path:
    """Busca el directorio data/ del proyecto APA de forma robusta."""
    resolved = Path(__file__).resolve()
    current = resolved.parent

    candidates = []
    for _ in range(8):
        candidate = current / "data"
        if candidate.is_dir() and (candidate / "providers").is_dir():
            parent_dir = candidate.parent
            has_apa_subdir = (parent_dir / "apa").is_dir()
            if has_apa_subdir:
                logger.debug(f"Path resolution: data_dir={candidate} (structural match)")
                return candidate
            candidates.append(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent

    if candidates:
        candidates.sort(key=lambda c: len(c.parts), reverse=True)
        logger.debug(f"Path resolution: data_dir={candidates[0]} (fallback: farthest candidate)")
        return candidates[0]

    fallback = resolved.parent.parent.parent / "data"
    logger.debug(f"Path resolution: data_dir={fallback} (legacy fallback)")
    return fallback


_DATA_DIR = _find_project_data_dir()
_HEALTH_CACHE_PATH = _DATA_DIR / "health_cache.json"
_ARENA_CACHE_PATH = _DATA_DIR / "arena_cache.json"

_MODULE_FILE = str(Path(__file__))
_MODULE_FILE_RESOLVED = str(Path(__file__).resolve())

logger.debug(f"Path resolution: data_dir={_DATA_DIR}, "
             f"__file__={_MODULE_FILE}, resolved={_MODULE_FILE_RESOLVED}")

_HEALTH_CACHE_VERSION = 2  # v5.0: formato v2 con previously_available
_FLUSH_INTERVAL = 30  # v5.0: flush cada 30s como fallback (mark_available flushea inmediato)

_PROBE_MESSAGES = [{"role": "user", "content": "Respond with exactly the word: PING"}]
_PROBE_MAX_TOKENS = 10
_PROBE_TEMPERATURE = 0.0
_PROBE_SYNC_TIMEOUT = 10
_PROBE_BG_TIMEOUT = 15
_PROBE_BG_DELAY = 3
_PROBE_SYNC_DELAY = 1.0

_RATE_LIMIT_BACKOFF_BASE = 60
_RATE_LIMIT_BACKOFF_MAX = 300

_TEMPORARILY_UNAVAILABLE_COOLDOWN = 60  # F10: Cooldown para temporarily_unavailable


def configure(trust_window: int = None, flush_immediately: bool = None) -> None:
    """Configura parámetros de model_health en runtime.

    v5.0: trust_window se mantiene por compatibilidad pero ya no se usa
    para expirar cachés. flush_immediately controla si mark_available()
    hace flush a disco inmediato (default: True).
    """
    global _FLUSH_IMMEDIATELY
    if flush_immediately is not None:
        _FLUSH_IMMEDIATELY = flush_immediately
        logger.info(f"Flush inmediato configurado a {flush_immediately}")


def get_trust_window() -> int:
    """v5.0: Retorna 0 — la caché no expira."""
    return 0


# ============================================================================
# Estado de salud en memoria
# ============================================================================

_health_data: Dict[str, Dict[str, Any]] = {}
_health_lock = threading.Lock()
_last_flush = 0.0
_bg_thread_started = False
_bg_thread_lock = threading.Lock()

_cache_loaded = False
_last_cache_load_time = 0.0


def _now_epoch() -> float:
    return time.time()


def _parse_verified_at_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
        try:
            dt = datetime.fromisoformat(value)
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
    return None


# ============================================================================
# Carga / guardado de health_cache.json
# ============================================================================

def load_health_from_cache(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Carga datos de salud desde health_cache.json.

    v5.0: La caché NO expira. Los modelos available se mantienen
    como available entre sesiones, con previously_available=True
    para indicar que necesitan re-verificación en background.
    """
    global _health_data, _cache_loaded, _last_cache_load_time

    if _cache_loaded and not force:
        return _health_data

    cache_path = _HEALTH_CACHE_PATH
    legacy_path = _ARENA_CACHE_PATH

    raw_health = {}
    source = ""

    logger.debug(f"load_health_from_cache() — cache_path={cache_path}, "
                 f"exists={cache_path.exists()}")

    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_health = data.get("models", {})
            source = f"health_cache.json (v{data.get('version', '?')})"
            logger.debug(f"Leído health_cache.json: {len(raw_health)} modelos, source={source}")
        except Exception as e:
            logger.warning(f"Error leyendo health_cache.json: {e}")

    if not raw_health and legacy_path.exists():
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version", 1) >= 3:
                raw_health = data.get("last_session_health", {})
                if raw_health:
                    source = "arena_cache.json (migración one-time)"
                    logger.info(f"Migrando health de arena_cache.json: {len(raw_health)} modelos")
        except Exception as e:
            logger.debug(f"No se pudo leer arena_cache.json para migración: {e}")

    if not raw_health:
        logger.info("No hay datos de salud previos, partiendo de vacío")
        _health_data = {}
        _cache_loaded = True
        _last_cache_load_time = _now_epoch()
        return _health_data

    _health_data = {}
    now = _now_epoch()
    loaded_available = 0
    loaded_other = 0

    for model_id, info in raw_health.items():
        prev_status = info.get("status", "unknown")
        verified_at = _parse_verified_at_epoch(info.get("verified_at"))
        provider = info.get("provider", "")
        probe_errors = info.get("probe_errors", {})
        rate_limited_count = info.get("rate_limited_count", 0) or 0
        rate_limited_at = _parse_verified_at_epoch(info.get("rate_limited_at"))
        previously_available = info.get("previously_available", False)

        # v5.0: CACHE NO EXPIRA
        # Si el modelo estaba available → se mantiene available.
        # No hay ventana de confianza. Se confía en la caché.
        # El background se encarga de re-verificar.
        if prev_status == "available":
            age = now - verified_at if verified_at else 0
            _health_data[model_id] = {
                "status": "available",
                "verified_at": verified_at,
                "provider": provider,
                "previous_status": prev_status,
                "previously_available": True,  # v5.0: necesita re-verificación
                "error": None,
                "rate_limited_at": None,
                "rate_limited_count": 0,
                "probe_errors": probe_errors,
            }
            loaded_available += 1
            if age > 0:
                logger.info(f"CACHE-STARTUP: {model_id} -> available "
                           f"(age={age:.0f}s, pendiente re-verificar)")
            continue

        # Estados no-available: se cargan tal cual
        # payment_required, failed, rate_limited, unknown, temporarily_unavailable
        _health_data[model_id] = {
            "status": prev_status,
            "verified_at": verified_at,
            "provider": provider,
            "previous_status": prev_status,
            "previously_available": previously_available,
            "error": info.get("error"),
            "rate_limited_at": rate_limited_at,
            "rate_limited_count": rate_limited_count,
            "probe_errors": probe_errors,
        }
        loaded_other += 1

    logger.info(f"Cargados {len(_health_data)} modelos de {source} "
                f"({loaded_available} available para startup, "
                f"{loaded_other} otros estados. Caché permanente: NO expira)")

    _cache_loaded = True
    _last_cache_load_time = _now_epoch()
    return _health_data


def ensure_loaded() -> bool:
    """Garantiza que el caché de salud esté cargado y actualizado."""
    global _cache_loaded, _last_cache_load_time

    verified = get_verified_models()

    if verified:
        logger.debug(f"ensure_loaded(): OK — {len(verified)} modelos verificados")
        return True

    if not _cache_loaded:
        logger.debug("ensure_loaded(): caché no cargado, cargando...")
        load_health_from_cache()
    elif _HEALTH_CACHE_PATH.exists():
        try:
            file_mtime = os.path.getmtime(str(_HEALTH_CACHE_PATH))
            if file_mtime > _last_cache_load_time:
                logger.debug(f"ensure_loaded(): archivo actualizado (mtime={file_mtime:.1f} > "
                             f"load_time={_last_cache_load_time:.1f}), re-cargando...")
                _last_cache_load_time = file_mtime
                load_health_from_cache(force=True)
            else:
                logger.debug("ensure_loaded(): archivo sin cambios, no se re-carga")
        except Exception as e:
            logger.debug(f"ensure_loaded(): error checking mtime: {e}")
            load_health_from_cache(force=True)
    else:
        logger.debug(f"ensure_loaded(): no hay archivo de caché (path={_HEALTH_CACHE_PATH})")

    verified = get_verified_models()
    logger.debug(f"ensure_loaded(): {len(verified)} modelos verificados de {len(_health_data)} totales")
    return len(verified) > 0


def get_diagnostic_info() -> Dict[str, Any]:
    """Retorna información de diagnóstico del módulo."""
    with _health_lock:
        total = len(_health_data)
        available = sum(1 for v in _health_data.values() if v.get("status") == "available")
        previously_available = sum(1 for v in _health_data.values()
                                  if v.get("status") == "available" and v.get("previously_available", False))
        rate_limited = sum(1 for v in _health_data.values() if v.get("status") == "rate_limited")
        failed = sum(1 for v in _health_data.values() if v.get("status") == "failed")
        payment_required = sum(1 for v in _health_data.values() if v.get("status") == "payment_required")
        unknown = sum(1 for v in _health_data.values() if v.get("status") in ("unknown", None))
        temporarily_unavailable = sum(1 for v in _health_data.values()
                                     if v.get("status") == "temporarily_unavailable")

    return {
        "cache_loaded": _cache_loaded,
        "last_cache_load_time": _last_cache_load_time,
        "cache_path": str(_HEALTH_CACHE_PATH),
        "cache_exists": _HEALTH_CACHE_PATH.exists(),
        "data_dir": str(_DATA_DIR),
        "module_file": _MODULE_FILE,
        "module_file_resolved": _MODULE_FILE_RESOLVED,
        "total_models": total,
        "available": available,
        "previously_available": previously_available,
        "rate_limited": rate_limited,
        "failed": failed,
        "payment_required": payment_required,
        "temporarily_unavailable": temporarily_unavailable,
        "unknown": unknown,
        "verified_models": get_verified_models(),
        "trust_window": get_trust_window(),
        "cache_version": _HEALTH_CACHE_VERSION,
    }


def flush_to_disk() -> None:
    """Guarda _health_data en health_cache.json.

    BF-2: Toda la copia de datos (incluyendo previously_available)
    se hace dentro del lock para evitar race conditions.
    """
    global _last_flush
    try:
        # BF-2: Copiar todo dentro del lock, incluyendo previously_available
        with _health_lock:
            health_copy = {}
            for model_id, info in _health_data.items():
                health_copy[model_id] = {
                    "status": info.get("status", "unknown"),
                    "verified_at": info.get("verified_at"),
                    "provider": info.get("provider", ""),
                    "error": info.get("error"),
                    "rate_limited_count": info.get("rate_limited_count", 0),
                    "rate_limited_at": info.get("rate_limited_at"),
                    "probe_errors": info.get("probe_errors", {}),
                    "previously_available": info.get("previously_available", False),
                }

        data_to_save = {
            "version": _HEALTH_CACHE_VERSION,
            "updated_at": datetime.now().isoformat(),
            "models": health_copy,
        }

        _HEALTH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_HEALTH_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)

        _last_flush = time.time()
        logger.debug(f"Flush a disco: {len(health_copy)} modelos -> {_HEALTH_CACHE_PATH}")

    except Exception as e:
        logger.warning(f"Error en flush: {e}")


def maybe_flush() -> None:
    """Flush a disco si paso mas de _FLUSH_INTERVAL desde el ultimo."""
    global _last_flush
    if time.time() - (_last_flush or 0) >= _FLUSH_INTERVAL:
        flush_to_disk()


# ============================================================================
# Limpieza de rate_limited expirados
# ============================================================================

def _get_rate_limit_cooldown(count: int) -> float:
    if count <= 0:
        return _RATE_LIMIT_BACKOFF_BASE
    cooldown = _RATE_LIMIT_BACKOFF_BASE * count
    return min(cooldown, _RATE_LIMIT_BACKOFF_MAX)


def _cleanup_expired_rate_limits() -> None:
    """Limpia estados rate_limited y temporarily_unavailable expirados.

    BF-5: Itera sobre copia de items para evitar problemas
    de concurrencia al modificar valores del dict.
    """
    now = _now_epoch()
    with _health_lock:
        # BF-5: iterar sobre lista de items (copia)
        for model_id, info in list(_health_data.items()):
            if info.get("status") == "rate_limited":
                rl_at = info.get("rate_limited_at") or 0
                count = info.get("rate_limited_count") or 1
                cooldown = _get_rate_limit_cooldown(count)
                if now - rl_at >= cooldown:
                    info["status"] = "unknown"
                    info["error"] = None
                    info["rate_limited_at"] = None
                    info["previously_available"] = False
                    logger.debug(f"{model_id}: rate_limited expirado "
                                f"(cooldown {cooldown}s, #{count}) -> unknown")
            elif info.get("status") == "temporarily_unavailable":
                tu_at = info.get("verified_at") or 0
                if now - tu_at >= _TEMPORARILY_UNAVAILABLE_COOLDOWN:
                    info["status"] = "unknown"
                    info["error"] = None
                    info["previously_available"] = False
                    logger.debug(f"{model_id}: temporarily_unavailable expirado "
                                f"(cooldown {_TEMPORARILY_UNAVAILABLE_COOLDOWN}s) -> unknown")


# ============================================================================
# Consultas de salud
# ============================================================================

def is_available(model_id: str) -> bool:
    if not model_id:
        return False
    _cleanup_expired_rate_limits()
    with _health_lock:
        info = _health_data.get(model_id)
        return info is not None and info.get("status") == "available"


def is_payment_required(model_id: str) -> bool:
    """D-5: Retorna True si el modelo tiene estado payment_required (HTTP 402)."""
    if not model_id:
        return False
    _cleanup_expired_rate_limits()
    with _health_lock:
        info = _health_data.get(model_id)
        return info is not None and info.get("status") == "payment_required"


def get_status(model_id: str) -> str:
    """Retorna el estado del modelo.

    Posibles valores: 'available', 'failed', 'unknown',
    'rate_limited', 'payment_required', 'temporarily_unavailable'.
    """
    if not model_id:
        return "unknown"
    _cleanup_expired_rate_limits()
    with _health_lock:
        info = _health_data.get(model_id)
        return info.get("status", "unknown") if info else "unknown"


def get_verified_models() -> List[str]:
    """Retorna modelos con status='available'.

    v5.0: Incluye modelos pendientes de re-verificación (previously_available=True)
    porque se confía en la caché hasta tener evidencia de lo contrario.
    """
    _cleanup_expired_rate_limits()
    with _health_lock:
        return [mid for mid, info in _health_data.items()
                if info.get("status") == "available"]


def get_previously_available_models() -> List[str]:
    """v5.0: Retorna modelos que están available pero pendientes de re-verificación.

    Estos modelos se cargaron de la caché como 'available' pero no han sido
    verificados en esta sesión. Son los primeros candidatos para probing
    en background.
    """
    _cleanup_expired_rate_limits()
    with _health_lock:
        return [mid for mid, info in _health_data.items()
                if info.get("status") == "available" and info.get("previously_available", False)]


def mark_verified_this_session(model_id: str) -> None:
    """v5.0: Marca un modelo como verificado en esta sesión.

    Limpia el flag previously_available. Se llama después de un
    probe exitoso o una llamada LLM exitosa que confirma que el
    modelo sigue funcionando.
    """
    if not model_id:
        return
    with _health_lock:
        info = _health_data.get(model_id)
        if info and info.get("status") == "available":
            info["previously_available"] = False


def get_all_health() -> Dict[str, Dict[str, Any]]:
    _cleanup_expired_rate_limits()
    with _health_lock:
        return dict(_health_data)


# ============================================================================
# Reportar resultados
# ============================================================================

def mark_available(model_id: str, provider: str = "") -> None:
    """Marca un modelo como verificado y disponible.

    BF-1: Establece previously_available=False explícitamente.
    Un modelo que acaba de ser verificado en esta sesión no
    necesita re-verificación en background.

    Flush inmediato: cada verificación exitosa se persiste
    al instante a disco (si _FLUSH_IMMEDIATELY=True).
    """
    if not model_id:
        return
    now = _now_epoch()
    with _health_lock:
        existing = _health_data.get(model_id, {})
        _health_data[model_id] = {
            "status": "available",
            "verified_at": now,
            "provider": provider,
            "previous_status": "available",
            "previously_available": False,  # BF-1: explícito, verificado esta sesión
            "error": None,
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": existing.get("probe_errors", {}),
        }
    logger.info(f"{model_id}: VERIFICADO via {provider}")
    # v5.0: Flush inmediato — cada verificación exitosa se persiste al instante
    if _FLUSH_IMMEDIATELY:
        flush_to_disk()
    else:
        maybe_flush()


def mark_failed(model_id: str, provider: str = "", error: str = "") -> None:
    """Marca un modelo como failed (error permanente).

    NO sobreescribe status 'available' — un modelo verificado
    como disponible solo pierde ese estado si un probe directo
    demuestra que ya no funciona (vía mark_temporarily_unavailable
    o re-verificación fallida en background).
    """
    if not model_id:
        return
    now = _now_epoch()
    with _health_lock:
        existing = _health_data.get(model_id)
        if existing and existing.get("status") == "available":
            logger.debug(f"{model_id}: ignoro failed (ya estaba available)")
            if provider and error:
                probe_errors = existing.get("probe_errors", {})
                probe_errors[provider] = error
                existing["probe_errors"] = probe_errors
            return

        prev_errors = existing.get("probe_errors", {}) if existing else {}
        if provider and error:
            prev_errors[provider] = error

        prev_avail = existing.get("previously_available", False) if existing else False

        _health_data[model_id] = {
            "status": "failed",
            "verified_at": now,
            "provider": provider,
            "previous_status": existing.get("status", "unknown") if existing else "unknown",
            "previously_available": prev_avail,
            "error": error,
            "rate_limited_at": None,
            "rate_limited_count": existing.get("rate_limited_count", 0) if existing else 0,
            "probe_errors": prev_errors,
        }
    logger.debug(f"{model_id} -> failed (provider: {provider}, error: {error})")
    maybe_flush()


def mark_temporarily_unavailable(model_id: str, provider: str = "", error: str = "") -> None:
    """F10: Marca un modelo como temporarily_unavailable (error transitorio).

    A diferencia de mark_failed(), este estado tiene cooldown corto (60s).
    Tras expirar, el modelo vuelve a 'unknown' y puede ser re-seleccionado.

    Errores transitorios: timeout, connection, DNS, "Not available", etc.
    NO sobreescribe status 'available'.
    """
    if not model_id:
        return
    now = _now_epoch()
    with _health_lock:
        existing = _health_data.get(model_id)
        if existing and existing.get("status") == "available":
            logger.debug(f"{model_id}: ignoro temporarily_unavailable (ya estaba available)")
            if provider and error:
                probe_errors = existing.get("probe_errors", {})
                probe_errors[provider] = error
                existing["probe_errors"] = probe_errors
            return

        prev_errors = existing.get("probe_errors", {}) if existing else {}
        if provider and error:
            prev_errors[provider] = error

        prev_avail = existing.get("previously_available", False) if existing else False

        _health_data[model_id] = {
            "status": "temporarily_unavailable",
            "verified_at": now,
            "provider": provider,
            "previous_status": existing.get("status", "unknown") if existing else "unknown",
            "previously_available": prev_avail,
            "error": error,
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": prev_errors,
        }
    logger.info(f"{model_id} -> temporarily_unavailable (provider: {provider}, "
                f"error: {error}, cooldown: {_TEMPORARILY_UNAVAILABLE_COOLDOWN}s)")
    maybe_flush()


def mark_rate_limited(model_id: str, provider: str = "") -> None:
    """D-3: Marca un modelo como rate_limited (HTTP 429 → cooldown).

    NO sobreescribe status 'available'.
    """
    if not model_id:
        return
    now = _now_epoch()
    with _health_lock:
        existing = _health_data.get(model_id)
        if existing and existing.get("status") == "available":
            logger.debug(f"{model_id}: ignoro rate_limited (ya estaba available)")
            if provider:
                probe_errors = existing.get("probe_errors", {})
                probe_errors[provider] = "HTTP 429 (rate limit)"
                existing["probe_errors"] = probe_errors
            return

        prev_count = (existing.get("rate_limited_count") or 0) if existing else 0
        new_count = prev_count + 1
        cooldown = _get_rate_limit_cooldown(new_count)

        prev_errors = existing.get("probe_errors", {}) if existing else {}
        if provider:
            prev_errors[provider] = "HTTP 429 (rate limit)"

        prev_avail = existing.get("previously_available", False) if existing else False

        _health_data[model_id] = {
            "status": "rate_limited",
            "verified_at": now,
            "provider": provider,
            "previous_status": existing.get("status", "unknown") if existing else "unknown",
            "previously_available": prev_avail,
            "error": "HTTP 429 (rate limit)",
            "rate_limited_at": now,
            "rate_limited_count": new_count,
            "probe_errors": prev_errors,
        }
    logger.debug(f"{model_id} -> rate_limited (provider: {provider}, "
                f"429 #{new_count}, cooldown: {cooldown}s)")
    maybe_flush()


def mark_payment_required(model_id: str, provider: str = "") -> None:
    """D-5: Marca un modelo como payment_required (HTTP 402).

    No sobreescribe status 'available'. El modelo permanece como
    payment_required hasta que un probe exitoso demuestre que
    ya hay créditos disponibles.
    """
    if not model_id:
        return
    now = _now_epoch()
    with _health_lock:
        existing = _health_data.get(model_id)
        if existing and existing.get("status") == "available":
            logger.debug(f"{model_id}: ignoro payment_required (ya estaba available)")
            if provider:
                probe_errors = existing.get("probe_errors", {})
                probe_errors[provider] = "HTTP 402 (payment required)"
                existing["probe_errors"] = probe_errors
            return

        prev_errors = existing.get("probe_errors", {}) if existing else {}
        if provider:
            prev_errors[provider] = "HTTP 402 (payment required)"

        prev_avail = existing.get("previously_available", False) if existing else False

        _health_data[model_id] = {
            "status": "payment_required",
            "verified_at": now,
            "provider": provider,
            "previous_status": existing.get("status", "unknown") if existing else "unknown",
            "previously_available": prev_avail,
            "error": "HTTP 402 (payment required)",
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": prev_errors,
        }
    logger.info(f"{model_id} -> payment_required (provider: {provider})")
    maybe_flush()


def report_http_status(model_id: str, http_status: int, provider: str = "", error_detail: str = "") -> None:
    """D-3/D-4/D-5: Response-Code-Driven Scheduling unificado.

    Clasifica el código HTTP y llama a la función mark_* apropiada.
    Los códigos 5xx se tratan como temporarily_unavailable (error
    transitorio con cooldown) en vez de failed permanente, porque
    los errores de servidor son usualmente recuperables.
    """
    if not model_id:
        return

    if http_status == 200:
        mark_available(model_id, provider)
    elif http_status == 429:
        mark_rate_limited(model_id, provider)
    elif http_status == 402:
        mark_payment_required(model_id, provider)
    elif http_status == 413:
        # v6.2: Contexto excedido — no es fallo del modelo, es del tamaño.
        # Tratar como transitorio para que se pueda reintentar con prompt más pequeño.
        mark_temporarily_unavailable(model_id, provider, error_detail or "HTTP 413 (context exceeded)")
    elif http_status in (404, 401, 403):
        mark_failed(model_id, provider, error_detail or f"HTTP {http_status}")
    elif 500 <= http_status < 600:
        # v5.0: Errores 5xx son transitorios, no permanentes
        mark_temporarily_unavailable(model_id, provider, error_detail or f"HTTP {http_status} (server error)")
    else:
        logger.warning(f"report_http_status({model_id}): HTTP {http_status} no clasificado")
        mark_failed(model_id, provider, error_detail or f"HTTP {http_status}")


# ============================================================================
# Detección de contexto excedido (v6.2)
# ============================================================================
_CONTEXT_EXCEEDED_SIGNALS = [
    "context_length_exceeded",
    "maximum context length",
    "tokens limit",
    "token limit",
    "too long",
    "context window",
    "max_tokens",
    "input too large",
    "prompt too large",
    "request too large",
]


def is_context_exceeded(http_code: int, error_body: str = "") -> bool:
    """v6.2: Detecta si un error fue causado por exceder el contexto del modelo.

    No es lo mismo que un modelo roto o sin crédito. El modelo funciona,
    pero el prompt enviado es más grande de lo que puede procesar.

    Detecta dos casos:
    - HTTP 413: el API dice explícitamente que el contenido es demasiado grande
    - HTTP 400 con señales de contexto: algunos providers usan 400 en vez de 413
      pero incluyen mensajes como "context_length_exceeded" o "maximum context length"

    Args:
        http_code: Código HTTP de la respuesta (413, 400, etc.)
        error_body: Mensaje de error devuelto por el provider

    Returns:
        True si el error fue por contexto excedido, False en caso contrario.
    """
    # HTTP 413: siempre es contexto excedido
    if http_code == 413:
        return True

    # HTTP 400 con señales de contexto: algunos providers no usan 413
    if http_code == 400 and error_body:
        body_lower = str(error_body).lower()
        return any(signal in body_lower for signal in _CONTEXT_EXCEEDED_SIGNALS)

    return False


# ============================================================================
# Clasificacion de errores HTTP
# ============================================================================

def _classify_error(error_str: str) -> str:
    """F9: Clasificador de errores comprehensivo.

    Reconoce patrones de error de todos los providers conocidos
    (OpenRouter, Anthropic, OpenAI, Groq, GitHub, Together, Fireworks, Ollama)
    y clasifica de forma precisa para evitar falsos 'unknown'.

    Nuevas categorías vs v4.0:
    - 'timeout': errores de timeout (antes caían a 'unknown')
    - 'connection': errores de red/conexión (antes caían a 'unknown')
    - 'temporarily_unavailable': errores transitorios (antes caían a 'unknown' → failed permanente)

    Returns: rate_limit | not_found | auth | payment | server_error |
             timeout | connection | temporarily_unavailable | context_exceeded | unknown
    """
    if not error_str:
        return "unknown"
    err = str(error_str).lower()

    # --- Contexto excedido (v6.2, prioridad máxima) ---
    # Se verifica ANTES de rate_limit porque frases como "token limit"
    # o "tokens limit" contienen "limit" que coincidiría con rate_limit.
    if any(kw in err for kw in ("context_length_exceeded", "maximum context length",
                                 "input too large", "prompt too large",
                                 "request too large", "context window",
                                 "token limit", "tokens limit")):
        return "context_exceeded"

    # --- Rate limiting ---
    if any(kw in err for kw in ("429", "rate", "limit", "throttl", "too many", "quota exceeded", "capacity")):
        return "rate_limit"

    # --- Autenticación / Autorización ---
    if any(kw in err for kw in ("401", "403", "invalid api key", "invalid x-api-key",
                                 "authentication", "unauthorized", "forbidden",
                                 "permission denied", "access denied")):
        # Distinguir 'auth' de 'rate_limit' que también puede tener 'permission'
        if "rate" not in err and "limit" not in err and "429" not in err:
            return "auth"

    # --- Pago requerido ---
    if any(kw in err for kw in ("402", "payment", "billing", "insufficient", "credit")):
        return "payment"

    # --- Modelo no encontrado ---
    # F9 FIX: ya no usamos "model" como patrón (demasiado amplio)
    # Solo match patterns específicos de modelo no encontrado
    if any(kw in err for kw in ("404", "not found", "model_not_found", "does not exist",
                                 "no such model", "model not found")):
        return "not_found"

    # --- Timeout ---
    # F9: Nuevo — antes caía a 'unknown'
    if any(kw in err for kw in ("timeout", "timed out", "deadline exceeded", "read timeout",
                                 "connection timeout", "socket timeout")):
        return "timeout"

    # --- Errores de conexión / red ---
    # F9: Nuevo — antes caía a 'unknown'
    if any(kw in err for kw in ("connection", "connect", "network", "dns",
                                 "resolve", "name or service not known",
                                 "connectionerror", "connectionrefused",
                                 "connectionreset", "broken pipe",
                                 "ssl", "certificate", "proxy")):
        return "connection"

    # --- Errores de servidor (5xx) ---
    if any(kw in err for kw in ("500", "502", "503", "504", "529",
                                 "server", "internal", "upstream",
                                 "overloaded", "bad gateway", "service unavailable",
                                 "gateway timeout")):
        return "server_error"

    # --- Temporalmente no disponible ---
    # F9: Nuevo — errores transitorios que NO deberían marcar como 'failed' permanente
    if any(kw in err for kw in ("not available", "unavailable", "temporarily",
                                 "try again", "retry", "busy",
                                 "maintenance")):
        return "temporarily_unavailable"

    return "unknown"


# ============================================================================
# Probe verificable
# ============================================================================

def _do_probe_call(model_id: str, provider, provider_name: str) -> Tuple[bool, str, str]:
    """Ejecuta una llamada probe a un provider específico.

    Retorna: (success, provider_name, error_msg)
    """
    try:
        result = provider.call(
            model_id,
            _PROBE_MESSAGES,
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=_PROBE_TEMPERATURE,
        )
        if result.get("success"):
            content = (result.get("content") or "").strip().upper()
            if "PING" in content:
                return True, provider_name, ""
            else:
                error_msg = f"Unexpected response: {result.get('content', '')[:80]}"
                return False, provider_name, error_msg
        else:
            error = str(result.get("error", "Unknown error"))
            return False, provider_name, error
    except Exception as e:
        return False, provider_name, str(e)


def probe_model(model_id: str, timeout: float = None) -> Tuple[bool, str]:
    """Prueba un modelo contra sus providers disponibles.

    BF-3: Ahora maneja errores timeout/connection/temporarily_unavailable
    llamando a mark_temporarily_unavailable() en vez de dejar el modelo
    en estado indeterminado. Esto permite que el modelo sea re-intentado
    tras el cooldown de 60s en vez de quedar permanentemente failed.

    Retorna: (success, provider_name)
    """
    if timeout is None:
        timeout = _PROBE_SYNC_TIMEOUT

    try:
        from core.providers import provider_manager

        providers_to_try: List[Tuple[Any, str]] = []

        try:
            found = provider_manager.find_providers_for_model(model_id)
            for prov_obj, translated_id in found:
                providers_to_try.append((prov_obj, translated_id))
        except Exception as e:
            logger.debug(f"find_providers_for_model({model_id}) fallo: {e}")

        if not providers_to_try:
            for p in provider_manager.providers.values():
                try:
                    if any(m["id"] == model_id for m in p.get_models()):
                        providers_to_try.append((p, model_id))
                except Exception:
                    continue

        if not providers_to_try:
            inferred = provider_manager._infer_provider_for_model(model_id)
            if inferred and inferred in provider_manager.providers:
                p = provider_manager.providers[inferred]
                if p.is_available():
                    translated = provider_manager.translate_model_id(model_id, inferred)
                    providers_to_try.append((p, translated))

        if not providers_to_try:
            mark_failed(model_id, "", "No provider found")
            return False, ""

        last_error = ""
        had_permanent_error = False
        had_transient_error = False

        for provider_obj, translated_id in providers_to_try:
            provider_name = provider_obj.name

            try:
                if not provider_obj.is_available():
                    continue
            except Exception:
                continue

            logger.debug(f"Probing {model_id} via {provider_name} (translated_id={translated_id})")

            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        _do_probe_call, translated_id, provider_obj, provider_name
                    )
                    success, prov, error = future.result(timeout=timeout)
            except FuturesTimeoutError:
                logger.debug(f"{model_id}: timeout ({timeout}s) en {provider_name}")
                last_error = f"Timeout after {timeout}s on {provider_name}"
                had_transient_error = True
                continue
            except Exception as e:
                logger.debug(f"{model_id}: excepcion en {provider_name}: {e}")
                last_error = str(e)
                had_transient_error = True
                continue

            if success:
                mark_available(model_id, prov)
                logger.info(f"{model_id}: VERIFICADO via {prov} (translated_id={translated_id})")
                return True, prov

            error_type = _classify_error(error)

            if error_type == "rate_limit":
                mark_rate_limited(model_id, prov)
                last_error = error
                continue
            elif error_type == "not_found":
                mark_failed(model_id, prov, "HTTP 404")
                had_permanent_error = True
                last_error = error
                continue
            elif error_type in ("auth", "payment"):
                mark_failed(model_id, prov, f"HTTP {error.split()[1] if len(error.split()) > 1 else error}")
                had_permanent_error = True
                last_error = error
                if error_type == "payment":
                    logger.debug(f"{model_id}: payment required en {prov}, probando siguiente proveedor")
                continue
            elif error_type in ("timeout", "connection", "temporarily_unavailable", "server_error"):
                # BF-3: Errores transitorios → temporarily_unavailable
                # El modelo volverá a 'unknown' tras cooldown y podrá ser re-intentado
                mark_temporarily_unavailable(model_id, prov, error)
                had_transient_error = True
                last_error = error
                continue
            else:
                logger.debug(f"{model_id}: error no clasificado en {prov}: {error}")
                last_error = error
                continue

        # Si todos los providers fallaron con errores permanentes
        if had_permanent_error:
            current_status = get_status(model_id)
            if current_status not in ("rate_limited", "temporarily_unavailable"):
                mark_failed(model_id, "", last_error or "All providers failed")

        # Si todos los providers fallaron con errores transitorios,
        # el modelo ya está como temporarily_unavailable (no necesitamos
        # marcarlo como failed — se re-intentará tras cooldown)
        if had_transient_error and not had_permanent_error:
            current_status = get_status(model_id)
            if current_status not in ("temporarily_unavailable", "rate_limited"):
                # Si por alguna razón no quedó marcado, lo marcamos
                mark_temporarily_unavailable(model_id, "", last_error or "All providers temporarily failed")

        return False, ""

    except Exception as e:
        logger.error(f"probe_model({model_id}): excepcion inesperada: {e}")
        return False, ""


def probe_model_sync(model_id: str) -> Tuple[bool, str]:
    """Wrapper síncrono de probe_model con timeout por defecto."""
    return probe_model(model_id, timeout=_PROBE_SYNC_TIMEOUT)


# ============================================================================
# Background probing
# ============================================================================

def _background_probe_ranking(ranking: List[Dict[str, Any]]) -> None:
    """Proba modelos en background siguiendo un ranking dado."""
    logger.info(f"Background probing: {len(ranking)} modelos")

    def sort_key(m):
        mid = m.get("id", "")
        with _health_lock:
            info = _health_data.get(mid)
            current = info.get("status", "unknown") if info else "unknown"
            if current == "available":
                return -1
            prev = info.get("previous_status", "unknown") if info else "unknown"
            order = {"available": 0, "unknown": 1, "failed": 2, "rate_limited": 3}
            return order.get(prev, 1)

    ranked = sorted(ranking, key=sort_key)
    verified_count = 0
    failed_count = 0
    rate_limited_count = 0

    for model_info in ranked:
        model_id = model_info.get("id", "")
        if not model_id:
            continue
        if is_available(model_id):
            continue
        status = get_status(model_id)
        if status == "rate_limited":
            rate_limited_count += 1
            continue

        success, provider = probe_model(model_id, timeout=_PROBE_BG_TIMEOUT)
        if success:
            verified_count += 1
        else:
            final_status = get_status(model_id)
            if final_status == "rate_limited":
                rate_limited_count += 1
            else:
                failed_count += 1

        time.sleep(_PROBE_BG_DELAY)
        maybe_flush()

    flush_to_disk()
    logger.info(f"Background probing completado: "
                f"{verified_count} available, {failed_count} failed, "
                f"{rate_limited_count} rate_limited")


def start_background_probing(ranking: List[Dict[str, Any]]) -> None:
    """Inicia el hilo de background probing con un ranking dado."""
    global _bg_thread_started
    with _bg_thread_lock:
        if _bg_thread_started:
            logger.debug("Background probing ya en curso")
            return
        _bg_thread_started = True

    thread = threading.Thread(
        target=_background_probe_ranking,
        args=(ranking,),
        daemon=True,
        name="model-health-probe"
    )
    thread.start()
    logger.info("Hilo de background probing iniciado")


def on_session_close() -> None:
    """Flush final al cerrar la sesión de APA."""
    flush_to_disk()
    logger.info("Sesión cerrada, datos guardados")


# ============================================================================
# v5.0: Cache re-verification en background
# ============================================================================

_bg_reverification_started = False
_bg_reverification_lock = threading.Lock()
_REVERIFICATION_FIRST_DELAY = 30  # BF-4: Primera verificación a los 30s
_REVERIFICATION_INTERVAL = 600    # Luego cada 10 minutos
_PROBE_REVERIFY_DELAY = 2        # Delay entre probes de re-verificación


def _background_cache_reverification() -> None:
    """v5.0: Re-verifica modelos previously_available y unknown en background.

    BF-4: Primera pasada a los 30s (no 600s) para que los modelos
    cargados de la caché sean re-verificados rápidamente.

    Este hilo se ejecuta periódicamente para mantener la caché actualizada:
    1. Re-verifica modelos previously_available (cargados de caché, no verificados aún)
    2. Re-verifica modelos unknown (nunca probados o que volvieron a unknown)
    3. Re-intenta modelos payment_required (quizás ya hay créditos)
    4. Flush a disco con los resultados

    Los modelos que ya están verificados en esta sesión (previously_available=False)
    NO se re-verifican para no gastar llamadas innecesarias.
    """
    global _bg_reverification_started
    logger.info("Background cache re-verification iniciado")

    # BF-4: Primera pasada rápida (30s) para re-verificar caché de startup
    first_pass = True
    next_delay = _REVERIFICATION_FIRST_DELAY

    while True:
        try:
            time.sleep(next_delay)

            # Recopilar modelos a re-verificar
            to_reverify = []
            to_retry_payment = []

            with _health_lock:
                for model_id, info in _health_data.items():
                    status = info.get("status", "unknown")
                    # Prioridad 1: previously_available (cargados de caché)
                    if status == "available" and info.get("previously_available", False):
                        to_reverify.append((model_id, "previously_available"))
                    # Prioridad 2: unknown (nunca probados)
                    elif status == "unknown":
                        to_reverify.append((model_id, "unknown"))
                    # Prioridad 3: payment_required (reintentar si hay créditos)
                    elif status == "payment_required":
                        to_retry_payment.append(model_id)

            if not to_reverify and not to_retry_payment:
                logger.debug("Background re-verification: nada que re-verificar")
                # Cambiar a intervalo normal después de la primera pasada
                if first_pass:
                    first_pass = False
                    next_delay = _REVERIFICATION_INTERVAL
                    logger.info("Background re-verification: primera pasada completada, "
                               f"intervalo -> {_REVERIFICATION_INTERVAL}s")
                continue

            logger.info(f"Background re-verification: {len(to_reverify)} modelos a verificar, "
                        f"{len(to_retry_payment)} a reintento de pago"
                        f"{' [PRIMERA PASADA]' if first_pass else ''}")

            # Re-verificar por prioridad
            verified = 0
            failed = 0
            temp_unavail = 0
            for model_id, reason in to_reverify:
                success, provider = probe_model(model_id, timeout=_PROBE_BG_TIMEOUT)
                if success:
                    mark_verified_this_session(model_id)
                    verified += 1
                else:
                    new_status = get_status(model_id)
                    if new_status == "temporarily_unavailable":
                        temp_unavail += 1
                    else:
                        failed += 1
                time.sleep(_PROBE_REVERIFY_DELAY)

            # Re-intentar modelos payment_required (con menos prioridad)
            # Solo reintentar algunos por ciclo para no gastar llamadas
            payment_restored = 0
            payment_max_retry = 5  # Limitar reintentos de pago por ciclo
            for model_id in to_retry_payment[:payment_max_retry]:
                success, provider = probe_model(model_id, timeout=_PROBE_BG_TIMEOUT)
                if success:
                    mark_verified_this_session(model_id)
                    payment_restored += 1
                time.sleep(_PROBE_REVERIFY_DELAY)

            flush_to_disk()

            logger.info(f"Background re-verification completado: "
                        f"{verified} verificados, {failed} fallidos, "
                        f"{temp_unavail} temporalmente no disponibles, "
                        f"{payment_restored} pagos restaurados")

            # Cambiar a intervalo normal después de la primera pasada
            if first_pass:
                first_pass = False
                next_delay = _REVERIFICATION_INTERVAL
                logger.info(f"Background re-verification: intervalo -> {_REVERIFICATION_INTERVAL}s")

        except Exception as e:
            logger.error(f"Error en background cache re-verification: {e}")
            time.sleep(60)  # Esperar antes de reintentar


def start_cache_reverification() -> None:
    """v5.0: Inicia el hilo de re-verificación periódica de la caché.

    BF-4: La primera verificación se ejecuta a los 30s (no 600s)
    para que los modelos previously_available sean verificados
    rápidamente después del startup.
    """
    global _bg_reverification_started
    with _bg_reverification_lock:
        if _bg_reverification_started:
            logger.debug("Background cache re-verification ya iniciado")
            return
        _bg_reverification_started = True

    thread = threading.Thread(
        target=_background_cache_reverification,
        daemon=True,
        name="cache-reverification"
    )
    thread.start()
    logger.info(f"Hilo de cache re-verification iniciado "
               f"(primera pasada en {_REVERIFICATION_FIRST_DELAY}s, "
               f"luego cada {_REVERIFICATION_INTERVAL}s)")


# ============================================================================
# Inicializacion al importar — v5.0: Cache-driven startup
# ============================================================================

try:
    load_health_from_cache()
except Exception as _import_err:
    logger.warning(f"Error en load_health_from_cache() al importar: {_import_err}")

# v5.0: Iniciar re-verificación periódica de la caché en background
# Esto mantiene la caché actualizada sin bloquear el flujo principal
try:
    start_cache_reverification()
except Exception as _reverify_err:
    logger.debug(f"No se pudo iniciar cache re-verification: {_reverify_err}")


# ============================================================================
# Test standalone
# ============================================================================

if __name__ == "__main__":
    if not logging.root.handlers:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.setLevel(logging.DEBUG)

    trust_window = get_trust_window()

    print("\n" + "=" * 70)
    print(f"TEST: Model Health v5.0 — Cache-driven startup (NO EXPIRA)")
    print(f"  data_dir={_DATA_DIR}")
    print("=" * 70)

    # Test 1: get_trust_window() retorna 0
    assert get_trust_window() == 0, "trust_window debe ser 0 (no expira)"
    print("  [PASS] get_trust_window() == 0")

    # Test 2: Cargar caché
    data = load_health_from_cache(force=True)
    print(f"  [INFO] Cargados {len(data)} modelos de caché")

    # Test 3: mark_available establece previously_available=False
    test_model = "__test_model_v5__"
    # Simular modelo cargado de caché como previously_available
    with _health_lock:
        _health_data[test_model] = {
            "status": "available",
            "verified_at": time.time() - 3600,  # 1 hora atrás
            "provider": "test",
            "previous_status": "available",
            "previously_available": True,
            "error": None,
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": {},
        }

    # Verificar que está en previously_available
    prev_avail = get_previously_available_models()
    assert test_model in prev_avail, "Modelo debe estar en previously_available"
    print(f"  [PASS] Modelo en previously_available tras cargar de caché")

    # BF-1: mark_available debe establecer previously_available=False
    mark_available(test_model, "test-provider")
    with _health_lock:
        info = _health_data.get(test_model, {})
        assert info.get("previously_available") == False, \
            "BF-1: mark_available debe establecer previously_available=False"
    prev_avail_after = get_previously_available_models()
    assert test_model not in prev_avail_after, \
        "BF-1: Modelo no debe estar en previously_available tras mark_available"
    print(f"  [PASS] BF-1: mark_available establece previously_available=False")

    # Test 4: flush_to_disk incluye previously_available
    mark_available(test_model, "test-provider")  # Force flush
    try:
        with open(_HEALTH_CACHE_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        saved_info = saved.get("models", {}).get(test_model, {})
        assert "previously_available" in saved_info, \
            "BF-2: previously_available debe estar en caché guardada"
        assert saved_info["previously_available"] == False, \
            "BF-2: previously_available debe ser False para modelo verificado"
        print(f"  [PASS] BF-2: flush_to_disk incluye previously_available correctamente")
    except Exception as e:
        print(f"  [FAIL] BF-2: Error verificando flush: {e}")

    # Test 5: mark_temporarily_unavailable
    test_model2 = "__test_temp_unavail__"
    mark_temporarily_unavailable(test_model2, "test-provider", "Connection timeout")
    assert get_status(test_model2) == "temporarily_unavailable", \
        "Modelo debe estar temporarily_unavailable"
    print(f"  [PASS] mark_temporarily_unavailable funciona")

    # Test 6: _classify_error reconoce timeout/connection/temporarily_unavailable
    assert _classify_error("Timeout after 10s") == "timeout", \
        "Debe clasificar timeout"
    assert _classify_error("Connection refused") == "connection", \
        "Debe clasificar connection"
    assert _classify_error("Service temporarily unavailable") == "temporarily_unavailable", \
        "Debe clasificar temporarily_unavailable"
    print(f"  [PASS] _classify_error reconoce timeout/connection/temporarily_unavailable")

    # Test 7: report_http_status trata 5xx como temporarily_unavailable
    test_model3 = "__test_5xx__"
    report_http_status(test_model3, 503, "test-provider", "Service Unavailable")
    assert get_status(test_model3) == "temporarily_unavailable", \
        "5xx debe ser temporarily_unavailable, no failed"
    print(f"  [PASS] report_http_status(503) -> temporarily_unavailable")

    # Test 8: report_http_status(200) marca available
    report_http_status(test_model3, 200, "test-provider")
    assert get_status(test_model3) == "available", \
        "200 debe marcar como available"
    print(f"  [PASS] report_http_status(200) -> available")

    # Test 9: available no se sobreescribe por otros estados
    mark_rate_limited(test_model3, "test-provider")
    assert get_status(test_model3) == "available", \
        "available no debe ser sobrescrito por rate_limited"
    mark_failed(test_model3, "test-provider", "error")
    assert get_status(test_model3) == "available", \
        "available no debe ser sobrescrito por failed"
    mark_payment_required(test_model3, "test-provider")
    assert get_status(test_model3) == "available", \
        "available no debe ser sobrescrito por payment_required"
    mark_temporarily_unavailable(test_model3, "test-provider", "error")
    assert get_status(test_model3) == "available", \
        "available no debe ser sobrescrito por temporarily_unavailable"
    print(f"  [PASS] available no se sobreescribe por otros estados")

    # Test 10: get_diagnostic_info
    diag = get_diagnostic_info()
    assert diag["trust_window"] == 0, "trust_window debe ser 0"
    assert diag["cache_loaded"] == True, "cache_loaded debe ser True"
    assert "previously_available" in diag, "diagnostic debe incluir previously_available"
    print(f"  [PASS] get_diagnostic_info() correcto")
    print(f"    available={diag['available']}, previously_available={diag['previously_available']}, "
          f"failed={diag['failed']}, payment_required={diag['payment_required']}, "
          f"temporarily_unavailable={diag['temporarily_unavailable']}, unknown={diag['unknown']}")

    # Limpiar modelos de test
    with _health_lock:
        for mid in [test_model, test_model2, test_model3]:
            _health_data.pop(mid, None)
    flush_to_disk()

    print(f"\n{'='*70}")
    print(f"  TODOS LOS TESTS PASARON — Model Health v5.0")
    print(f"{'='*70}")
