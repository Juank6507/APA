# apa/core/model_health.py
# v3.1 — Production-ready: SESSION TRUST configurable, logging limpio,
#         sin print() de diagnóstico, lazy path resolution.
#
# ============================================================================
# APROXIMACIÓN v3.1 vs RESULTADO ESPERADO:
#   v3.0 era funcional pero tenía problemas de producción:
#   - print() de diagnóstico por toda la consola en producción
#   - Duplicate logging (logger + root logger propagation)
#   - SESSION TRUST window hardcoded (300s, no configurable)
#   - Path resolution diagnostic impreso al importar (ruidoso)
#
#   v3.1 FIX:
#   1. Todos los print() → logger.debug() (solo visibles con DEBUG level)
#   2. logger.propagate = False → elimina duplicados de logging
#   3. SESSION TRUST window configurable via APA_TRUST_WINDOW env var
#      o parámetro en configure()
#   4. Path resolution diagnostic solo a logger.debug()
#   5. configure() API para cambiar parámetros en runtime
#   6. Standalone test usa logging.basicConfig (no print directo)
#
#   RESULTADO ESPERADO:
#   - Salida limpia en producción (solo INFO/WARNING/ERROR)
#   - Sin líneas duplicadas
#   - SESSION TRUST window configurable sin tocar código
#   - Diagnósticos disponibles via logger.debug() cuando se necesitan
# ============================================================================
#
# CAMBIOS v3.1 vs v3.0:
#   - logger.propagate = False → elimina duplicate log lines
#   - Todos los print() de diagnóstico → logger.debug()
#   - logger.info() solo para eventos importantes (SESSION TRUST, carga, flush)
#   - _SESSION_TRUST_WINDOW configurable via APA_TRUST_WINDOW env var
#   - configure(trust_window=...) para cambio en runtime
#   - Path resolution diagnostic: print() → logger.debug()
#   - Import-time print() eliminado
#   - Standalone test: print() solo en __main__, funciones usan logger
#
# CAMBIOS v3.0 vs v2.9:
#   - (v3.0 fue la versión del usuario con cambios menores)
#
# CAMBIOS v2.9 vs v2.8:
#   - _find_project_data_dir(): búsqueda robusta del data dir correcto
#   - Path(__file__).resolve() para path absoluto antes de calcular parent.parent
#   - get_diagnostic_info() incluye _module_file y _module_file_resolved
#   - Eliminado cálculo frágil parent.parent.parent / "data"
#
# CONCEPTO:
#   - Al iniciar sesión: cargar health_cache.json (lo que funcionaba antes)
#   - SESSION TRUST: modelos verificados hace <trust_window → mantener como "available"
#   - Probar modelos en orden de ranking Arena (probe verificable)
#   - El primer modelo que responde = modelo seleccionado
#   - Background: seguir verificando el resto del ranking
#   - Todo en memoria, flush a disco cada 5 min o al cerrar
#
# PROBE VERIFICABLE:
#   Prompt: "Respond with exactly the word: PING"
#   Verificación: respuesta contiene "PING" (case-insensitive)
#   Timeout: 10s para probe sincrónico, 15s para background

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

# v3.1: Solo agregar handler si no hay; NO propagar al root logger
# (evita líneas duplicadas cuando root logger también tiene handler)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
logger.propagate = False  # v3.1: Evita duplicate log lines

# ============================================================================
# Configuración — SESSION TRUST window configurable
# ============================================================================
# Prioridad: configure() > APA_TRUST_WINDOW env var > default 300s
_DEFAULT_TRUST_WINDOW = 300
_SESSION_TRUST_WINDOW = int(os.environ.get("APA_TRUST_WINDOW", _DEFAULT_TRUST_WINDOW))

# ============================================================================
# Archivos de caché
# ============================================================================
# v2.9: _find_project_data_dir() busca el data dir correcto sin depender
# de la profundidad de __file__. En Windows, __file__ puede ser relativo
# cuando el módulo se importa como paquete.

