# apa/config/settings.py

import os
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings
from pathlib import Path


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
    
    together_api_key: str = ""
    fireworks_api_key: str = ""
    use_arena_rankings: bool = True
    arena_cache_ttl_hours: int = 24
    arena_api_timeout_sec: float = 1.5
    arena_elite_threshold: int = 1250
    arena_task_mapping: dict = {
        "planning": "hard-prompts",
        "generation": "coding",
        "correction": "reasoning",
        "evaluation": "math"
    }
    default_quality_mode: str = "balanced"

    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434"

    # NAS (MCP Server)
    nas_host: str = ""
    nas_user: str = ""
    nas_sandbox_path: str = "/app/sandbox"

    # Arena Fetcher
    use_arena_rankings: bool = True
    arena_cache_ttl_hours: int = 24
    arena_api_timeout_sec: float = 1.5
    arena_task_mapping: str = '{"planning":"hard-prompts","generation":"coding","correction":"reasoning","evaluation":"math"}'

    # Router
    default_quality_mode: str = "balanced"
    log_level: str = "INFO"
    provider_priority: str = "openrouter,together,fireworks,groq,github,anthropic,openai,ollama"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @model_validator(mode='after')
    def validate_at_least_one_provider(self) -> 'Settings':
        """Asegura que al menos un proveedor tenga credenciales configuradas."""
        providers = [
            ("openrouter_api_key", self.openrouter_api_key),
            ("anthropic_api_key", self.anthropic_api_key),
            ("openai_api_key", self.openai_api_key),
            ("groq_api_key", self.groq_api_key),
            ("github_token", self.github_token),
            ("together_api_key", self.together_api_key),
            ("fireworks_api_key", self.fireworks_api_key),
        ]
        # Ollama no requiere key, solo URL
        has_valid_key = any(key.strip() for _, key in providers)
        has_ollama = bool(self.ollama_base_url.strip())

        if not has_valid_key and not has_ollama:
            raise ValueError(
                "No se encontró ninguna API key configurada. "
                "Define al menos una de las siguientes variables en .env:\n"
                "OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, "
                "GROQ_API_KEY, GITHUB_TOKEN, TOGETHER_API_KEY, FIREWORKS_API_KEY, "
                "o configura OLLAMA_BASE_URL para usar modelos locales."
            )
        return self


# Singleton de configuración
settings = Settings()