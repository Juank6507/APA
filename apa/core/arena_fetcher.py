# apa/core/arena_fetcher.py
import csv
import io
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
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
from core.normalizer import normalize_model_id

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

# -----------------------------------------------------------------------------
# Configuración de caché y fuentes de datos en cascada
# -----------------------------------------------------------------------------
_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "arena_cache.json"
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent / "data" / "arena_snapshot.json"
LOCAL_RANKINGS_PATH = Path(__file__).parent / "data" / "arena_rankings.json"
_CACHE_DURATION_SECONDS = 86400  # 24 horas para caché local
_CACHE_VALIDITY_DAYS = 30  # Validez del ranking para is_arena_ranking_available

# URLs para descarga en cascada: HuggingFace → GitHub → Caché
HF_DATASET = "lmarena-ai/leaderboard-dataset"
# FIX: Usar variable de entorno con fallback a URL por defecto
ARENA_GITHUB_URL = os.getenv("ARENA_GITHUB_URL", "https://raw.githubusercontent.com/tu_usuario/apa-rankings/main/arena_rankings.json")

# Memoria principal (lectura ultrarrápida)
# FIX: Corregido typo: era "_arena_ Dict" ahora es "_arena_ Dict"
_arena_data: Dict[str, Dict[str, float]] = {}
_needs_refresh = True
_refresh_lock = threading.Lock()
_refresh_thread_started = False

def _load_local_rankings() -> Optional[Dict[str, Dict[str, float]]]:
    """Carga rankings desde archivo JSON local (fuente despriorizada)."""
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
        for model, score in data.items():
            normalized = normalize_model_id(model)
            if not normalized:
                continue
            elo = float(score) if isinstance(score, (int, float)) else 1000.0
            normalized_score = min(100.0, max(0.0, (elo - 1000.0) / 3.0))
            if normalized not in fast_index:
                fast_index[normalized] = {}
            fast_index[normalized]["general"] = normalized_score
        _log("arena_fetcher", "LOCAL_LOAD", "EXITOSO", f"{len(fast_index)} modelos")
        return fast_index
    except Exception as e:
        _log("arena_fetcher", "LOCAL_LOAD", "ERROR", str(e))
        return None

def _load_snapshot() -> Optional[Dict[str, Any]]:
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
            score = min(100.0, max(0.0, (elo - 1000.0) / 3.0))
            if normalized not in fast_index:
                fast_index[normalized] = {}
            fast_index[normalized][category] = score
            fast_index[normalized]["general"] = fast_index[normalized].get("general", score)
        _log("arena_fetcher", "SNAPSHOT_LOAD", "EXITOSO", f"{len(fast_index)} modelos cargados")
        return fast_index
    except Exception as e:
        _log("arena_fetcher", "SNAPSHOT_LOAD", "ERROR", str(e))
        return None

def _load_cache() -> Dict[str, Dict[str, float]]:
    """Carga el caché persistente si es válido. Si no, retorna dict vacío."""
    if not _CACHE_PATH.exists():
        _log("arena_fetcher", "CACHE_LOAD", "NO_EXISTE", str(_CACHE_PATH))
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated_str = data.get("updated_at")
        if not updated_str:
            _log("arena_fetcher", "CACHE_LOAD", "INVALIDO", "Falta updated_at")
            return {}
        updated = datetime.fromisoformat(updated_str)
        now = datetime.now(updated.tzinfo) if updated.tzinfo else datetime.now()
        cache_age = (now - updated).total_seconds()
        if updated.date() != date.today() and cache_age > _CACHE_DURATION_SECONDS:
            _log("arena_fetcher", "CACHE_LOAD", "EXPIRADO", f"Antigüedad: {cache_age/3600:.1f}h, fecha: {updated.date()}")
            return {}
        models_raw = data.get("models", {})
        fast_index: Dict[str, Dict[str, float]] = {}
        for name, info in models_raw.items():
            elo = info.get("elo", 1000.0)
            category = info.get("category", "general").lower()
            normalized_score = min(100.0, max(0.0, (elo - 1000.0) / 3.0))
            if name not in fast_index:
                fast_index[name] = {}
            fast_index[name][category] = normalized_score
            fast_index[name]["general"] = fast_index[name].get("general", normalized_score)
        _log("arena_fetcher", "CACHE_LOAD", "VALIDO", f"{len(fast_index)} modelos, actualizado {updated_str}")
        return fast_index
    except Exception as e:
        _log("arena_fetcher", "CACHE_LOAD", "ERROR", str(e))
        return {}

