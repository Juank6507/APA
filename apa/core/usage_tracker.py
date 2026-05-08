# apa/core/usage_tracker.py
import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime


class UsageTracker:
    """
    Gestiona el registro de uso de tokens consumidos por llamadas a LLM.
    Almacena en SQLite: apa/data/usage.db
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "usage.db"
        self.db_path = Path(db_path)
        self._ensure_db_exists()
    
    def _ensure_db_exists(self) -> None:
        """Crea la base de datos y la tabla si no existen."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                model TEXT NOT NULL,
                tokens INTEGER NOT NULL,
                request_type TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    
    def log_usage(
        self,
        project_id: str,
        model: str,
        tokens: int,
        request_type: str,
        timestamp: Optional[datetime] = None
    ) -> None:
        """Registra un uso de tokens para un proyecto."""
        if timestamp is None:
            timestamp = datetime.utcnow()
        ts_str = timestamp.isoformat()
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO usage (project_id, model, tokens, request_type, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, model, tokens, request_type, ts_str)
        )
        conn.commit()
        conn.close()
    
    def get_usage_by_project(self, project_id: str) -> List[Dict[str, Any]]:
        """Obtiene todos los registros de uso para un proyecto."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM usage WHERE project_id = ? ORDER BY timestamp DESC",
            (project_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_aggregated_usage(self, project_id: str) -> Dict[str, int]:
        """Obtiene el uso agregado por modelo para un proyecto. Returns: {model: total_tokens}"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT model, SUM(tokens) as total_tokens
            FROM usage
            WHERE project_id = ?
            GROUP BY model
            """,
            (project_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}


if __name__ == "__main__":
    import tempfile
    import shutil
    
    temp_dir = tempfile.mkdtemp()
    test_db = Path(temp_dir) / "test_usage.db"
    
    try:
        tracker = UsageTracker(db_path=test_db)
        
        # Registrar varios usos de prueba
        tracker.log_usage("test_proj", "qwen/qwen2.5-coder", 150, "planning")
        tracker.log_usage("test_proj", "qwen/qwen2.5-coder", 200, "generation")
        tracker.log_usage("test_proj", "anthropic/claude-3-5-sonnet", 300, "correction")
        
        # Validar recuperación por proyecto
        usage_list = tracker.get_usage_by_project("test_proj")
        assert len(usage_list) == 3, f"Esperados 3 registros, obtenidos {len(usage_list)}"
        
        # Validar agregación
        aggregated = tracker.get_aggregated_usage("test_proj")
        assert aggregated.get("qwen/qwen2.5-coder") == 350, f"Tokens qwen: esperado 350, obtenido {aggregated.get('qwen/qwen2.5-coder')}"
        assert aggregated.get("anthropic/claude-3-5-sonnet") == 300, f"Tokens claude: esperado 300, obtenido {aggregated.get('anthropic/claude-3-5-sonnet')}"
        
        # Validar proyecto vacío
        empty = tracker.get_aggregated_usage("proj_inexistente")
        assert empty == {}, f"Esperado dict vacío, obtenido {empty}"
        
        print("✅ UsageTracker tests passed.")
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)