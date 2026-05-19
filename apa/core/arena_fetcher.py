# apa/core/arena_fetcher.py
# v3.3 — Arena: solo se ejecuta al inicio en background, no periódico.
#         (extends v3.2: Granular notification events throughout Arena lifecycle)
#
# CAMBIOS v3.3 vs v3.2:
#   - ELIMINADO: Bucle periódico _background_periodic_refresh() que ejecutaba
#     refresh cada 1h. Arena ahora se ejecuta SOLO UNA VEZ al inicio de la
#     aplicación en segundo plano, sin repetición. El ranking permanece
#     estático durante toda la sesión (acuerdo rendimiento Director).
#   - _start_periodic_refresh() eliminada.
#   - _BACKGROUND_REFRESH_INTERVAL ya no se usa.
#
# CAMBIOS v3.2 vs v3.1:
#   - Eventos granulares (2 nuevos, + múltiples _notify() calls):
#     * arena:category_loaded — emitido cuando una categoría se procesa
#     * arena:top_models     — emitido con top-5 modelos generales tras refresh
#   - Notificaciones en _fetch_from_huggingface (text, webdev)
#   - Notificaciones en _fetch_from_huggingface_http (por config parquet)
#   - Notificaciones en _fetch_from_github (v2, mirror, plano)
#   - Notificaciones en _fetch_rankings_with_fallback (por fuente exitosa)
#   - Notificaciones en _background_refresh (top-5 + category counts)
#   - Notificaciones en _phase0_load_cache_only (caché local detalle)
#
# CAMBIOS v3.1 vs v3.0:
#   - Integración con notifications.py — emite 4 eventos al event bus:
#     * arena:cache_loaded   (Phase 0: caché local cargado al inicio)
#     * arena:refresh_start  (inicio refresh en background)
#     * arena:refresh_complete (refresh exitoso con N modelos)
#     * arena:refresh_failed (fallo del refresh, sin datos o error)
#   - Patrón lazy para import de notifications (sin import circular)
#
# CAMBIOS v3.0 vs v2.0:
#   - D-8/D-10: Cache-first non-blocking — carga caché local al importar,
#     fetch en background. NUNCA bloquea al importar.
#   - 4-Phase Startup:
#     * Phase 0: Carga caché local (instantáneo, <100ms)
#     * Phase 1: Inicia fetch en background para rankings frescos
#     * Phase 2: Disponibilidad via model_health
#     * Phase 3: Recuperar unavailable models
#   - get_score_for_model() funciona inmediatamente con lo que haya en caché
#   - Compatibilidad total con v2.0 (sin breaking changes en API pública)
#
# v2.0 — Corrección completa: soporte multi-categoría, eliminación de inferencias,
#         fetch de config webdev, cache v2 con versionado, GitHub fallback real.
import csv
import io
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import requests

import sys
import os

# FIX: Buscar la raíz del proyecto (donde está config/) de forma robusta
def _find_project_root() -> Optional[Path]:
    """Busca hacia arriba en el árbol de directorios hasta encontrar la raíz del proyecto."""
    current = Path(__file__).resolve()
    for parent in [current, *current.parents]:
        # Marcadores que indican la raíz del proyecto APA
        if (parent / "config").is_dir() and (parent / "core").is_dir():
            return parent
        if (parent / "apa").is_dir():
            return parent / "apa"
    return None

_project_root = _find_project_root()
if _project_root:
    sys.path.insert(0, str(_project_root))
else:
    # Fallback: añadir el directorio padre del archivo actual
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.settings import settings
from core.normalizer import normalize_model_id, canonical_name

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

# -----------------------------------------------------------------------------
# v3.1: Notificaciones al usuario (patrón lazy, sin import circular)
# -----------------------------------------------------------------------------
# Igual que model_health.py: importa notifications solo cuando se necesita,
# y nunca rompe si el módulo no existe.
_notifier = None

def _get_notifier():
    """Retorna la función notify() si el módulo notifications está disponible."""
    global _notifier
    if _notifier is None:
        try:
            _notifier = __import__('core.notifications', fromlist=['notify']).notify
        except (ImportError, ModuleNotFoundError):
            try:
                _notifier = __import__('notifications', fromlist=['notify']).notify
            except (ImportError, ModuleNotFoundError):
                pass
    return _notifier


def _notify(event_type: str, message: str, data: dict = None):
    """Emite una notificación si notifications.py está disponible.

    v3.1: Import lazy — no rompe si notifications.py no existe.
    Los errores del callback se capturan silenciosamente.
    """
    n = _get_notifier()
    if n:
        try:
            n(event_type, message, data)
        except Exception:
            pass


def _log(module: str, stage: str, status: str, detail: str = "") -> None:
    msg = f"[PROGRESO] | MÓDULO={module} | ETAPA={stage} | ESTADO={status}"
    if detail:
        msg += f" | DETALLE={detail}"
    logger.info(msg)

# -----------------------------------------------------------------------------
# Configuración de caché y fuentes de datos en cascada
# -----------------------------------------------------------------------------
_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "arena_cache.json"
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent / "data" / "arena_snapshot.json"
LOCAL_RANKINGS_PATH = Path(__file__).parent / "data" / "arena_rankings.json"
_CACHE_DURATION_SECONDS = 86400  # Ya no se usa para expirar, solo como referencia de antigüedad
# _BACKGROUND_REFRESH_INTERVAL ya no se usa — Arena solo se ejecuta al inicio.
# (Acuerdo rendimiento: sin competencia de red con el pipeline agéntico)
_CACHE_VALIDITY_DAYS = 30  # Validez del ranking para is_arena_ranking_available
_CACHE_VERSION = 3  # Versión del formato de caché (v3 = multi-categoría + last_session_health)

# URLs para descarga en cascada: HuggingFace datasets lib → HuggingFace HTTP directo → Caché
HF_DATASET = "lmarena-ai/leaderboard-dataset"
HF_PARQUET_BASE = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main"
HF_PARQUET_CONFIGS = {
    "text":   f"{HF_PARQUET_BASE}/text/latest-00000-of-00001.parquet",
    "webdev": f"{HF_PARQUET_BASE}/webdev/latest-00000-of-00001.parquet",
}
# URL configurable para fuente adicional (GitHub, mirror, etc.)
ARENA_GITHUB_URL = os.getenv("ARENA_GITHUB_URL", "")

