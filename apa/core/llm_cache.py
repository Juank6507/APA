# apa/core/llm_cache.py
import os
import sys
import json
import sqlite3
import hashlib
import logging
import gc
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    from config.settings import settings
except ImportError:
    class _DummySettings:
        LLM_CACHE_PATH = None
        LLM_CACHE_TTL_DAYS = 30
        log_level = 'INFO'
    settings = _DummySettings()

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, getattr(settings, 'log_level', 'DEBUG').upper(), logging.DEBUG))

class LLMCache:
    def __init__(self, cache_path: Optional[Path] = None, ttl_days: int = 30):
        # Resolver ruta: parámetro -> settings -> fallback por defecto
        if cache_path is None:
            cache_path = getattr(settings, 'LLM_CACHE_PATH', None)
        if cache_path is None:
            cache_path = Path(__file__).parents[1] / "cache" / "llm_cache.db"
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Resolver TTL: parámetro -> settings
        self.ttl_days = ttl_days if ttl_days != 30 else getattr(settings, 'LLM_CACHE_TTL_DAYS', ttl_days)

        # Inicializar BD
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(str(self.cache_path)) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        prompt TEXT,
                        model TEXT,
                        response TEXT,
                        created_at TEXT,
                        expires_at TEXT
                    )
                """)
            logger.debug(f"LLMCache inicializado en {self.cache_path}")
        except Exception as e:
            logger.debug(f"Error inicializando LLMCache: {e}")

    def _compute_key(self, prompt: str, model: str, **params) -> str:
        param_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        raw = f"{prompt}|{model}|{param_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, prompt: str, model: str, **params) -> Optional[Dict[str, Any]]:
        try:
            key = self._compute_key(prompt, model, **params)
            with sqlite3.connect(str(self.cache_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT response FROM cache WHERE key = ? AND expires_at > datetime('now')",
                    (key,)
                )
                row = cursor.fetchone()
                if row:
                    logger.debug(f"Cache HIT: {key[:8]}...")
                    return json.loads(row[0])
                logger.debug(f"Cache MISS: {key[:8]}...")
                return None
        except Exception as e:
            logger.debug(f"Cache get falló: {e}")
            return None

    def set(self, prompt: str, model: str, response: Dict[str, Any], **params) -> None:
        try:
            key = self._compute_key(prompt, model, **params)
            now = datetime.utcnow()
            # Formato compatible con comparación string de SQLite (espacio en lugar de 'T')
            expires = (now + timedelta(days=self.ttl_days)).strftime('%Y-%m-%d %H:%M:%S')
            resp_json = json.dumps(response, ensure_ascii=False)
            with sqlite3.connect(str(self.cache_path)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, prompt, model, response, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (key, prompt, model, resp_json, now.isoformat(), expires)
                )
            logger.debug(f"Cache SET: {key[:8]}... (TTL: {self.ttl_days}d)")
        except Exception as e:
            logger.debug(f"Cache set falló: {e}")

    def clear_expired(self) -> int:
        try:
            with sqlite3.connect(str(self.cache_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM cache WHERE expires_at <= datetime('now')")
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    logger.debug(f"Limpieza de caché: {deleted} entradas eliminadas")
                return deleted
        except Exception as e:
            logger.debug(f"Cache clear_expired falló: {e}")
            return 0


if __name__ == "__main__":
    import time
    import tempfile

    print("Iniciando pruebas de LLMCache...")

    # Configurar entorno de prueba aislado
    test_db = Path(tempfile.gettempdir()) / "test_llm_cache_fix.db"
    if test_db.exists():
        try:
            test_db.unlink()
        except PermissionError:
            time.sleep(0.2)
            test_db.unlink()

    cache = LLMCache(cache_path=test_db, ttl_days=30)

    # Prueba 1: set/get correcto
    prompt = "Test prompt"
    model = "test-model"
    response = {"response": "Hola mundo", "model": "test-model", "tokens": 5}
    cache.set(prompt, model, response, temperature=0.7, max_tokens=100)
    cached = cache.get(prompt, model, temperature=0.7, max_tokens=100)
    assert cached == response, "Test 1 falló: set/get mismatch"
    print("✅ Prueba 1: set/get correcto")

    # Prueba 2: clave diferente retorna None
    cached_none = cache.get("Different prompt", model, temperature=0.7)
    assert cached_none is None, "Test 2 falló: debería retornar None"
    print("✅ Prueba 2: clave diferente retorna None")

    # Prueba 3: limpieza de expiradas
    # Insertamos manualmente una fila expirada con formato nativo de SQLite
    old_expires = (datetime.utcnow() - timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S')
    old_key = cache._compute_key("Old prompt", "old-model", temperature=0.0)
    with sqlite3.connect(str(test_db)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, prompt, model, response, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (old_key, "Old prompt", "old-model", "{}", old_expires, old_expires)
        )
    deleted = cache.clear_expired()
    assert deleted >= 1, f"No se eliminaron entradas expiradas (deleted={deleted})"
    print("✅ Prueba 3: limpieza de expiradas")

    # Limpieza final robusta para Windows
    # Liberar locks de SQLite y recolectar basura antes de eliminar
    gc.collect()
    time.sleep(0.15)
    if test_db.exists():
        try:
            test_db.unlink()
            print("Archivo temporal eliminado correctamente.")
        except PermissionError:
            # Fallback seguro para bloqueos residuales en Windows
            time.sleep(0.5)
            if test_db.exists():
                test_db.unlink()
                print("Archivo temporal eliminado correctamente (reintento).")
    print("Todas las pruebas pasaron.")