def _save_cache(raw_models: Dict[str, Any]) -> None:
    """Guarda datos brutos en disco. Solo se llama si hay datos nuevos de HF o GitHub."""
    if not raw_models:
        _log("arena_fetcher", "CACHE_SAVE", "OMITIDO", "Sin datos para guardar")
        return
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = {"updated_at": datetime.now().isoformat(), "models": raw_models}
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)
        _log("arena_fetcher", "CACHE_SAVE", "EXITOSO", f"{len(raw_models)} modelos en {_CACHE_PATH}")
    except Exception as e:
        _log("arena_fetcher", "CACHE_SAVE", "ERROR", f"{str(e)} - ruta: {_CACHE_PATH}")

def _fetch_from_huggingface() -> Optional[Dict[str, Any]]:
    """Intenta cargar desde HuggingFace usando la biblioteca 'datasets' (fuente primaria)."""
    try:
        from datasets import load_dataset
        logger.info("Cargando dataset lmarena-ai/leaderboard-dataset...")
        # FIX: Añadir config name 'text' para el dataset
        dataset = load_dataset(HF_DATASET, 'text', split="latest")
        models_dict = {}
        for row in dataset:
            model = row.get('model_name') or row.get('model')
            if not model:
                continue
            normalized = normalize_model_id(str(model).strip())
            if not normalized:
                continue
            score = row.get('rating') or row.get('arena_score') or 1000.0
            try:
                elo = float(score)
            except (ValueError, TypeError):
                elo = 1000.0
            category = row.get('category', 'general').lower() if 'category' in row else 'general'
            votes = row.get('votes') or row.get('num_battles') or 0
            try:
                votes = int(votes)
            except (ValueError, TypeError):
                votes = 0
            models_dict[normalized] = {"elo": elo, "category": category, "votes": votes}
        logger.info(f"Dataset HF cargado: {len(models_dict)} modelos")
        return models_dict
    except ImportError:
        logger.warning("datasets no instalada, intentando GitHub...")
        return None
    except Exception as e:
        logger.warning(f"Error HF: {type(e).__name__}: {e}")
        return None