def _find_project_data_dir() -> Path:
    """Busca el directorio data/ del proyecto APA de forma robusta.

    ESTRATEGIA:
    1. Resolve __file__ a path absoluto
    2. Caminar hacia arriba buscando data/ con providers/
    3. Para cada data/ candidato, verificar que su directorio padre
       contiene 'apa/' como subdirectorio (marcador del raíz del proyecto)
    4. Si no encuentra con criterio estructural, usar el data/ más
       alejado de __file__ (el del raíz, no el interno)
    5. Último fallback: parent.parent.parent / "data" (v2.8)
    """
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

# v2.9: Guardar info del módulo para diagnóstico
_MODULE_FILE = str(Path(__file__))
_MODULE_FILE_RESOLVED = str(Path(__file__).resolve())

# v3.1: Path resolution diagnostic va a logger.debug(), no a print()
logger.debug(f"Path resolution: data_dir={_DATA_DIR}, "
             f"__file__={_MODULE_FILE}, resolved={_MODULE_FILE_RESOLVED}")

_HEALTH_CACHE_VERSION = 1
_FLUSH_INTERVAL = 300

# Prompt verificable para probe
_PROBE_MESSAGES = [{"role": "user", "content": "Respond with exactly the word: PING"}]
_PROBE_MAX_TOKENS = 10
_PROBE_TEMPERATURE = 0.0
_PROBE_SYNC_TIMEOUT = 10
_PROBE_BG_TIMEOUT = 15
_PROBE_BG_DELAY = 3
_PROBE_SYNC_DELAY = 1.0

# Rate limit y backoff
_RATE_LIMIT_BACKOFF_BASE = 60
_RATE_LIMIT_BACKOFF_MAX = 300


def configure(trust_window: int = None) -> None:
    """Configura parámetros de model_health en runtime.

    Args:
        trust_window: Ventana SESSION TRUST en segundos. Si es None,
                      no se cambia el valor actual.
    """
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
    """Retorna el tiempo actual como epoch float."""
    return time.time()


def _parse_verified_at_epoch(value: Any) -> Optional[float]:
    """Convierte verified_at a epoch float. Acepta ISO string, epoch float, o None."""
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
    """Carga datos de salud desde health_cache.json (archivo separado).

    SESSION TRUST: Si un modelo estaba "available" y fue verificado
    hace menos de trust_window segundos, se mantiene como "available"
    en lugar de marcarlo como "unknown".

    v3.1: Todos los diagnostics via logger.debug(), no print().
    """
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

    # 1. Intentar leer health_cache.json
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_health = data.get("models", {})
            source = f"health_cache.json (v{data.get('version', '?')})"
            logger.debug(f"Leído health_cache.json: {len(raw_health)} modelos, source={source}")
        except Exception as e:
            logger.warning(f"Error leyendo health_cache.json: {e}")

    # 2. Migración one-time desde arena_cache.json
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

    # Procesar datos de salud
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

        # SESSION TRUST
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

        # No califica para SESSION TRUST
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
    """Garantiza que el caché de salud esté cargado y actualizado.

    v2.8: Usa mtime del archivo para detectar si el caché fue actualizado
    por otro proceso después de la carga inicial.

    v3.1: Todos los diagnostics via logger.debug().

    Retorna True si hay modelos verificados disponibles.
    """
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
    """Retorna información de diagnóstico del módulo (para debugging)."""
    with _health_lock:
        total = len(_health_data)
        available = sum(1 for v in _health_data.values() if v.get("status") == "available")
        rate_limited = sum(1 for v in _health_data.values() if v.get("status") == "rate_limited")
        failed = sum(1 for v in _health_data.values() if v.get("status") == "failed")
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
# Limpieza de rate_limited expirados (con exponential backoff)
# ============================================================================

def _get_rate_limit_cooldown(count: int) -> float:
    """Calcula cooldown para rate_limited basado en 429s consecutivos.
    Exponential backoff: 60->120->180->300 (maximo)
    """
    if count <= 0:
        return _RATE_LIMIT_BACKOFF_BASE
    cooldown = _RATE_LIMIT_BACKOFF_BASE * count
    return min(cooldown, _RATE_LIMIT_BACKOFF_MAX)


