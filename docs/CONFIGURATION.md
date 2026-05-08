# CONFIGURATION.md

# Configuración

## Variables de entorno

| Variable | Descripción | Valor por defecto | Requerida |
|----------|-------------|-------------------|-----------|
| OPENROUTER_API_KEY | API key para acceder a OpenRouter | | Sí |
| NAS_HOST | Dirección del servidor NAS | | Sí |
| NAS_USER | Usuario para autenticación en NAS | | Sí |
| NAS_SANDBOX_PATH | Ruta en NAS para entorno sandbox | | Sí |
| NAS_SERVER_PATH | Ruta en NAS para servidor principal | | Sí |
| APA_HOST | Host del servicio APA | | Sí |
| APA_PORT | Puerto del servicio APA | | Sí |
| LOG_LEVEL | Nivel de logging (ej: DEBUG, INFO, WARNING, ERROR) | | Sí |
| ANTHROPIC_API_KEY | API key para Anthropic | | Sí |
| OPENAI_API_KEY | API key para OpenAI | | Sí |
| GROQ_API_KEY | API key para GROQ | | Sí |
| GITHUB_TOKEN | Token de autenticación de GitHub | | Sí |
| TOGETHER_API_KEY | API key para Together AI | | Sí |
| FIREWORKS_API_KEY | API key para Fireworks AI | | Sí |
| HF_TOKEN | Token de Hugging Face | | Sí |
| OLLAMA_BASE_URL | URL base de OLLAMA | | Sí |
| PROVIDER_PRIORITY | Prioridad de proveedores (ej: openai,anthropic,openrouter) | | Sí |
| USE_ARENA_RANKINGS | Habilitar rankings externos desde Arena | | No |
| ARENA_CACHE_TTL_HOURS | TTL en horas para caché de rankings Arena | | No |
| ARENA_API_TIMEOUT_SEC | Timeout en segundos para API de Arena | | No |
| ARENA_ELITE_THRESHOLD | Umbral para elite en rankings Arena | | No |
| ARENA_API_BASE | URL base para API de Arena | | No |
| HF_LEADERBOARD_URL | URL del leaderboard de Hugging Face | | No |
| ARENA_TASK_MAPPING | Mapeo JSON de tareas a categorías de ranking | | No |
| DEFAULT_QUALITY_MODE | Modo de calidad por defecto | | No |
| SIMPLE_MODEL | Modelo simple de referencia | | No |

## Archivos de configuración

### config/settings.py
Archivo principal de configuración que carga variables de entorno (.env) y define parámetros del sistema APA. Centraliza la gestión de configuración para todos los módulos del proyecto.

## Configuración por entorno

### Desarrollo
- **LOG_LEVEL**: DEBUG
- **ENABLE_CACHE**: False
- **PROVIDER_PRIORITY**: openai,anthropic,openrouter
- **ARENA_RANKINGS**: Desactivados

### Testing
- **LOG_LEVEL**: WARNING
- **USE_ARENA_RANKINGS**: false
- **ARENA_CACHE_TTL_HOURS**: 1
- **PROVIDER_PRIORITY**: mock

### Producción
- **LOG_LEVEL**: ERROR
- **ENABLE_CACHE**: True
- **PROVIDER_PRIORITY**: openai,anthropic,openrouter,together,fireworks
- **ARENA_RANKINGS**: Activados con cache
- **CACHE_TTL**: Mayor (horas definidas en ARENA_CACHE_TTL_HOURS)

## Ejemplo de .env completo

```env
# API Keys de servicios de IA
OPENROUTER_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
GROQ_API_KEY=sk-xxx
TOGETHER_API_KEY=sk-xxx
FIREWORKS_API_KEY=sk-xxx
HF_TOKEN=hf-xxx

# Conexión y almacenamiento
NAS_HOST=192.168.1.100
NAS_USER=admin
NAS_SANDBOX_PATH=/sandbox
NAS_SERVER_PATH=/server
APA_HOST=localhost
APA_PORT=8000
OLLAMA_BASE_URL=http://localhost:11434

# Logging y calidad
LOG_LEVEL=INFO
PROVIDER_PRIORITY=openai,anthropic,openrouter
DEFAULT_QUALITY_MODE=balanced

# Rankings externos
USE_ARENA_RANKINGS=true
ARENA_CACHE_TTL_HOURS=24
ARENA_API_TIMEOUT_SEC=30
ARENA_ELITE_THRESHOLD=0.7
ARENA_API_BASE=https://arena.example.com/api
HF_LEADERBOARD_URL=https://huggingface.co/api/leaderboard

# Mapeo de tareas: planning, generation, correction, evaluation
ARENA_TASK_MAPPING={"planning":"hard-prompts","generation":"coding","correction":"reasoning","evaluation":"math"}

# Modelo simple de referencia
SIMPLE_MODEL=gpt-3.5-turbo
```