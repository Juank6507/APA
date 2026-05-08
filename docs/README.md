# Nombre del proyecto
APA (Automated Programming Assistant) es un sistema asistido por inteligencia artificial para la generación, corrección y documentación de código fuente. Su propósito es automatizar tareas de desarrollo mediante el uso de agentes especializados que analizan, corrigen y documentan proyectos de software.

## Características principales
- Generación automática de código a partir de prompts en lenguaje natural.
- Corrección inteligente de errores en código mediante análisis de resultados de ejecución.
- Documentación completa del proyecto (README, API, configuración y desarrollo).
- Extracción de firmas reales de clases y funciones públicas para asistencia contextual.
- Soporte para múltiples proveedores de LLM a través de integraciones como Ollama.
- Gestión de caché y optimización de llamadas a modelos de lenguaje.
- Construcción de prompts enriquecidos con dependencias y contexto del proyecto.

## Requisitos
- Python 3.x
- Dependencias listadas en `requirements.txt`
- Acceso a proveedores de LLM soportados (Ollama, OpenAI, etc.) según configuración
- Sistema operativo compatible con la estructura de carpetas y rutas utilizadas

## Instalación
1. Clona el repositorio:
   ```bash
   git clone <repository-url>
   cd APA
   ```
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Configura las variables de entorno necesarias según `CONFIGURATION.md`.

## Uso
- Ejecuta la interfaz gráfica:
  ```bash
  python prompt_gui.py
  ```
- Utiliza la CLI para generar documentación:
  ```bash
  python setup_project.py
  ```
- Ejemplos de uso de agentes:
  - Corrección de código con `CorrectorAgent.correct()`
  - Generación de README con `DocumenterAgent.generate_readme()`
  - Extracción de firmas con `extract_signatures(project_path)`

## Estructura del proyecto
- `apa/agents/` — Agentes principales:
  - `corrector.py`: Corrección y diagnóstico de código.
  - `documenter.py`: Generación de documentación.
  - `generator.py`: Generación de código asistida.
- `apa/core/` — Módulos centrales:
  - `orchestrator.py`, `planner.py`, `validator.py`, entre otros.
- `apa/sdk/` — Integraciones y proveedores.
- `docs/` — Documentación generada (README, API, CONFIGURATION, DEVELOPMENT).
- `data/` — Archivos de configuración y caché.
- `tests/` — Pruebas unitarias y de integración.

## Configuración
Ve CONFIGURATION.md para la lista completa de variables de entorno.

## Contribución
1. Fork del repositorio.
2. Crea una rama para tu funcionalidad.
3. Realiza commits con mensajes claros y descriptivos.
4. Envía un Pull Request con una descripción detallada de los cambios.

## Costes Estimados

*Sin datos de uso registrados para este proyecto.*
