# apa/core/model_health.py
# v4.0 — Sprint 1: payment_required status (D-5),
#         response-code-driven scheduling (D-3/D-4),
#         integración con Pool composite key (P-1).
#
# CAMBIOS v4.0 vs v3.1:
#   - payment_required status (D-5): HTTP 402 → payment_required
#   - mark_payment_required() method
#   - Response-code-driven scheduling (D-3/D-4):
#     * 429 → rate_limited (cooldown)
#     * 402 → payment_required (D-5)
#     * 5xx → failed con retry automático
#   - get_status() reconoce payment_required
#   - _classify_error() retorna 'payment' para 402
#   - report_http_status() — entrada unificada para response codes
#   - Compatibilidad total con v3.1 (sin breaking changes)
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
# Configuración — SESSION TRUST window configurable
# ============================================================================
_DEFAULT_TRUST_WINDOW = 300
_SESSION_TRUST_WINDOW = int(os.environ.get("APA_TRUST_WINDOW", _DEFAULT_TRUST_WINDOW))

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

_HEALTH_CACHE_VERSION = 1
_FLUSH_INTERVAL = 300

_PROBE_MESSAGES = [{"role": "user", "content": "Respond with exactly the word: PING"}]
_PROBE_MAX_TOKENS = 10
_PROBE_TEMPERATURE = 0.0
_PROBE_SYNC_TIMEOUT = 10
_PROBE_BG_TIMEOUT = 15
_PROBE_BG_DELAY = 3
_PROBE_SYNC_DELAY = 1.0

_RATE_LIMIT_BACKOFF_BASE = 60
_RATE_LIMIT_BACKOFF_MAX = 300


def configure(trust_window: int = None) -> None:
    """Configura parámetros de model_health en runtime."""
    global _SESSION_TRUST_WINDOW
    if trust_window is not None:
        _SESSION_TRUST_WINDOW = trust_window
        logger.info(f"SESSION TRUST window configurado a {trust_window}s")


def get_trust_window() -> int:
    """Retorna la ventana SESSION TRUST actual en segundos."""
    return _SESSION_TRUST_WINDOW


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
    """Carga datos de salud desde health_cache.json."""
    global _health_data, _cache_loaded, _last_cache_load_time

    if _cache_loaded and not force:
        return _health_data

    cache_path = _HEALTH_CACHE_PATH
    legacy_path = _ARENA_CACHE_PATH
    trust_window = get_trust_window()

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
    prev_available = 0
    trust_maintained = 0

    for model_id, info in raw_health.items():
        prev_status = info.get("status", "unknown")
        verified_at = _parse_verified_at_epoch(info.get("verified_at"))
        provider = info.get("provider", "")
        probe_errors = info.get("probe_errors", {})
        rate_limited_count = info.get("rate_limited_count", 0) or 0
        rate_limited_at = _parse_verified_at_epoch(info.get("rate_limited_at"))

        if prev_status == "available" and verified_at is not None:
            age = now - verified_at
            if age < trust_window:
                _health_data[model_id] = {
                    "status": "available",
                    "verified_at": verified_at,
                    "provider": provider,
                    "previous_status": prev_status,
                    "error": None,
                    "rate_limited_at": None,
                    "rate_limited_count": 0,
                    "probe_errors": probe_errors,
                }
                trust_maintained += 1
                prev_available += 1
                logger.info(f"SESSION TRUST: {model_id} -> available (age={age:.0f}s)")
                continue
            else:
                logger.debug(f"SESSION TRUST expired: {model_id} (age={age:.0f}s >= {trust_window}s)")

        _health_data[model_id] = {
            "status": "unknown",
            "verified_at": verified_at,
            "provider": provider,
            "previous_status": prev_status,
            "error": None,
            "rate_limited_at": rate_limited_at,
            "rate_limited_count": rate_limited_count,
            "probe_errors": probe_errors,
        }

        if prev_status == "available":
            prev_available += 1

    logger.info(f"Cargados {len(_health_data)} modelos de {source} "
                f"({prev_available} available, {trust_maintained} por SESSION TRUST <{trust_window}s)")

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
        rate_limited = sum(1 for v in _health_data.values() if v.get("status") == "rate_limited")
        failed = sum(1 for v in _health_data.values() if v.get("status") == "failed")
        payment_required = sum(1 for v in _health_data.values() if v.get("status") == "payment_required")
        unknown = sum(1 for v in _health_data.values() if v.get("status") in ("unknown", None))

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
        "rate_limited": rate_limited,
        "failed": failed,
        "payment_required": payment_required,
        "unknown": unknown,
        "verified_models": get_verified_models(),
        "trust_window": get_trust_window(),
    }


