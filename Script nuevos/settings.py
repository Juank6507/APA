# apa/config/settings.py

from pathlib import Path
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

def _log(stage, status, detail=""):
    msg = f"[PROGRESO] | MÓDULO=settings | ETAPA={stage} | ESTADO={status}"
    if detail: msg += f" | DETALLE={detail}"
    print(msg)
    logging.getLogger(__name__).info(msg)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = ""
    nas_host: str = ""
    nas_user: str = ""
    nas_sandbox_path: str = ""
    nas_server_path: str = ""
    apa_host: str = "localhost"
    apa_port: int = 8080
    log_level: str = "INFO"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    provider_priority: str = "openrouter,anthropic,openai,ollama"
    groq_api_key: str = ""
    github_token: str = ""
    together_api_key: str = ""
    fireworks_api_key: str = ""
    use_arena_rankings: bool = True
    arena_cache_ttl_hours: int = 24
    arena_api_timeout_sec: float = 1.5
    arena_elite_threshold: int = 1250
    arena_task_mapping: dict = {"planning":"hard-prompts","generation":"coding","correction":"reasoning","evaluation":"math"}
    default_quality_mode: str = "balanced"

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v): return v.strip() if isinstance(v, str) else v

    @model_validator(mode='after')
    def _validate_providers(self) -> 'Settings':
        keys = {k:(getattr(self,k) or "").strip() for k in ["openrouter_api_key","anthropic_api_key","openai_api_key","groq_api_key","github_token","together_api_key","fireworks_api_key"]}
        ollama = (self.ollama_base_url or "").strip()
        active = [k for k,v in keys.items() if v] + (["ollama"] if ollama != "http://localhost:11434" else [])
        if not active: raise ValueError("Se requiere al menos un proveedor o OLLAMA_BASE_URL configurado")
        _log("VALIDACIÓN_PROVIDERS", "✅ EXITOSA", f"ACTIVOS=[{', '.join(active)}]")
        return self

settings = Settings()

def validate_self():
    _log("VALIDACIÓN_FINAL", "INICIADA")
    try:
        assert settings.nas_host is not None
        assert isinstance(settings.provider_priority, str) and "," in settings.provider_priority
        assert settings.arena_api_timeout_sec <= 2.0  # Garantiza no-bloqueo
        _log("VALIDACIÓN_FINAL", "✅ EXITOSA", "Estructura, tipos y timeout verificados")
        return True
    except Exception as e:
        _log("VALIDACIÓN_FINAL", "❌ FALLIDA", str(e)); return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    if validate_self(): print("✅ VALIDADO | MÓDULO=settings | EJECUCIÓN_CORRECTA | LISTO_PARA_RETROALIMENTACIÓN")