def _cleanup_expired_rate_limits() -> None:
    """Convierte rate_limited expirados de vuelta a unknown."""
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


# ============================================================================
# Consultas de salud (en memoria, O(1))
# ============================================================================

def is_available(model_id: str) -> bool:
    """Retorna True si el modelo esta verificado como available."""
    if not model_id:
        return False
    _cleanup_expired_rate_limits()
    with _health_lock:
        info = _health_data.get(model_id)
        return info is not None and info.get("status") == "available"


def get_status(model_id: str) -> str:
    """Retorna el estado del modelo: 'available', 'failed', 'unknown', o 'rate_limited'."""
    if not model_id:
        return "unknown"
    _cleanup_expired_rate_limits()
    with _health_lock:
        info = _health_data.get(model_id)
        return info.get("status", "unknown") if info else "unknown"


def get_verified_models() -> List[str]:
    """Retorna lista de modelos verificados como available."""
    _cleanup_expired_rate_limits()
    with _health_lock:
        return [mid for mid, info in _health_data.items()
                if info.get("status") == "available"]


def get_all_health() -> Dict[str, Dict[str, Any]]:
    """Retorna copia del estado de salud de todos los modelos (diagnostico)."""
    _cleanup_expired_rate_limits()
    with _health_lock:
        return dict(_health_data)


# ============================================================================
# Reportar resultados
# ============================================================================

def mark_available(model_id: str, provider: str = "") -> None:
    """Marca un modelo como disponible (verificado)."""
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
    """Marca un modelo como fallido permanentemente (404, auth, etc)."""
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


