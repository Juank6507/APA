# DEVELOPMENT.md

# Guía de desarrollo

## Arquitectura
El proyecto sigue una arquitectura modular y basada en agentes. Los componentes principales son:
- Agentes especializados (corrector, documenter, generator) que encapsulan lógica de neginio.
- Módulos de núcleo (core) que gestionan flujos, orquestación, validación y almacenamiento en caché.
- Capa de interfaz (interface) con UI basada en tkinter.
- Integración con proveedores LLM a través de configuraciones centralizadas (data/providers.json).
- Los módulos se comunican principalmente mediante llamadas directas y un sistema de caché persistente (llm_cache.db).

## Estructura de módulos
- apa/agents/corrector.py: Agente de corrección de código.
  - CorrectorAgent: corrige errores de ejecución, construye prompts con dependencias y usa Ollama para correcciones simples.
- apa/agents/documenter.py: Agente de documentación.
  - DocumenterAgent: extrae firmas y variables de entorno, genera README, CONFIGURATION.md, API.md y DEVELOPMENT.md.
- apa/agents/generator.py: (módulo pendiente de revisión).
- apa/core/orchestrator.py: Orquesta flujos de trabajo y coordina agentes.
- apa/core/llm_cache.py: Caché de respuestas LLM (llm_cache.db).
- apa/core/error_classifier.py: Clasificación de errores de ejecución.
- apa/core/validator.py: Validación de artefactos y estados.
- apa/core/parallel_executor.py: Ejecución paralela de tareas.
- apa/interface/app.py: Interfaz gráfica principal (tkinter).
- data/providers.json: Configuración de proveedores LLM (OpenAI, Ollama, etc.).
- scripts/setup_project.py: Script de inicialización del proyecto.

## Flujo de datos
1. Entrada: usuario provee un prompt o código a través de la UI (interface/app.py) o scripts.
2. Procesamiento: los datos fluyen hacia core/orchestrator.py, que decide si se requiere corrección, documentación o generación.
3. Corrección: CorrectorAgent analiza errores, construye prompts con _build_fix_prompt_with_dependencies y, si es simple, usa _call_ollama_for_simple_correction.
4. Documentación: DocumenterAgent extrae firmas (extract_signatures) y variables de entorno (extract_env_variables), luego genera artefactos de documentación.
5. Almacenamiento: Las respuestas LLM se almacenan en caché (llm_cache.db) para reutilización y auditoría.
6. Salida: Resultados devueltos a la UI o escritos en docs/ (API.md, CONFIGURATION.md, DEVELOPMENT.md, README.md).

## Cómo añadir funcionalidad
1. Identifica el módulo responsable (core, agents o interface).
2. Añade funciones o clases siguiendo los patrones existentes (métodos públicos claros, uso de _prefijo para internos).
3. Si necesitas nueva integración con LLM, extiende providers.json y usa los wrappers en core/providers.py.
4. Para nuevos agentes, crea una clase con al menos __init__, métodos de procesamiento y un contrato claro de entradas/salidas.
5. Registra cambios en docs/ correspondientes (API.md, CONFIGURATION.md, DEVELOPMENT.md).
6. Escribe tests en tests/ que cubran casos válidos y de error.

## Testing
- Estructura: tests/test_e2e.py, tests/test_full.py, tests/test_parallel.py, tests/test_t13.py.
- Ejecuta tests con: python -m pytest tests/ -v.
- Usa datos de prueba en tests/data y specs en tests/specs.
- Para nuevas funcionalidades, añade pruebas unitarias y de integración siguiendo el estilo existente (ej: test_b2_ollama_simple_error en corrector.py).
- Asegura cobertura de errores conocidos: unknown error, múltiples coincidencias de archivos, y fallos de red con proveedores.

## Debugging
- Registros: logs.json en la raíz del proyecto.
- Depuración de agentes: usa print/logging en métodos críticos (corrector.py, orchestrator.py).
- Caché: inspecciona llm_cache.db con herramientas SQLite para revisar respuestas LLM almacenadas.
- UI: depura con modo consola o añade ventanas de diagnóstico en interface/app.py.
- Pruebas de error: reproduce escenarios con test_t13.py y verifica correcciones con test_b2_ollama_simple_error.

## Convenciones de código
- Nomenclatura: snake_case para funciones y métodos, PascalCase para clases.
- Módulos: nombres descriptivos y alineados con su responsabilidad (ej: corrector.py, documenter.py).
- Comentarios: docstrings para clases y funciones públicas; comentarios breves para lógica compleja.
- Métodos públicos: claramente definidos con contratos de entrada/salida; métodos privados prefijados con _.
- Manejo de errores: usa excepciones estándar y mensajes informativos; evita silenciar errores.
- Formatting: mantén líneas bajo 100 caracteres; usa black si está disponible.