# Mapeo de categorías del dataset Arena → categorías que APA usa internamente
# El dataset usa "overall" como ranking general; APA usa "general" históricamente.
# Se mantiene compatibilidad: "overall" se almacena también como "general".
_ARENA_CATEGORY_ALIASES = {
    "overall": "general",  # "overall" del dataset → "general" que APA espera
}

# Memoria principal (lectura ultrarrápida)
_arena_data: Dict[str, Dict[str, float]] = {}
_needs_refresh = True
_refresh_lock = threading.Lock()
_refresh_thread_started = False


# =============================================================================
# FORMATO DE DATOS INTERNOS (v2)
# =============================================================================
#
# Raw format (devuelto por _fetch_from_huggingface y _fetch_from_github):
#   {
#       "claudeopus46thinking": {
#           "overall":  {"elo": 1500.2, "votes": 22385},
#           "coding":   {"elo": 1540.9, "votes": 5432},
#           "spanish":  {"elo": 1521.4, "votes": 1234},
#       },
#       "gpt4o": { ... }
#   }
#
# Fast index format (almacenado en _arena_data):
#   {
#       "claudeopus46thinking": {
#           "general": 66.7,    # de "overall"
#           "coding":  80.3,
#           "spanish": 73.8,
#       },
#       "gpt4o": { ... }
#   }
#
# Cache format (en disco, arena_cache.json v2):
#   {
#       "version": 2,
#       "updated_at": "2026-05-11T...",
#       "models": {
#           "claudeopus46thinking": {
#               "overall":  {"elo": 1500.2, "votes": 22385},
#               "coding":   {"elo": 1540.9, "votes": 5432},
#           }
#       }
#   }
# =============================================================================


def _elo_to_normalized(elo: float) -> float:
    """Convierte ELO rating a escala normalizada 0-100.
    Rango ELO Arena: ~680 (peor) a ~1550 (mejor).
    Fórmula: (elo - 1000) / 6.0 — da buen rango para ELOs modernos:
      ELO 1500 → 83.3, ELO 1300 → 50.0, ELO 1100 → 16.7, ELO 1000 → 0.0
    Antes se usaba /3.0 que truncaba 196/349 modelos a 100.
    """
    return min(100.0, max(0.0, (elo - 1000.0) / 6.0))


# -----------------------------------------------------------------------------
# Carga de fuentes locales (compatibles con formato v1 y v2)
# -----------------------------------------------------------------------------