def mark_rate_limited(model_id: str, provider: str = "") -> None:
    """Marca un modelo como rate_limited (error 429 temporal).
    Exponential backoff: 60->120->180->300s cooldown.
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


# ============================================================================
# Clasificacion de errores HTTP
# ============================================================================

def _classify_error(error_str: str) -> str:
    """Clasifica un error HTTP.
    Retorna: 'rate_limit', 'not_found', 'auth', 'payment', 'server_error', 'unknown'
    """
    err = str(error_str).lower()
    if "429" in err or "rate" in err:
        return "rate_limit"
    if "404" in err or "not found" in err:
        return "not_found"
    if "401" in err or "403" in err or "auth" in err or "permission" in err:
        return "auth"
    if "402" in err or "payment" in err:
        return "payment"
    if "500" in err or "502" in err or "503" in err or "server" in err:
        return "server_error"
    return "unknown"


# ============================================================================
# Probe verificable — con ID translation y TODOS los proveedores
# ============================================================================

def _do_probe_call(model_id: str, provider, provider_name: str) -> Tuple[bool, str, str]:
    """Hace la llamada HTTP real al proveedor. Retorna (success, provider_name, error_msg)."""
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
    """Hace un probe verificable a un modelo usando find_providers_for_model().

    Retorna: (success: bool, provider_name: str)
    """
    if timeout is None:
        timeout = _PROBE_SYNC_TIMEOUT

    try:
        from core.providers import provider_manager

        providers_to_try: List[Tuple[Any, str]] = []

        # 1. Usar find_providers_for_model()
        try:
            found = provider_manager.find_providers_for_model(model_id)
            for prov_obj, translated_id in found:
                providers_to_try.append((prov_obj, translated_id))
        except Exception as e:
            logger.debug(f"find_providers_for_model({model_id}) fallo: {e}")

        # 2. Fallback: buscar en listas de proveedores
        if not providers_to_try:
            for p in provider_manager.providers.values():
                try:
                    if any(m["id"] == model_id for m in p.get_models()):
                        providers_to_try.append((p, model_id))
                except Exception:
                    continue

        # 3. Segundo fallback: inferir proveedor por prefijo
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

        # Probar cada proveedor con su ID traducido
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

        # Todos los proveedores fallaron
        if had_permanent_error:
            current_status = get_status(model_id)
            if current_status != "rate_limited":
                mark_failed(model_id, "", last_error or "All providers failed")

        return False, ""

    except Exception as e:
        logger.error(f"probe_model({model_id}): excepcion inesperada: {e}")
        return False, ""


def probe_model_sync(model_id: str) -> Tuple[bool, str]:
    """Probe sincronico con timeout. Para uso en select_model."""
    return probe_model(model_id, timeout=_PROBE_SYNC_TIMEOUT)


# ============================================================================
# Background probing
# ============================================================================

def _background_probe_ranking(ranking: List[Dict[str, Any]]) -> None:
    """Verifica todos los modelos del ranking en segundo plano."""
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
    """Lanza el probing en segundo plano si no esta ya corriendo."""
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
    """Llamar al cerrar la sesion para flush final."""
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
    # v3.1: Tambien habilitar DEBUG para este modulo en standalone
    logger.setLevel(logging.DEBUG)

    trust_window = get_trust_window()

    print("\n" + "=" * 70)
    print(f"TEST: Model Health v3.1 — SESSION TRUST + production logging")
    print(f"  trust_window={trust_window}s  data_dir={_DATA_DIR}")
    print("=" * 70)

    # Estado actual
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

    # Diagnostico
    print(f"\n[2b] Diagnostico:")
    diag = get_diagnostic_info()
    for k, v in diag.items():
        print(f"    {k}: {v}")

    # Probe de prueba
    print(f"\n[3] Probe de prueba (gratuitos primero, con ID translation):\n")
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
                print(f"      -> provider={p.name}, translated_id={tid}")
            print(f"    Probing {mid}...")
            success, prov = probe_model_sync(mid)
            info = get_all_health().get(mid, {})
            err_detail = ""
            if not success:
                errors = info.get("probe_errors", {})
                rl_count = info.get("rate_limited_count", 0)
                rl_at = info.get("rate_limited_at")
                if errors:
                    err_detail = " | errores: " + ", ".join(f"{k}: {v}" for k, v in errors.items())
                if rl_count:
                    cooldown = _get_rate_limit_cooldown(rl_count)
                    err_detail += f" (429 #{rl_count}, cooldown: {cooldown}s)"
            print(f"    -> {'OK' if success else 'FAIL'} (provider: {prov}, "
                  f"status: {info.get('status', '?')}{err_detail})\n")
    except Exception as e:
        print(f"    Error en probe de prueba: {e}")

    # Estado despues de probes
    print(f"\n[4] Estado despues de probes:")
    for mid, info in get_all_health().items():
        status = info.get("status", "unknown")
        provider = info.get("provider", "")
        errors = info.get("probe_errors", {})
        rl_count = info.get("rate_limited_count", 0)
        rl_at = info.get("rate_limited_at")

        detail = ""
        if status == "available":
            detail = f" (provider: {provider})"
        elif errors:
            detail = f" [{' | '.join(f'{k}->{v}' for k, v in errors.items())}]"
        if rl_count:
            cooldown = _get_rate_limit_cooldown(rl_count)
            detail += f" (429 #{rl_count}, cooldown: {cooldown}s)"
        if rl_at and status == "rate_limited":
            age = _now_epoch() - rl_at
            detail += f" | per-provider: {', '.join(f'{k}->{v}' for k, v in errors.items())}"

        print(f"    {mid}: {status}{detail}")

    flush_to_disk()
    print(f"\n[5] Cache guardado en: {_HEALTH_CACHE_PATH}")

    # SESSION TRUST verification
    print(f"\n[6] SESSION TRUST verification:")
    for mid in get_verified_models():
        info = get_all_health().get(mid, {})
        va = info.get("verified_at")
        if va:
            age = _now_epoch() - va
            ok = "OK" if age < get_trust_window() else "EXPIRED"
            print(f"    {mid}: epoch={va}, age={age:.0f}s {ok}")

    print("\n" + "=" * 70)
    print("TEST COMPLETADO")
    print("=" * 70)