def flush_to_disk() -> None:
    """Guarda _health_data en health_cache.json."""
    global _last_flush
    try:
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
    now = _now_epoch()
    with _health_lock:
        for model_id, info in _health_data.items():
            if info.get("status") == "rate_limited":
                rl_at = info.get("rate_limited_at") or 0
                count = info.get("rate_limited_count") or 1
                cooldown = _get_rate_limit_cooldown(count)
                if now - rl_at >= cooldown:
                    info["status"] = "unknown"
                    info["error"] = None
                    info["rate_limited_at"] = None
                    logger.debug(f"{model_id}: rate_limited expirado (cooldown {cooldown}s, #{count}) -> unknown")
            # F10: Limpiar temporarily_unavailable expirados
            elif info.get("status") == "temporarily_unavailable":
                tu_at = info.get("verified_at") or 0
                if now - tu_at >= _TEMPORARILY_UNAVAILABLE_COOLDOWN:
                    info["status"] = "unknown"
                    info["error"] = None
                    logger.debug(f"{model_id}: temporarily_unavailable expirado (cooldown {_TEMPORARILY_UNAVAILABLE_COOLDOWN}s) -> unknown")


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
    """Retorna el estado del modelo: 'available', 'failed', 'unknown', 'rate_limited', o 'payment_required'."""
    if not model_id:
        return "unknown"
    _cleanup_expired_rate_limits()
    with _health_lock:
        info = _health_data.get(model_id)
        return info.get("status", "unknown") if info else "unknown"


def get_verified_models() -> List[str]:
    _cleanup_expired_rate_limits()
    with _health_lock:
        return [mid for mid, info in _health_data.items()
                if info.get("status") == "available"]


def get_all_health() -> Dict[str, Dict[str, Any]]:
    _cleanup_expired_rate_limits()
    with _health_lock:
        return dict(_health_data)


# ============================================================================
# Reportar resultados
# ============================================================================

def mark_available(model_id: str, provider: str = "") -> None:
    if not model_id:
        return
    now = _now_epoch()
    with _health_lock:
        existing = _health_data.get(model_id, {})
        _health_data[model_id] = {
            "status": "available",
            "verified_at": now,
            "provider": provider,
            "error": None,
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": existing.get("probe_errors", {}),
        }
    logger.info(f"{model_id}: VERIFICADO via {provider}")
    maybe_flush()


def mark_failed(model_id: str, provider: str = "", error: str = "") -> None:
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

        _health_data[model_id] = {
            "status": "failed",
            "verified_at": now,
            "provider": provider,
            "error": error,
            "rate_limited_at": None,
            "rate_limited_count": existing.get("rate_limited_count", 0) if existing else 0,
            "probe_errors": prev_errors,
        }
    logger.debug(f"{model_id} -> failed (provider: {provider}, error: {error})")
    maybe_flush()


_TEMPORARILY_UNAVAILABLE_COOLDOWN = 60  # F10: Cooldown para temporarily_unavailable


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

        _health_data[model_id] = {
            "status": "temporarily_unavailable",
            "verified_at": now,
            "provider": provider,
            "error": error,
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": prev_errors,
        }
    logger.info(f"{model_id} -> temporarily_unavailable (provider: {provider}, "
                f"error: {error}, cooldown: {_TEMPORARILY_UNAVAILABLE_COOLDOWN}s)")
    maybe_flush()