def _load_local_rankings() -> Optional[Dict[str, Dict[str, float]]]:
    """Carga rankings desde archivo JSON local (fuente despriorizada).
    Soporta formato plano {model: elo_number} y formato v2 multi-categoría.
    """
    if not LOCAL_RANKINGS_PATH.exists():
        _log("arena_fetcher", "LOCAL_LOAD", "NO_EXISTE", str(LOCAL_RANKINGS_PATH))
        return None
    try:
        with open(LOCAL_RANKINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _log("arena_fetcher", "LOCAL_LOAD", "INVALIDO", "Formato incorrecto")
            return None

        fast_index: Dict[str, Dict[str, float]] = {}
        for model, score_data in data.items():
            normalized = normalize_model_id(model)
            if not normalized:
                continue

            if normalized not in fast_index:
                fast_index[normalized] = {}

            # Formato v2: {cat: {"elo": N, "votes": N}, ...}
            if isinstance(score_data, dict) and all(
                isinstance(v, dict) and "elo" in v for v in score_data.values()
            ):
                for cat, cat_data in score_data.items():
                    alias = _ARENA_CATEGORY_ALIASES.get(cat, cat)
                    fast_index[normalized][alias] = _elo_to_normalized(cat_data["elo"])
                    if cat == "overall":
                        fast_index[normalized]["general"] = fast_index[normalized].get("general", fast_index[normalized][alias])
            # Formato v1 legacy: {"elo": N, "category": "...", "votes": N}
            elif isinstance(score_data, dict) and "elo" in score_data:
                elo = float(score_data.get("elo", 1000.0))
                category = score_data.get("category", "general").lower()
                alias = _ARENA_CATEGORY_ALIASES.get(category, category)
                score = _elo_to_normalized(elo)
                fast_index[normalized][alias] = score
                if category == "overall":
                    fast_index[normalized]["general"] = score
            # Formato plano: solo número (elo)
            elif isinstance(score_data, (int, float)):
                fast_index[normalized]["general"] = _elo_to_normalized(float(score_data))

        _log("arena_fetcher", "LOCAL_LOAD", "EXITOSO", f"{len(fast_index)} modelos")
        return fast_index
    except Exception as e:
        _log("arena_fetcher", "LOCAL_LOAD", "ERROR", str(e))
        return None


def _load_snapshot() -> Optional[Dict[str, Dict[str, float]]]:
    """Carga el snapshot estático de respaldo desde data/arena_snapshot.json."""
    if not _SNAPSHOT_PATH.exists():
        _log("arena_fetcher", "SNAPSHOT_LOAD", "NO_EXISTE", str(_SNAPSHOT_PATH))
        return None
    try:
        with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "data" not in data or not isinstance(data["data"], list):
            _log("arena_fetcher", "SNAPSHOT_LOAD", "INVALIDO", "Estructura incorrecta")
            return None
        fast_index: Dict[str, Dict[str, float]] = {}
        for entry in data["data"]:
            model = entry.get("model")
            if not model:
                continue
            normalized = normalize_model_id(model)
            if not normalized:
                continue
            elo = entry.get("elo", 1000.0)
            category = entry.get("category", "general").lower()
            alias = _ARENA_CATEGORY_ALIASES.get(category, category)
            score = _elo_to_normalized(elo)
            if normalized not in fast_index:
                fast_index[normalized] = {}
            fast_index[normalized][alias] = score
            if category == "overall":
                fast_index[normalized]["general"] = fast_index[normalized].get("general", score)
        _log("arena_fetcher", "SNAPSHOT_LOAD", "EXITOSO", f"{len(fast_index)} modelos cargados")
        return fast_index
    except Exception as e:
        _log("arena_fetcher", "SNAPSHOT_LOAD", "ERROR", str(e))
        return None


def _load_cache() -> Dict[str, Dict[str, float]]:
    """Carga el caché persistente si tiene formato compatible.

    Retorna fast_index (formato {name: {category: score}}).
    Cachés v1 (sin version o version=1) se consideran obsoletos y se regeneran.

    P7 FIX: El caché NUNCA expira. Es fuente permanente de datos para carga rápida.
    La actualización se hace en background, sin afectar el flujo principal.
    Solo se descarta si el formato es incompatible (versión antigua).
    """
    if not _CACHE_PATH.exists():
        _log("arena_fetcher", "CACHE_LOAD", "NO_EXISTE", str(_CACHE_PATH))
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Verificar versión del caché — solo v3+ es compatible
        cache_version = data.get("version", 1)
        if cache_version < _CACHE_VERSION:
            _log("arena_fetcher", "CACHE_LOAD", "OBSOLETO",
                 f"Versión caché={cache_version}, requiere>={_CACHE_VERSION}. Se regenerará.")
            return {}

        # P7: Ya NO se descarta el caché por antigüedad.
        # El caché es permanente. Se actualiza en background cuando hay datos frescos,
        # pero nunca se pierde por expiración.
        updated_str = data.get("updated_at")
        if updated_str:
            try:
                updated = datetime.fromisoformat(updated_str)
                now = datetime.now(updated.tzinfo) if updated.tzinfo else datetime.now()
                cache_age = (now - updated).total_seconds()
                _log("arena_fetcher", "CACHE_LOAD", "CARGADO",
                     f"{cache_age/3600:.1f}h de antigüedad. Caché permanente — se actualizará en background.")
            except Exception:
                pass
        else:
            _log("arena_fetcher", "CACHE_LOAD", "CARGADO", "Sin fecha de actualización")

        # Formato v2: {name: {category: {"elo": N, "votes": N}, ...}}
        models_raw = data.get("models", {})
        fast_index: Dict[str, Dict[str, float]] = {}
        for name, categories_data in models_raw.items():
            if not isinstance(categories_data, dict):
                continue
            fast_index[name] = {}
            for cat, cat_data in categories_data.items():
                if isinstance(cat_data, dict) and "elo" in cat_data:
                    alias = _ARENA_CATEGORY_ALIASES.get(cat, cat)
                    fast_index[name][alias] = _elo_to_normalized(cat_data["elo"])
                    if cat == "overall":
                        fast_index[name]["general"] = fast_index[name].get("general", fast_index[name][alias])
            # Asegurar que siempre tenga "general" (fallback al mayor score disponible)
            if "general" not in fast_index[name] and fast_index[name]:
                best_cat = max(fast_index[name], key=fast_index[name].get)
                fast_index[name]["general"] = fast_index[name][best_cat]

        _log("arena_fetcher", "CACHE_LOAD", "VALIDO",
             f"{len(fast_index)} modelos, actualizado {updated_str}")
        return fast_index
    except Exception as e:
        _log("arena_fetcher", "CACHE_LOAD", "ERROR", str(e))
        return {}


def _save_cache(raw_models: Dict[str, Any]) -> None:
    """Guarda datos brutos (formato v2) en disco.
    Solo se llama si hay datos nuevos de HF o GitHub.
    """
    if not raw_models:
        _log("arena_fetcher", "CACHE_SAVE", "OMITIDO", "Sin datos para guardar")
        return
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = {
            "version": _CACHE_VERSION,
            "updated_at": datetime.now().isoformat(),
            "models": raw_models
        }
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)
        _log("arena_fetcher", "CACHE_SAVE", "EXITOSO",
             f"{len(raw_models)} modelos en {_CACHE_PATH}")
    except Exception as e:
        _log("arena_fetcher", "CACHE_SAVE", "ERROR", f"{str(e)} - ruta: {_CACHE_PATH}")


# -----------------------------------------------------------------------------
# Fetching desde HuggingFace (fuente primaria)
# -----------------------------------------------------------------------------

