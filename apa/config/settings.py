# apa/config/settings.py
# v1.1 — F5 FIX: Búsqueda inteligente del .env + guía al usuario
#         si no se encuentra. Antes, pydantic-settings solo buscaba
#         en el CWD, que a menudo no coincide con el directorio del
#         proyecto cuando se lanza APA desde otra ubicación.
#
# CAMBIOS v1.1 vs v1.0:
#   - _find_env_file(): busca .env en múltiples ubicaciones lógicas
#   - Si no se encuentra, imprime guía clara para el usuario
#   - Settings.Config.env_file usa la ruta encontrada
#   - validate_at_least_one_provider() indica si .env fue encontrado o no
import os
import sys
import logging
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings
from pathlib import Path

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


def _find_env_file() -> Optional[str]:
    """Busca el fichero .env en múltiples ubicaciones lógicas.

    Orden de búsqueda:
    1. Directorio de trabajo actual (CWD)
    2. Directorio donde reside este fichero (apa/config/)
    3. Directorio padre del config (apa/)
    4. Raíz del proyecto APA (padre de apa/)
    5. Subiendo desde el CWD hasta la raíz del sistema de ficheros

    Retorna la ruta absoluta al .env si lo encuentra, o None si no.
    """
    candidates = []

    # 1. Directorio de trabajo actual
    candidates.append(Path.cwd() / ".env")

    # 2. Directorio de este fichero (apa/config/)
    this_dir = Path(__file__).resolve().parent
    candidates.append(this_dir / ".env")

    # 3. Directorio padre (apa/)
    candidates.append(this_dir.parent / ".env")

    # 4. Raíz del proyecto (padre de apa/)
    candidates.append(this_dir.parent.parent / ".env")

    # 5. Buscar subiendo desde el CWD
    current = Path.cwd()
    for _ in range(8):
        candidates.append(current / ".env")
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Buscar el primero que exista
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            logger.info(f".env encontrado en: {resolved}")
            return str(resolved)

    # No encontrado — informar al usuario
    searched_dirs = sorted(set(str(c.parent) for c in candidates))
    logger.warning(
        f".env NO encontrado. Se buscaron en:\n"
        + "\n".join(f"  - {d}" for d in searched_dirs)
        + "\n\n"
        "Coloque el fichero .env en uno de estos directorios, o defina "
        "las variables de entorno directamente (export OPENROUTER_API_KEY=...)."
    )
    return None


# F5: Resolver la ruta del .env antes de instanciar Settings
_resolved_env_path = _find_env_file()