def mark_rate_limited(model_id: str, provider: str = "") -> None:
    """D-3: Marca un modelo como rate_limited (HTTP 429 → cooldown)."""
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

        _health_data[model_id] = {
            "status": "rate_limited",
            "verified_at": now,
            "provider": provider,
            "error": "HTTP 429 (rate limit)",
            "rate_limited_at": now,
            "rate_limited_count": new_count,
            "probe_errors": prev_errors,
        }
    logger.debug(f"{model_id} -> rate_limited (provider: {provider}, 429 #{new_count}, cooldown: {cooldown}s)")
    maybe_flush()


def mark_payment_required(model_id: str, provider: str = "") -> None:
    """D-5: Marca un modelo como payment_required (HTTP 402).

    No sobreescribe status 'available'.
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

        _health_data[model_id] = {
            "status": "payment_required",
            "verified_at": now,
            "provider": provider,
            "error": "HTTP 402 (payment required)",
            "rate_limited_at": None,
            "rate_limited_count": 0,
            "probe_errors": prev_errors,
        }
    logger.info(f"{model_id} -> payment_required (provider: {provider})")
    maybe_flush()


def report_http_status(model_id: str, http_status: int, provider: str = "", error_detail: str = "") -> None:
    """D-3/D-4/D-5: Response-Code-Driven Scheduling unificado."""
    if not model_id:
        return

    if http_status == 200:
        mark_available(model_id, provider)
    elif http_status == 429:
        mark_rate_limited(model_id, provider)
    elif http_status == 402:
        mark_payment_required(model_id, provider)
    elif http_status in (404, 401, 403):
        mark_failed(model_id, provider, error_detail or f"HTTP {http_status}")
    elif 500 <= http_status < 600:
        mark_failed(model_id, provider, error_detail or f"HTTP {http_status} (server error, retryable)")
    else:
        logger.warning(f"report_http_status({model_id}): HTTP {http_status} no clasificado")
        mark_failed(model_id, provider, error_detail or f"HTTP {http_status}")


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
             timeout | connection | temporarily_unavailable | unknown
    """
    if not error_str:
        return "unknown"
    err = str(error_str).lower()

    # --- Rate limiting (prioridad máxima) ---
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
                                 "overloaded", "maintenance")):
        return "temporarily_unavailable"

    return "unknown"


# ============================================================================
# Probe verificable
# ============================================================================

def _do_probe_call(model_id: str, provider, provider_name: str) -> Tuple[bool, str, str]:
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
                continue
            except Exception as e:
                logger.debug(f"{model_id}: excepcion en {provider_name}: {e}")
                last_error = str(e)
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
            else:
                logger.debug(f"{model_id}: error en {prov}: {error}")
                last_error = error
                continue

        if had_permanent_error:
            current_status = get_status(model_id)
            if current_status != "rate_limited":
                mark_failed(model_id, "", last_error or "All providers failed")

        return False, ""

    except Exception as e:
        logger.error(f"probe_model({model_id}): excepcion inesperada: {e}")
        return False, ""


def probe_model_sync(model_id: str) -> Tuple[bool, str]:
    return probe_model(model_id, timeout=_PROBE_SYNC_TIMEOUT)


# ============================================================================
# Background probing
# ============================================================================

def _background_probe_ranking(ranking: List[Dict[str, Any]]) -> None:
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
    flush_to_disk()
    logger.info("Sesion cerrada, datos guardados")


# ============================================================================
# Inicializacion al importar
# ============================================================================

try:
    load_health_from_cache()