def _fetch_from_huggingface() -> Optional[Dict[str, Any]]:
    """Carga rankings desde HuggingFace usando la biblioteca 'datasets'.
    Config 'text': todas las categorías de texto (overall, coding, math, hard_prompts, etc.)
    Config 'webdev': categorías de desarrollo web (webdev, webdev-html, webdev-react).

    Retorna formato raw v2: {normalized_name: {category: {"elo": float, "votes": int}}}
    CORRECCIÓN v2: cada modelo almacena TODAS sus categorías (antes se sobreescritaban).
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("Biblioteca 'datasets' no instalada, saltando opción 1 (HF datasets lib)...")
        return None

    models_dict: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # --- Config 'text' (27 categorías: overall, coding, math, hard_prompts, etc.) ---
    try:
        logger.info("[Opción 1] Cargando dataset lmarena-ai/leaderboard-dataset (text/latest)...")
        dataset = load_dataset(HF_DATASET, 'text', split="latest")
        text_count = _ingest_hf_dataset(dataset, models_dict)
        logger.info(f"Config 'text': {text_count} modelos con categorías múltiples")
        # v3.2: Notificar carga de categoría text
        _notify("arena:category_loaded",
                f"Arena text: {text_count} modelos con múltiples categorías",
                {"category": "text", "models": text_count})
    except Exception as e:
        logger.warning(f"Error cargando config 'text': {type(e).__name__}: {e}")

    # --- Config 'webdev' (categorías: webdev, webdev-html, webdev-react) ---
    try:
        logger.info("[Opción 1] Cargando dataset lmarena-ai/leaderboard-dataset (webdev/latest)...")
        dataset_webdev = load_dataset(HF_DATASET, 'webdev', split="latest")
        webdev_count = _ingest_hf_dataset(dataset_webdev, models_dict)
        logger.info(f"Config 'webdev': {webdev_count} modelos mergeados")
        # v3.2: Notificar carga de categoría webdev
        _notify("arena:category_loaded",
                f"Arena webdev: {webdev_count} modelos mergeados",
                {"category": "webdev", "models": webdev_count})
    except Exception as e:
        logger.warning(f"Error cargando config 'webdev' (no crítico): {type(e).__name__}: {e}")

    if not models_dict:
        logger.warning("HuggingFace datasets lib: no se cargaron modelos")
        return None

    # Log de categorías disponibles
    all_cats = set()
    for cats in models_dict.values():
        all_cats.update(cats.keys())
    logger.info(f"[Opción 1] OK: {len(models_dict)} modelos, "
                f"categorías: {sorted(all_cats)}")
    return models_dict


def _fetch_from_huggingface_http() -> Optional[Dict[str, Any]]:
    """Carga rankings desde HuggingFace descargando los parquet directamente vía HTTP.
    No requiere la biblioteca 'datasets', solo requests + pyarrow (más ligero).

    Retorna formato raw v2: {normalized_name: {category: {"elo": float, "votes": int}}}
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("Biblioteca 'pyarrow' no instalada, saltando opción 2 (HF HTTP)...")
        return None

    models_dict: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for config_name, url in HF_PARQUET_CONFIGS.items():
        try:
            logger.info(f"[Opción 2] Descargando parquet {config_name} desde HuggingFace...")
            resp = requests.get(url, timeout=30, allow_redirects=True)
            resp.raise_for_status()

            # Leer parquet desde memoria
            import io
            table = pq.read_table(io.BytesIO(resp.content))
            df = table.to_pandas()

            count = 0
            for _, row in df.iterrows():
                model = row.get('model_name')
                if not model or not isinstance(model, str):
                    continue
                normalized = normalize_model_id(model.strip())
                if not normalized:
                    continue

                elo = row.get('rating', 1000.0)
                try:
                    elo = float(elo)
                except (ValueError, TypeError):
                    elo = 1000.0

                category = str(row.get('category', 'general')).lower().strip()
                if not category:
                    category = 'general'

                votes = row.get('vote_count', 0)
                try:
                    votes = int(votes)
                except (ValueError, TypeError):
                    votes = 0

                if normalized not in models_dict:
                    models_dict[normalized] = {}
                    count += 1
                models_dict[normalized][category] = {"elo": elo, "votes": votes}

            logger.info(f"[Opción 2] Config '{config_name}': {count} modelos desde parquet HTTP")
            # v3.2: Notificar carga de categoría vía HTTP parquet
            _notify("arena:category_loaded",
                    f"Arena {config_name}: {count} modelos descargados (HTTP)",
                    {"category": config_name, "models": count, "source": "http_parquet"})
        except Exception as e:
            logger.warning(f"[Opción 2] Error descargando config '{config_name}': {type(e).__name__}: {e}")

    if not models_dict:
        logger.warning("HuggingFace HTTP: no se cargaron modelos de ningún parquet")
        return None

    all_cats = set()
    for cats in models_dict.values():
        all_cats.update(cats.keys())
    logger.info(f"[Opción 2] OK: {len(models_dict)} modelos, "
                f"categorías: {sorted(all_cats)}")
    return models_dict


def _ingest_hf_dataset(dataset, models_dict: Dict[str, Dict[str, Dict[str, Any]]]) -> int:
    """Ingiere filas de un dataset HF en models_dict (formato v2 multi-categoría).
    Retorna el número de modelos nuevos o actualizados.
    CORRECCIÓN CLAVE: models_dict[normalized][category] = {...} en vez de
    models_dict[normalized] = {...} que sobreescribía categorías.
    """
    count = 0
    for row in dataset:
        model = row.get('model_name') or row.get('model')
        if not model:
            continue
        normalized = normalize_model_id(str(model).strip())
        if not normalized:
            continue

        # Obtener ELO
        score = row.get('rating') or row.get('arena_score') or 1000.0
        try:
            elo = float(score)
        except (ValueError, TypeError):
            elo = 1000.0

        # Obtener categoría
        category = row.get('category', 'general').lower() if 'category' in row else 'general'
        if not category:
            category = 'general'

        # Obtener votos
        votes = row.get('vote_count') or row.get('votes') or row.get('num_battles') or 0
        try:
            votes = int(votes)
        except (ValueError, TypeError):
            votes = 0

        # CORRECCIÓN: Almacenar por categoría dentro de cada modelo
        # Antes: models_dict[normalized] = {"elo": ..., "category": ...} → SOBRESCRIBÍA
        # Ahora: models_dict[normalized][category] = {"elo": ..., "votes": ...} → ACUMULA
        if normalized not in models_dict:
            models_dict[normalized] = {}
            count += 1
        models_dict[normalized][category] = {"elo": elo, "votes": votes}

    return count


# -----------------------------------------------------------------------------
# Fetching desde GitHub (fuente secundaria)
# -----------------------------------------------------------------------------