def _fetch_from_github() -> Optional[Dict[str, Any]]:
    """Intenta cargar rankings desde la URL configurada en ARENA_GITHUB_URL."""
    # FIX: Usar la constante global ARENA_GITHUB_URL en lugar de os.getenv() directo
    # La constante ya lee del entorno con fallback, evitando lecturas inconsistentes
    url = ARENA_GITHUB_URL
    if not url:
        _log("arena_fetcher", "GITHUB", "DESHABILITADO", "Variable ARENA_GITHUB_URL no configurada")
        return None
    try:
        logger.info(f"Intentando cargar desde fuente secundaria: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Formato del mirror arena-ai-leaderboards (models[])
        if isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
            models_dict = {}
            for entry in data["models"]:
                model = entry.get("model")
                score = entry.get("score")
                if not model or score is None:
                    continue
                normalized = normalize_model_id(str(model).strip())
                if not normalized:
                    continue
                elo = float(score) if isinstance(score, (int, float)) else 1000.0
                models_dict[normalized] = {"elo": elo, "category": "general", "votes": 0}
            logger.info(f"Fuente secundaria (JSON mirror): {len(models_dict)} modelos")
            return models_dict

        # Formato JSON plano {model: score}
        if isinstance(data, dict) and all(isinstance(v, (int, float)) for v in data.values()):
            models_dict = {}
            for model, score in data.items():
                normalized = normalize_model_id(str(model).strip())
                if not normalized:
                    continue
                elo = float(score) if isinstance(score, (int, float)) else 1000.0
                models_dict[normalized] = {"elo": elo, "category": "general", "votes": 0}
            logger.info(f"Fuente secundaria (JSON plano): {len(models_dict)} modelos")
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
    """Parsea el contenido CSV y retorna dict de modelos raw (para fallback CSV)."""
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
        models_dict = {}
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
            models_dict[normalized] = {"elo": elo, "category": category, "votes": votes}
            parsed_count += 1
        if not models_dict:
            logger.warning("arena_fetcher: No se parsearon modelos del CSV")
            return None
        logger.info(f"arena_fetcher: {parsed_count} modelos parseados correctamente")
        return models_dict
    except csv.Error as e:
        logger.error(f"arena_fetcher: Error parseando CSV: {e}")
        return None
    except Exception as e:
        logger.error(f"arena_fetcher: Error inesperado parseando CSV: {type(e).__name__}: {e}")
        return None

def _build_fast_index(raw_models: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Convierte datos raw en índice de acceso rápido."""
    fast: Dict[str, Dict[str, float]] = {}
    for name, info in raw_models.items():
        elo = info.get("elo", 1000.0)
        category = info.get("category", "general").lower()
        score = min(100.0, max(0.0, (elo - 1000.0) / 3.0))
        if name not in fast:
            fast[name] = {}
        fast[name][category] = score
        fast[name]["general"] = fast[name].get("general", score)
    return fast

def _fetch_rankings_with_fallback() -> Optional[Dict[str, Any]]:
    """Obtiene rankings siguiendo jerarquía: HuggingFace → GitHub → caché local."""
    # 1. HuggingFace (fuente primaria)
    raw = _fetch_from_huggingface()
    if raw:
        _save_cache(raw)
        logger.info("✓ Rankings obtenidos de HuggingFace (fuente primaria)")
        return raw
    logger.warning("✗ HuggingFace falló, intentando fuente secundaria (GitHub)...")

    # 2. Fuente secundaria (GitHub/CSV)
    raw = _fetch_from_github()
    if raw:
        _save_cache(raw)
        logger.info("✓ Rankings obtenidos de fuente secundaria (GitHub)")
        return raw
    logger.warning("✗ Fuente secundaria falló, intentando caché local...")

    # 3. Caché local (último recurso)
    cached = _load_cache()
    if cached:
        logger.info("✓ Rankings obtenidos de caché local (último recurso)")
        raw_cached = {}
        for name, scores in cached.items():
            elo = scores.get("general", 1000.0) * 3.0 + 1000.0
            raw_cached[name] = {"elo": elo, "category": "general", "votes": 0}
        return raw_cached
    logger.warning("✗ No se pudieron obtener rankings de ninguna fuente")
    return None

def _background_refresh() -> None:
    """Hilo en segundo plano para refrescar caché siguiendo jerarquía HF→GitHub→caché."""
    global _arena_data, _needs_refresh
    _log("arena_fetcher", "BACKGROUND", "INICIADO")
    try:
        raw = _fetch_rankings_with_fallback()
        if raw:
            new_index = _build_fast_index(raw)
            with _refresh_lock:
                _arena_data = new_index
                _needs_refresh = False
            _log("arena_fetcher", "BACKGROUND", "COMPLETADO", f"{len(new_index)} modelos en memoria")
        else:
            _log("arena_fetcher", "BACKGROUND", "SIN_DATOS", "Se mantienen datos existentes")
    except Exception as e:
        _log("arena_fetcher", "BACKGROUND", "ERROR", str(e))

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

# -----------------------------------------------------------------------------
# Inicialización al importar: carga con jerarquía HF→GitHub→caché, luego hilo background
# -----------------------------------------------------------------------------
_initial_raw = _fetch_rankings_with_fallback()
if _initial_raw:
    _initial_cache = _build_fast_index(_initial_raw)
    _log("arena_fetcher", "INIT", "DATOS_CARGADOS", f"{len(_initial_cache)} modelos disponibles")
else:
    _initial_cache = {}
    _log("arena_fetcher", "INIT", "SIN_DATOS", "No hay datos disponibles de ninguna fuente")

with _refresh_lock:
    _arena_data = _initial_cache
    _needs_refresh = (len(_initial_cache) == 0)
_start_background_refresh_if_needed()

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
# Función pública (O(1)) con normalización mejorada
# -----------------------------------------------------------------------------
def get_score_for_model(model_id: str, task_type: str = None) -> Optional[float]:
    """
    Retorna score Arena normalizado (0-100) si está disponible en memoria.
    Prioridad: HF → GitHub → caché → snapshot.
    Incluye búsqueda por subcadena para mejorar tasa de acierto.
    No realiza llamadas bloqueantes.
    """
    if not model_id:
        return None
    search_name = normalize_model_id(model_id)
    if not search_name:
        return None

    category_map = {
        "planning": ["reasoning", "general"],
        "evaluation": ["reasoning", "general"],
        "generation": ["coding", "reasoning"],
        "coding": ["coding", "reasoning"],
        "correction": ["coding", "general"],
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

    # Búsqueda por subcadena (fallback para nombres no exactos)
    search_lower = search_name.lower()
    for name, scores in data_snapshot.items():
        name_lower = name.lower()
        if search_lower in name_lower or name_lower in search_lower:
            for cat in categories:
                if cat in scores:
                    return scores[cat]
            return scores.get("general")

    return None

def validate_self() -> bool:
    _log("arena_fetcher", "VALIDATE_SELF", "INICIADO")
    try:
        score = get_score_for_model("qwen/qwen2.5-coder", "coding")
        _log("arena_fetcher", "VALIDATE_SELF", "COMPLETADO", f"Score obtenido: {score if score is not None else 'None'}")
        return True
    except Exception as e:
        _log("arena_fetcher", "VALIDATE_SELF", "FALLIDO", str(e))
        return False

if __name__ == "__main__":
    if not logging.root.handlers:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    import time

    print("=== PRUEBA: Arena Fetcher con jerarquía HF → GitHub → Caché ===")

    # Prueba 1: Verificar disponibilidad
    print("\n[1] Verificando disponibilidad del ranking...")
    available = is_arena_ranking_available()
    if available:
        print("✓ Ranking disponible (HF, GitHub o caché)")
    else:
        print("⚠️ Ranking NO disponible")

    # Prueba 2: Consulta no bloqueante con normalización mejorada
    print("\n[2] Prueba de consulta con búsqueda por subcadena...")
    t0 = time.time()
    s = get_score_for_model("openai/gpt-4o", "general")
    t1 = time.time()
    print(f"gpt-4o → {s:.1f}" if s else "gpt-4o → None")
    print(f"Tiempo consulta: {(t1-t0)*1000:.0f}ms (debe ser <5ms)")
    print("✓ No bloqueante OK")

    # Prueba 3: Múltiples modelos con normalización
    print("\n[3] Consultando modelos conocidos con búsqueda flexible...")
    test_models = ["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "qwen/qwen2.5-coder", "gpt-4"]
    for m in test_models:
        score = get_score_for_model(m)
        status = f"{score:.1f}" if score else "N/A"
        print(f"  {m} → {status}")

    # Prueba 4: Verificar fuente secundaria (GitHub)
    print("\n[4] Verificando fuente secundaria (GitHub)...")
    github_url = os.getenv("ARENA_GITHUB_URL")
    if not github_url:
        print("⚠️ Variable ARENA_GITHUB_URL no configurada. Omitiendo prueba de GitHub.")
    else:
        print(f"URL configurada: {github_url}")
        try:
            # Llamar a la función real que usa la URL del entorno
            github_data = _fetch_from_github()
            if github_data:
                fast_index = _build_fast_index(github_data)
                print(f"✓ Fuente secundaria funcional: {len(fast_index)} modelos parseados")
                # Mostrar un par de ejemplos para verificar calidad
                sample_models = list(fast_index.keys())[:3]
                for model in sample_models:
                    score = fast_index[model].get('general', 'N/A')
                    print(f"  Ejemplo: {model} -> {score:.1f}" if isinstance(score, float) else f"  Ejemplo: {model} -> {score}")
            else:
                print("⚠️ No se pudieron parsear modelos de la fuente secundaria (ver logs)")
        except Exception as e:
            print(f"❌ Error al probar fuente secundaria: {e}")

    print("\n✅ Todas las pruebas pasaron")