except Exception as _import_err:
    logger.warning(f"Error en load_health_from_cache() al importar: {_import_err}")


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
    print(f"TEST: Model Health v4.0 — SESSION TRUST + D-5 payment_required")
    print(f"  trust_window={trust_window}s  data_dir={_DATA_DIR}")
    print("=" * 70)

    print(f"\n[1] Modelos cargados de sesion anterior: {len(_health_data)}")
    prev_avail = sum(1 for v in _health_data.values()
                    if v.get("previous_status") == "available")
    trust_maintained = sum(1 for v in _health_data.values()
                          if v.get("status") == "available")
    print(f"    Que estaban available: {prev_avail}")
    print(f"    Mantenidos como available (SESSION TRUST <{trust_window}s): {trust_maintained}")

    for mid, info in _health_data.items():
        st = info.get("status", "unknown")
        prev = info.get("previous_status", "?")
        va = info.get("verified_at")
        if va:
            age = _now_epoch() - va
            print(f"    -> {mid}: {st} (age={age:.0f}s)"
                  f"{' [EXPIRED]' if st != 'available' and prev == 'available' else ''}")
        else:
            print(f"    -> {mid}: {st}")

    print(f"\n[2] Modelos verificados AHORA: {len(get_verified_models())}")

    print(f"\n[2b] Diagnostico:")
    diag = get_diagnostic_info()
    for k, v in diag.items():
        print(f"    {k}: {v}")

    # Probe de prueba
    print(f"\n[3] Probe de prueba (con ID translation):\n")
    try:
        from core.providers import provider_manager
        test_ids = [
            "google/gemma-4-26b-a4b-it:free",
            "deepseek/deepseek-r1:free",
            "qwen/qwen3-coder:free",
            "meta-llama/llama-4-maverick:free",
            "openai/gpt-oss-120b:free",
            "anthropic/claude-opus-4-6",
            "openai/gpt-4o-mini",
            "claude-sonnet-4-6",
        ]
        for mid in test_ids:
            status = get_status(mid)
            print(f"    {mid}: {status}")
            providers_found = provider_manager.find_providers_for_model(mid)
            for p, tid in providers_found:
                print(f"      -> {p.name} (translated: {tid})")
            if not providers_found:
                print(f"      -> Sin providers encontrados")
    except Exception as e:
        print(f"    Error: {e}")

    print(f"\n[4] Test D-5: payment_required status")
    model_health_test = "test-payment-model"
    _health_data[model_health_test] = {"status": "unknown"}
    mark_payment_required(model_health_test, "openrouter")
    assert get_status(model_health_test) == "payment_required", "FAIL: payment_required not set"
    assert is_payment_required(model_health_test), "FAIL: is_payment_required() returns False"
    print(f"    mark_payment_required: OK")
    print(f"    is_payment_required: OK")

    # Test report_http_status
    _health_data["http-test-402"] = {"status": "unknown"}
    report_http_status("http-test-402", 402, "openrouter")
    assert get_status("http-test-402") == "payment_required", "FAIL: HTTP 402 not mapped"
    print(f"    report_http_status(402): OK")

    _health_data["http-test-429"] = {"status": "unknown"}
    report_http_status("http-test-429", 429, "openrouter")
    assert get_status("http-test-429") == "rate_limited", "FAIL: HTTP 429 not mapped"
    print(f"    report_http_status(429): OK")

    _health_data["http-test-500"] = {"status": "unknown"}
    report_http_status("http-test-500", 503, "openrouter")
    assert get_status("http-test-500") == "failed", "FAIL: HTTP 5xx not mapped"
    print(f"    report_http_status(5xx): OK")

    # Available should NOT be overwritten by payment_required
    _health_data["avail-pr-test"] = {"status": "available", "verified_at": _now_epoch()}
    mark_payment_required("avail-pr-test", "openrouter")
    assert get_status("avail-pr-test") == "available", "FAIL: available overwritten by payment_required"
    print(f"    available NOT overwritten by payment_required: OK")

    flush_to_disk()
    print(f"\n    D-5 tests: ALL OK")

    print("\n" + "=" * 70)
    print("TEST COMPLETADO")
    print("=" * 70)