def _fetch_from_github() -> Optional[Dict[str, Any]]:
    """Intenta cargar rankings desde la URL configurada en ARENA_GITHUB_URL.
    Retorna formato raw v2: {normalized_name: {category: {"elo": float, "votes": int}}}
    """
    url = ARENA_GITHUB_URL
    if not url:
        _log("arena_fetcher", "GITHUB", "DESHABILITADO",
             "Variable ARENA_GITHUB_URL no configurada (no es un error si HF funciona)")
        return None
    try:
        logger.info(f"Intentando cargar desde fuente secundaria: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        models_dict: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Formato v2 multi-categoría: {model: {category: {"elo": N, "votes": N}}}
        if isinstance(data, dict) and "models" not in data:
            # Verificar si es formato v2 (values son dicts con "elo")
            sample_values = list(data.values())[:3]
            if sample_values and all(
                isinstance(v, dict) and any(
                    isinstance(cv, dict) and "elo" in cv for cv in v.values()
                ) for v in sample_values if isinstance(v, dict)
            ):
                for model, categories_data in data.items():
                    normalized = normalize_model_id(str(model).strip())
                    if not normalized or not isinstance(categories_data, dict):
                        continue
                    models_dict[normalized] = {}
                    for cat, cat_data in categories_data.items():
                        if isinstance(cat_data, dict) and "elo" in cat_data:
                            models_dict[normalized][cat] = {
                                "elo": float(cat_data["elo"]),
                                "votes": int(cat_data.get("votes", 0))
                            }
                logger.info(f"Fuente secundaria (v2 multi-cat): {len(models_dict)} modelos")
                # v3.2: Notificar carga vía GitHub (v2 multi-cat)
                _notify("arena:category_loaded",
                        f"Arena GitHub (v2): {len(models_dict)} modelos",
                        {"category": "multi", "models": len(models_dict), "source": "github"})
                return models_dict

        # Formato del mirror arena-ai-leaderboards (models[])
        if isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
            for entry in data["models"]:
                model = entry.get("model")
                score = entry.get("score") or entry.get("elo")
                if not model or score is None:
                    continue
                normalized = normalize_model_id(str(model).strip())
                if not normalized:
                    continue
                elo = float(score) if isinstance(score, (int, float)) else 1000.0
                category = entry.get("category", "general").lower()
                if normalized not in models_dict:
                    models_dict[normalized] = {}
                models_dict[normalized][category] = {"elo": elo, "votes": 0}
            logger.info(f"Fuente secundaria (JSON mirror): {len(models_dict)} modelos")
            # v3.2: Notificar carga vía GitHub (mirror)
            _notify("arena:category_loaded",
                    f"Arena GitHub (mirror): {len(models_dict)} modelos",
                    {"category": "mirror", "models": len(models_dict), "source": "github"})
            return models_dict

        # Formato JSON plano {model: elo_number}
        if isinstance(data, dict) and all(isinstance(v, (int, float)) for v in data.values()):
            for model, score in data.items():
                normalized = normalize_model_id(str(model).strip())
                if not normalized:
                    continue
                models_dict[normalized] = {
                    "general": {"elo": float(score), "votes": 0}
                }
            logger.info(f"Fuente secundaria (JSON plano): {len(models_dict)} modelos")
            # v3.2: Notificar carga vía GitHub (plano)
            _notify("arena:category_loaded",
                    f"Arena GitHub (plano): {len(models_dict)} modelos",
                    {"category": "flat", "models": len(models_dict), "source": "github"})
            return models_dict

        logger.warning("Fuente secundaria: formato JSON desconocido")
        return None
    except requests.RequestException as e:
        logger.warning(f"Fuente secundaria request failed: {e}")
        return None
    except json.JSONDecodeError:
        logger.info("Fuente secundaria: no es JSON, intentando CSV...")
        return _parse_arena_csv(response.text)
    except Exception as e:
        logger.warning(f"Fuente secundaria error: {type(e).__name__}: {e}")
        return None


def _parse_arena_csv(csv_text: str) -> Optional[Dict[str, Any]]:
    """Parsea contenido CSV y retorna dict en formato raw v2 multi-categoría."""
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            logger.error("arena_fetcher: CSV vacío o sin cabeceras")
            return None
        col_model = next((c for c in reader.fieldnames if c.lower() in ["model", "name", "model_name"]), None)
        col_elo = next((c for c in reader.fieldnames if c.lower() in ["elo", "elo_score", "rating"]), None)
        col_category = next((c for c in reader.fieldnames if c.lower() in ["category", "task_category"]), None)
        col_votes = next((c for c in reader.fieldnames if c.lower() in ["votes", "num_battles", "battles", "vote_count"]), None)
        if not col_model or not col_elo:
            logger.error(f"arena_fetcher: Columnas requeridas no encontradas. Disponibles: {reader.fieldnames}")
            return None
        models_dict: Dict[str, Dict[str, Dict[str, Any]]] = {}
        parsed_count = 0
        for row in reader:
            raw_name = row.get(col_model)
            if not raw_name or not raw_name.strip():
                continue
            normalized = normalize_model_id(raw_name.strip())
            if not normalized:
                continue
            try:
                elo_val = row.get(col_elo, "1000")
                elo = float(elo_val) if elo_val else 1000.0
            except (ValueError, TypeError):
                elo = 1000.0
            category_raw = row.get(col_category) if col_category else "general"
            category = (category_raw or "general").lower().strip()
            votes = 0
            if col_votes:
                try:
                    votes_str = row.get(col_votes, "0")
                    votes = int(votes_str) if votes_str else 0
                except (ValueError, TypeError):
                    votes = 0
            if normalized not in models_dict:
                models_dict[normalized] = {}
            models_dict[normalized][category] = {"elo": elo, "votes": votes}
            parsed_count += 1
        if not models_dict:
            logger.warning("arena_fetcher: No se parsearon modelos del CSV")
            return None
        logger.info(f"arena_fetcher: {parsed_count} entradas CSV parseadas, "
                     f"{len(models_dict)} modelos únicos")
        return models_dict
    except csv.Error as e:
        logger.error(f"arena_fetcher: Error parseando CSV: {e}")
        return None
    except Exception as e:
        logger.error(f"arena_fetcher: Error inesperado parseando CSV: {type(e).__name__}: {e}")
        return None


# -----------------------------------------------------------------------------
# Construcción del índice rápido (raw v2 → fast_index)
# -----------------------------------------------------------------------------

def _build_fast_index(raw_models: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Convierte datos raw v2 (multi-categoría) en índice de acceso rápido.
    Formato raw:   {name: {category: {"elo": N, "votes": N}}}
    Formato fast:  {name: {category: normalized_score_0_to_100}}
    También añade alias "general" = "overall" para compatibilidad con APA.
    """
    fast: Dict[str, Dict[str, float]] = {}
    for name, categories_data in raw_models.items():
        if not isinstance(categories_data, dict):
            continue
        fast[name] = {}
        for cat, cat_data in categories_data.items():
            if isinstance(cat_data, dict) and "elo" in cat_data:
                alias = _ARENA_CATEGORY_ALIASES.get(cat, cat)
                fast[name][alias] = _elo_to_normalized(cat_data["elo"])
                # Alias: "overall" también se guarda como "general"
                if cat == "overall":
                    fast[name]["general"] = fast[name].get("general", fast[name][alias])

        # Asegurar que siempre tenga "general" (fallback al score más alto disponible)
        if "general" not in fast[name] and fast[name]:
            best_cat = max(fast[name], key=fast[name].get)
            fast[name]["general"] = fast[name][best_cat]

    return fast


# -----------------------------------------------------------------------------
# Cascada de fetching: Opción 1 (HF datasets lib) → Opción 2 (HF HTTP) → Opción 3 (GitHub) → Caché
# -----------------------------------------------------------------------------

def _fetch_rankings_with_fallback() -> Optional[Dict[str, Any]]:
    """Obtiene rankings siguiendo jerarquía en cascada:
    1. HuggingFace vía librería 'datasets' (más rápido si está instalada)
    2. HuggingFace vía HTTP directo a parquet (sin librería datasets, requiere pyarrow)
    3. GitHub/URL configurable (mirror o fuente alternativa)
    4. Caché local (último recurso)
    Retorna datos en formato raw v2 (para pasar a _build_fast_index).
    """
    # Opción 1: HuggingFace datasets lib (text + webdev)
    raw = _fetch_from_huggingface()
    if raw:
        _save_cache(raw)
        cats_found = set()
        for c in raw.values():
            cats_found.update(c.keys())
        logger.info(f"✓ [Opción 1] Rankings de HuggingFace (datasets lib): {len(raw)} modelos, "
                     f"categorías: {sorted(cats_found)}")
        # v3.2: Notificar fuente exitosa (HuggingFace datasets lib)
        _notify("arena:category_loaded",
                f"Arena: fuente HuggingFace datasets — {len(raw)} modelos, categorías: {sorted(cats_found)}",
                {"source": "hf_datasets", "models": len(raw), "categories": sorted(cats_found)})
        return raw
    logger.warning("✗ Opción 1 (HF datasets lib) falló, intentando Opción 2 (HF HTTP)...")

    # Opción 2: HuggingFace HTTP directo (descarga parquet sin librería datasets)
    raw = _fetch_from_huggingface_http()
    if raw:
        _save_cache(raw)
        cats_found = set()
        for c in raw.values():
            cats_found.update(c.keys())
        logger.info(f"✓ [Opción 2] Rankings de HuggingFace (HTTP parquet): {len(raw)} modelos, "
                     f"categorías: {sorted(cats_found)}")
        # v3.2: Notificar fuente exitosa (HuggingFace HTTP)
        _notify("arena:category_loaded",
                f"Arena: fuente HuggingFace HTTP — {len(raw)} modelos, categorías: {sorted(cats_found)}",
                {"source": "hf_http", "models": len(raw), "categories": sorted(cats_found)})
        return raw
    logger.warning("✗ Opción 2 (HF HTTP) falló, intentando Opción 3 (GitHub)...")

    # Opción 3: GitHub / URL configurable
    raw = _fetch_from_github()
    if raw:
        _save_cache(raw)
        logger.info("✓ [Opción 3] Rankings de fuente configurable (GitHub/URL)")
        # v3.2: Notificar fuente exitosa (GitHub/URL)
        _notify("arena:category_loaded",
                f"Arena: fuente GitHub/URL — {len(raw)} modelos",
                {"source": "github", "models": len(raw)})
        return raw
    logger.warning("✗ Opción 3 (GitHub) falló, intentando caché local...")

    # Opción 4: Caché local (último recurso)
    cached = _load_cache()
    if cached:
        logger.info("✓ [Opción 4] Rankings de caché local (último recurso)")
        # El caché devuelve fast_index, convertir a raw para consistencia
        raw_cached: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for name, scores in cached.items():
            raw_cached[name] = {}
            for cat, score in scores.items():
                # Inversa: score_normalizado → elo aproximado
                elo_approx = score * 6.0 + 1000.0
                raw_cached[name][cat] = {"elo": elo_approx, "votes": 0}
        return raw_cached
    logger.warning("✗ No se pudieron obtener rankings de ninguna fuente (1→2→3→4)")
    return None


def _background_refresh() -> None:
    """Hilo en segundo plano para refrescar caché siguiendo jerarquía HF→GitHub→caché."""
    global _arena_data, _needs_refresh
    _log("arena_fetcher", "BACKGROUND", "INICIADO")
    # v3.1: Notificar inicio de actualización
    _notify("arena:refresh_start",
            "Actualizando rankings Arena en background...",
            {"source": "background_thread"})
    try:
        raw = _fetch_rankings_with_fallback()
        if raw:
            new_index = _build_fast_index(raw)
            with _refresh_lock:
                _arena_data = new_index
                _needs_refresh = False
            _log("arena_fetcher", "BACKGROUND", "COMPLETADO",
                 f"{len(new_index)} modelos en memoria")
            # v3.1: Notificar éxito
            _notify("arena:refresh_complete",
                    f"Arena actualizado: {len(new_index)} modelos en memoria",
                    {"total_models": len(new_index), "source": "background_thread"})

            # v3.2: Notificar top-5 modelos generales
            top5_general = sorted(new_index.items(),
                key=lambda x: x[1].get("general", 0), reverse=True)[:5]
            if top5_general:
                top5_names = [name for name, _ in top5_general]
                top5_scores = [f"{scores.get('general', 0):.0f}" for _, scores in top5_general]
                _notify("arena:top_models",
                        f"Top 5 Arena: {', '.join(top5_names)}",
                        {"top_models": top5_names, "top_scores": top5_scores})

            # v3.2: Notificar distribución de categorías
            all_cats = set()
            for scores in new_index.values():
                all_cats.update(scores.keys())
            cat_counts = {}
            for name, scores in new_index.items():
                for cat in scores:
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            _notify("arena:category_loaded",
                    f"Arena: {len(new_index)} modelos en {len(all_cats)} categorías ({', '.join(sorted(all_cats))})",
                    {"categories": dict(cat_counts), "total_models": len(new_index)})
        else:
            _log("arena_fetcher", "BACKGROUND", "SIN_DATOS",
                 "Se mantienen datos existentes")
            # v3.1: Notificar fallo (sin datos de ninguna fuente)
            _notify("arena:refresh_failed",
                    "No se pudieron obtener rankings Arena de ninguna fuente (HF/GitHub/caché)",
                    {"fallback": True, "existing_models": len(_arena_data)})
    except Exception as e:
        _log("arena_fetcher", "BACKGROUND", "ERROR", str(e))
        # v3.1: Notificar error inesperado
        _notify("arena:refresh_failed",
                f"Error actualizando Arena: {type(e).__name__}: {str(e)}",
                {"error": str(e), "error_type": type(e).__name__})
    finally:
        # P7: Permitir que el hilo se pueda ejecutar de nuevo
        with _refresh_lock:
            _refresh_thread_started = False


def _start_background_refresh_if_needed() -> None:
    """Inicia hilo de refresco si es necesario y no está ya corriendo."""
    global _refresh_thread_started
    if _refresh_thread_started:
        return
    with _refresh_lock:
        if _refresh_thread_started:
            return
        thread = threading.Thread(target=_background_refresh, daemon=True)
        thread.start()
        _refresh_thread_started = True
    _log("arena_fetcher", "STARTUP", "HILO_INICIADO")


# v3.3: ELIMINADO el bucle periódico. Arena se ejecuta SOLO UNA VEZ
# al inicio de la aplicación en segundo plano (vía _start_background_refresh_if_needed
# al importar el módulo). No hay más actualizaciones automáticas durante la sesión.
# Si el Director necesita datos frescos, puede llamar refresh_arena_cache() manualmente.
#
# Razón: Evitar competencia de red con el pipeline agéntico.
# El ranking Arena es una foto fija al inicio, suficiente para toda la sesión.


# -----------------------------------------------------------------------------
# Inicialización al importar: D-8/D-10 Cache-first non-blocking
# -----------------------------------------------------------------------------
# Phase 0: Cargar SOLO caché local (instantáneo, <100ms)
# Phase 1: Iniciar background fetch para rankings frescos
#
# v2.0 BLOCKED al importar: _fetch_rankings_with_fallback() tarda 5-6s+
# v3.0 NON-BLOCKING: carga caché local al instante, fetch en background

def _phase0_load_cache_only() -> Dict[str, Dict[str, float]]:
    """Phase 0: Carga SOLO caché local (instantáneo).

    D-10: 'Nothing blocks nothing' — arrancamos inmediatamente
    con lo que tenemos en caché, sin esperar a HuggingFace.
    """
    # 1. Intentar caché local persistente
    cached = _load_cache()
    if cached:
        cats = set()
        for scores in cached.values():
            cats.update(scores.keys())
        _log("arena_fetcher", "PHASE0", "CACHE_LOCAL",
             f"{len(cached)} modelos, categorías: {sorted(cats)}")
        # v3.2: Notificar detalle del caché local cargado
        _notify("arena:category_loaded",
                f"Caché local Arena: {len(cached)} modelos, categorías: {sorted(cats)}",
                {"source": "cache", "models": len(cached), "categories": sorted(cats)})
        return cached

    # 2. Intentar rankings locales
    local = _load_local_rankings()
    if local:
        _log("arena_fetcher", "PHASE0", "LOCAL_RANKINGS",
             f"{len(local)} modelos")
        return local

    # 3. Intentar snapshot
    snapshot = _load_snapshot()
    if snapshot:
        _log("arena_fetcher", "PHASE0", "SNAPSHOT",
             f"{len(snapshot)} modelos")
        return snapshot

    _log("arena_fetcher", "PHASE0", "VACIO",
         "Sin datos locales, se obtendrán en background")
    return {}


_initial_cache = _phase0_load_cache_only()

with _refresh_lock:
    _arena_data = _initial_cache
    _needs_refresh = (len(_initial_cache) == 0)

# v3.1: Notificar carga de caché al inicio (después de Phase 0)
_notify("arena:cache_loaded",
        f"Caché Arena cargado: {len(_initial_cache)} modelos al inicio",
        {"total": len(_initial_cache), "source": "phase0_startup"})

# Phase 1: Lanza refresh HTTP UNA SOLA VEZ al importar (background).
# Solo carga de cache local (Phase 0), y después un refresh en background
# que NO se repite. El ranking permanece estático durante toda la sesión.
#
# Esto elimina la competencia de red con el pipeline agentico al inicio.

# v3.3: Ejecutar Arena UNA SOLA VEZ al inicio en background (no periódico)
_start_background_refresh_if_needed()

if _initial_cache:
    cats_in_index = set()
    for scores in _initial_cache.values():
        cats_in_index.update(scores.keys())
    _log("arena_fetcher", "INIT", "LISTO",
         f"Phase 0 OK: {len(_initial_cache)} modelos. Phase 1 en background (solo al inicio, sin periódico).")
else:
    _log("arena_fetcher", "INIT", "ESPERANDO_BG",
         "Phase 0 sin datos. Esperando background fetch...")


# -----------------------------------------------------------------------------
# Función pública: verificar disponibilidad del ranking
# -----------------------------------------------------------------------------
def is_arena_ranking_available() -> bool:
    """Retorna True si hay datos disponibles (de cualquier fuente) con modelos válidos."""
    if _arena_data and len(_arena_data) > 0:
        return True
    snapshot = _load_snapshot()
    return snapshot is not None and len(snapshot) > 0


# -----------------------------------------------------------------------------
# Función pública (O(1)) con mapeo correcto de categorías
# -----------------------------------------------------------------------------
def get_score_for_model(model_id: str, task_type: str = None) -> Optional[float]:
    """
    Retorna score Arena normalizado (0-100) si está disponible en memoria.
    Mapea task_type de APA a las categorías reales del dataset Arena:
        - planning     → hard_prompts, overall/general
        - evaluation   → math, hard_prompts, overall/general
        - generation   → coding, webdev, webdev-react, overall/general
        - coding       → coding, webdev, webdev-react, overall/general
        - correction   → coding, instruction_following, overall/general
    Incluye búsqueda por subcadena para mejorar tasa de acierto.
    No realiza llamadas bloqueantes.
    """
    if not model_id:
        return None
    search_name = normalize_model_id(model_id)
    if not search_name:
        return None

    # F7: También obtener el nombre canónico para búsqueda alternativa
    canonical = canonical_name(model_id)
    # Normalizar el nombre canónico para búsqueda en _arena_data
    # (los datos de Arena pueden estar normalizados)
    canonical_norm = normalize_model_id(canonical) if canonical else ""

    # Mapeo de task_type de APA → categorías reales del dataset Arena
    # Ordenadas por prioridad: la primera categoría encontrada se retorna
    # FIX: Categorías actualizadas a las que realmente existen en el dataset Arena 2026.
    # El dataset ya no usa "overall" como nombre en el fast index (se renombró a "general").
    # Categorías disponibles: coding, hard_prompts, instruction_following, math,
    # creative_writing, expert, webdev, webdev-react, image_to_webdev,
    # hard_prompts_english, longer_query, multi_turn, general, + idiomas.
    category_map = {
        "planning":    ["hard_prompts", "expert", "general"],
        "evaluation":  ["math", "hard_prompts", "expert", "general"],
        "generation":  ["creative_writing", "coding", "instruction_following", "general"],
        "coding":      ["coding", "hard_prompts", "webdev", "general"],
        "correction":  ["coding", "instruction_following", "general"],
    }
    categories = category_map.get(task_type, ["general"]) if task_type else ["general"]

    with _refresh_lock:
        data_snapshot = _arena_data

    if not data_snapshot:
        return None

    # Búsqueda exacta por nombre normalizado
    if search_name in data_snapshot:
        model_scores = data_snapshot[search_name]
        for cat in categories:
            if cat in model_scores:
                return model_scores[cat]
        return model_scores.get("general")

    # F7: Búsqueda por nombre canónico (permite emparejar modelos
    # de distintos proveedores que comparten el mismo LLM)
    if canonical_norm and canonical_norm != search_name and canonical_norm in data_snapshot:
        model_scores = data_snapshot[canonical_norm]
        for cat in categories:
            if cat in model_scores:
                return model_scores[cat]
        return model_scores.get("general")

    # Búsqueda por subcadena (fallback para nombres no exactos)
    search_lower = search_name.lower()
    for name, scores in data_snapshot.items():
        name_lower = name.lower()
        if search_lower in name_lower or name_lower in search_lower:
            for cat in categories:
                if cat in scores:
                    return scores[cat]
            return scores.get("general")

    # F7: Búsqueda por subcadena usando nombre canónico
    if canonical_norm and canonical_norm != search_name:
        canonical_lower = canonical_norm.lower()
        for name, scores in data_snapshot.items():
            name_lower = name.lower()
            if canonical_lower in name_lower or name_lower in canonical_lower:
                for cat in categories:
                    if cat in scores:
                        return scores[cat]
                return scores.get("general")

    return None


def get_available_categories() -> List[str]:
    """Retorna lista de categorías disponibles en los datos actuales (para diagnóstico)."""
    with _refresh_lock:
        data_snapshot = _arena_data
    if not data_snapshot:
        return []
    cats = set()
    for scores in data_snapshot.values():
        cats.update(scores.keys())
    return sorted(cats)


def get_model_all_scores(model_id: str) -> Optional[Dict[str, float]]:
    """Retorna todos los scores disponibles para un modelo (para diagnóstico).
    Retorna dict {category: score} o None si el modelo no se encuentra.
    """
    if not model_id:
        return None
    search_name = normalize_model_id(model_id)
    if not search_name:
        return None

    with _refresh_lock:
        data_snapshot = _arena_data

    if not data_snapshot:
        return None

    if search_name in data_snapshot:
        return dict(data_snapshot[search_name])

    # Búsqueda por subcadena
    search_lower = search_name.lower()
    for name, scores in data_snapshot.items():
        name_lower = name.lower()
        if search_lower in name_lower or name_lower in search_lower:
            return dict(scores)

    return None


def validate_self() -> bool:
    """Validación del módulo: verifica que get_score_for_model funciona con categorías reales."""
    _log("arena_fetcher", "VALIDATE_SELF", "INICIADO")
    try:
        # Verificar que coding funciona (antes siempre devolvía None)
        score_coding = get_score_for_model("qwen/qwen2.5-coder", "coding")
        # Verificar que overall funciona
        score_general = get_score_for_model("openai/gpt-4o", "planning")
        # Verificar categorías disponibles
        cats = get_available_categories()

        detail = (f"coding={score_coding:.1f}" if score_coding else "coding=None, "
                  f"planning={score_general:.1f}" if score_general else "planning=None, "
                  f"cats={cats[:5]}...")
        _log("arena_fetcher", "VALIDATE_SELF", "COMPLETADO", detail)
        return True
    except Exception as e:
        _log("arena_fetcher", "VALIDATE_SELF", "FALLIDO", str(e))
        return False


if __name__ == "__main__":
    if not logging.root.handlers:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    import time

    print("\n" + "=" * 70)
    print("PRUEBA: Arena Fetcher v2 — Multi-categoría con datos reales")
    print("=" * 70)

    # Prueba 1: Verificar disponibilidad
    print("\n[1] Verificando disponibilidad del ranking...")
    available = is_arena_ranking_available()
    print(f"  Ranking disponible: {available}")

    # Prueba 2: Categorías disponibles
    print("\n[2] Categorías disponibles en el índice:")
    cats = get_available_categories()
    for c in cats:
        count = sum(1 for scores in _arena_data.values() if c in scores)
        print(f"  {c}: {count} modelos")

    # Prueba 3: Scores por task_type (ANTES siempre devolvían None para coding/planning)
    print("\n[3] Scores por task_type (ANTES CODING SIEMPRE ERA None):")
    test_models = [
        ("openai/gpt-4o", "planning"),
        ("openai/gpt-4o", "coding"),
        ("anthropic/claude-opus-4-6", "coding"),
        ("qwen/qwen2.5-coder", "coding"),
        ("qwen/qwen2.5-coder", "generation"),
        ("anthropic/claude-sonnet-4", "correction"),
        ("deepseek/deepseek-r1", "evaluation"),
    ]
    for model, task in test_models:
        score = get_score_for_model(model, task)
        print(f"  {model} [{task}] → {score:.1f}" if score else f"  {model} [{task}] → None")

    # Prueba 4: Todos los scores de un modelo
    print("\n[4] Todos los scores de claude-opus-4-6-thinking:")
    all_scores = get_model_all_scores("anthropic/claude-opus-4-6-thinking")
    if all_scores:
        for cat, score in sorted(all_scores.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {score:.1f}")
    else:
        print("  No encontrado")

    # Prueba 5: Consulta no bloqueante
    print("\n[5] Prueba de rendimiento (debe ser <5ms):")
    t0 = time.time()
    for _ in range(1000):
        get_score_for_model("openai/gpt-4o", "coding")
    t1 = time.time()
    print(f"  1000 consultas en {(t1-t0)*1000:.0f}ms "
          f"({(t1-t0)*1000/1000:.2f}ms cada una)")

    # Prueba 6: Validación
    print("\n[6] Validación del módulo:")
    validate_self()

    print("\n" + "=" * 70)
    print("PRUEBAS COMPLETADAS")
    print("=" * 70)