class Settings(BaseSettings):
    # OpenRouter
    openrouter_api_key: str = ""
    
    # Anthropic
    anthropic_api_key: str = ""
    
    # OpenAI
    openai_api_key: str = ""
    
    # Groq
    groq_api_key: str = ""
    
    # GitHub Models
    github_token: str = ""
    
    # Together AI
    together_api_key: str = ""
    
    # Fireworks AI
    fireworks_api_key: str = ""

    #Hugging Face 
    HF_TOKEN: str = ""
    
    # Arena Fetcher
    use_arena_rankings: bool = True
    arena_cache_ttl_hours: int = 24
    arena_api_timeout_sec: float = 1.5
    arena_elite_threshold: int = 1250
    # Mapeo de task_type de APA → categorías reales del dataset Arena (lmarena-ai/leaderboard-dataset)
    # Categorías disponibles: overall, coding, hard_prompts, math, instruction_following,
    # creative_writing, multi_turn, webdev, webdev-html, webdev-react, + idiomas
    arena_task_mapping: dict = {
        "planning": "hard_prompts",       # Tareas de planificación → hard_prompts (razonamiento difícil)
        "generation": "coding",           # Generación de código → coding
        "correction": "coding",           # Corrección de código → coding
        "evaluation": "math"              # Evaluación → math (razonamiento cuantitativo)
    }
    
    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434"
    
    # NAS (MCP Server)
    nas_host: str = ""
    nas_user: str = ""
    nas_sandbox_path: str = "/app/sandbox"
    
    # Router
    default_quality_mode: str = "balanced"
    log_level: str = "INFO"
    provider_priority: str = "openrouter,together,fireworks,groq,github,anthropic,openai,ollama"
    
    # =================================================================
    # SISTEMA DE COSTES DINÁMICOS: Ruta para BD de usage tracking
    # =================================================================
    usage_db_path: str = "apa/data/usage.db"

    # F5: Flag para saber si el .env fue encontrado
    env_file_found: bool = _resolved_env_path is not None
    
    class Config:
        # F5: Usar la ruta encontrada por _find_env_file(), o ".env" como fallback
        env_file = _resolved_env_path if _resolved_env_path else ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
    
    @model_validator(mode='after')
    def validate_at_least_one_provider(self) -> 'Settings':
        """Asegura que al menos un proveedor tenga credenciales configuradas.

        F5: Si no hay claves, informa si el .env fue encontrado o no,
        para que el usuario sepa si el problema es que no tiene .env
        o que el .env existe pero está vacío.

        F8: Ollama solo requiere URL, pero si no hay API keys y solo
        se usa Ollama, se advierte que el servidor debe estar corriendo.
        """
        providers = [
            ("openrouter_api_key", self.openrouter_api_key),
            ("anthropic_api_key", self.anthropic_api_key),
            ("openai_api_key", self.openai_api_key),
            ("groq_api_key", self.groq_api_key),
            ("github_token", self.github_token),
            ("together_api_key", self.together_api_key),
            ("fireworks_api_key", self.fireworks_api_key),
        ]
        has_valid_key = any(key.strip() for _, key in providers)
        has_ollama = bool(self.ollama_base_url.strip())

        if not has_valid_key and not has_ollama:
            if not self.env_file_found:
                msg = (
                    "No se encontró el fichero .env ni se detectaron claves API.\n"
                    "APA buscó el .env en múltiples ubicaciones sin éxito.\n\n"
                    "Solución: Coloque el fichero .env en el directorio raíz del proyecto APA\n"
                    "(donde se encuentra la carpeta 'apa/') con al menos una clave configurada:\n\n"
                    "  OPENROUTER_API_KEY=sk-or-...\n"
                    "  ANTHROPIC_API_KEY=sk-ant-...\n"
                    "  OPENAI_API_KEY=sk-...\n"
                    "  GROQ_API_KEY=gsk_...\n"
                    "  GITHUB_TOKEN=ghp_...\n"
                    "  TOGETHER_API_KEY=...\n"
                    "  FIREWORKS_API_KEY=...\n\n"
                    "O configure OLLAMA_BASE_URL=http://localhost:11434 si usa Ollama local\n"
                    "(nota: el servidor Ollama debe estar corriendo para usarlo)."
                )
            else:
                msg = (
                    "Se encontró el fichero .env, pero ninguna clave API tiene valor.\n"
                    "Edite el fichero .env y añada al menos una clave:\n\n"
                    "  OPENROUTER_API_KEY=sk-or-...\n"
                    "  ANTHROPIC_API_KEY=sk-ant-...\n"
                    "  OPENAI_API_KEY=sk-...\n"
                    "  GROQ_API_KEY=gsk_...\n"
                    "  GITHUB_TOKEN=ghp_...\n"
                    "  TOGETHER_API_KEY=...\n"
                    "  FIREWORKS_API_KEY=...\n\n"
                    "O configure OLLAMA_BASE_URL=http://localhost:11434 si usa Ollama local\n"
                    "(nota: el servidor Ollama debe estar corriendo para usarlo)."
                )
            raise ValueError(msg)

        # F8: Si solo Ollama está configurado, advertir que requiere servidor corriendo
        if not has_valid_key and has_ollama:
            logger.warning(
                "Solo Ollama está configurado como proveedor. "
                "Asegúrese de que el servidor Ollama esté corriendo en %s "
                "antes de usar APA.", self.ollama_base_url
            )
        return self


settings = Settings()


if __name__ == "__main__":
    import sys
    
    if "--test" in sys.argv:
        print("Ejecutando pruebas de settings...")
        
        assert settings is not None, "settings no inicializado"
        assert hasattr(settings, 'usage_db_path'), "usage_db_path no definido"
        assert settings.usage_db_path == "apa/data/usage.db", f"ruta incorrecta: {settings.usage_db_path}"
        
        settings_attrs = dir(settings)
        cost_attrs = [a for a in settings_attrs if 'cost' in a.lower() or 'price' in a.lower()]
        assert not any(a.lower() in ['model_cost_per_call', 'default_costs', 'pricing_dict'] for a in cost_attrs), \
            f"FALLA: Se encontraron atributos de coste hardcodeados: {cost_attrs}"
        
        # F5: Verificar que _find_env_file() existe y retorna str o None
        assert callable(_find_env_file), "_find_env_file no es callable"
        env_result = _find_env_file()
        assert env_result is None or isinstance(env_result, str), \
            f"_find_env_file retorno tipo inesperado: {type(env_result)}"
        
        # F5: Verificar que env_file_found es bool
        assert hasattr(settings, 'env_file_found'), "env_file_found no definido"
        assert isinstance(settings.env_file_found, bool), \
            f"env_file_found no es bool: {type(settings.env_file_found)}"
        
        print("OK - settings.py tiene usage_db_path sin hardcoding de precios")
        print("OK - F5: _find_env_file() funciona, env_file_found =", settings.env_file_found)
        print("Settings tests passed.")
        sys.exit(0)
    
    print("Settings module loaded successfully")