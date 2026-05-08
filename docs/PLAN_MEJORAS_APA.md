# Plan Maestro de Desarrollo de APA (Formato Detallado)

## Estado General del Proyecto
**APA** es un sistema multi-agente autónomo con soporte para 7 lenguajes de programación, 6 proveedores de LLM y 165+ modelos disponibles. Cuenta con orquestación robusta, checkpointing, paralelización, caché de respuestas, validación multi-capa, interfaz web con chatbot y generación de documentación automática.

## Leyenda de Prioridad y Estado
- **Prioridad:** `X / Completada` | `Alta / Actual` | `Alta / Próxima` | `Alta` | `Media` | `Baja`
- **Estado:** `[x] Completada` | `[ ] Pendiente`

---

## Fase 0: Infraestructura Base y Orquestador Inicial

### T0.1 - Estructura de carpetas del proyecto APA
- **Prioridad:** X / Completada
- **Descripción:** Crear script `setup_project.py` que genere la estructura completa de directorios y archivos base (core, agents, mcp, interface, config, etc.) con docstrings descriptivos.
- **Archivos implicados:** `setup_project.py`, `apa/*/__init__.py`
- **Criterio de aceptación:** Ejecutar `python setup_project.py` crea la estructura exacta sin errores y es idempotente.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### T0.2 - Archivo de configuración y variables de entorno
- **Prioridad:** X / Completada
- **Descripción:** Implementar `apa/config/settings.py` usando `pydantic-settings` para cargar variables desde `.env`. Crear `.env.example`.
- **Archivos implicados:** `apa/config/settings.py`, `.env.example`, `apa/requirements.txt`
- **Criterio de aceptación:** La clase `Settings` valida que `OPENROUTER_API_KEY` no esté vacía y expone una instancia global `settings`.
- **Dependencias:** T0.1
- **Estado:** [x] Completada

### T0.3 - Conector SSH al NAS
- **Prioridad:** X / Completada
- **Descripción:** Implementar `apa/mcp/server.py` con la clase `NASConnector` para ejecutar código en el sandbox remoto vía SSH/Docker y JSON-RPC.
- **Archivos implicados:** `apa/mcp/server.py`, `apa/requirements.txt`
- **Criterio de aceptación:** Los métodos `execute_code`, `read_file`, `write_file` funcionan correctamente sobre el contenedor Docker en el NAS.
- **Dependencias:** T0.2
- **Estado:** [x] Completada

### T0.4 - Orquestador principal
- **Prioridad:** X / Completada
- **Descripción:** Implementar `apa/core/orchestrator.py` para ejecutar el ciclo completo: parse de spec -> generación de plan -> ejecución secuencial de tareas respetando dependencias -> entrega de resultados.
- **Archivos implicados:** `apa/core/orchestrator.py`
- **Criterio de aceptación:** Ejecutar el orquestador con `example.md` completa 3/3 tareas y persiste `plan.json`.
- **Dependencias:** T0.3, T2.2, T3.2
- **Estado:** [x] Completada

## Fase 1: Router de Modelos Multi-Proveedor

### T1.1 - Escáner de modelos gratuitos en OpenRouter
- **Prioridad:** X / Completada
- **Descripción:** Implementar `fetch_free_models()` en `router.py` que consulte la API de OpenRouter y filtre modelos con `pricing.prompt == "0"`. Cachear resultado 10 min.
- **Archivos implicados:** `apa/core/router.py`
- **Criterio de aceptación:** La función retorna una lista de modelos gratuitos con `id`, `context_length` y `capabilities` inferidas.
- **Dependencias:** T0.2
- **Estado:** [x] Completada

### T1.2 - Lógica de selección de modelo por tipo de tarea
- **Prioridad:** X / Completada
- **Descripción:** Implementar `select_model(task_type)` y `escalate_model()` priorizando `coding` para generación y `long_context` para planificación.
- **Archivos implicados:** `apa/core/router.py`
- **Criterio de aceptación:** `select_model("correction")` elige modelos rápidos (ctx<=32k).
- **Dependencias:** T1.1
- **Estado:** [x] Completada

### T1.3 - Router v2: call_llm centralizado y ranking de calidad
- **Prioridad:** X / Completada
- **Descripción:** Refactorizar `router.py` para centralizar la lógica de llamada, reintentos y escalado en `call_llm()`. Añadir `MODEL_QUALITY_RANKING`.
- **Archivos implicados:** `apa/core/router.py`, `apa/core/planner.py`
- **Criterio de aceptación:** `planner.py` usa `call_llm()` en lugar de su propia lógica de reintento.
- **Dependencias:** T1.2, T2.1
- **Estado:** [x] Completada

### T1.4 - Descubrimiento de modelos con free tier por usuario
- **Prioridad:** X / Completada
- **Descripción:** Añadir `FREE_TIER_MODELS` y `fetch_free_tier_models()` para incluir modelos como Gemini/Claude con límites gratuitos.
- **Archivos implicados:** `apa/core/router.py`
- **Criterio de aceptación:** El pool de modelos incluye modelos "free tier" si la API de OpenRouter los lista como disponibles.
- **Dependencias:** T1.3
- **Estado:** [x] Completada

### T1.5 - Capa multi-proveedor (Anthropic, OpenAI, Ollama)
- **Prioridad:** X / Completada
- **Descripción:** Implementar `apa/core/providers.py` con clases `OpenRouterProvider`, `AnthropicProvider`, `OpenAIProvider`, `OllamaProvider` y un `ProviderManager`.
- **Archivos implicados:** `apa/core/providers.py`, `apa/config/settings.py`
- **Criterio de aceptación:** El router puede usar modelos de Anthropic/OpenAI si las API keys están configuradas.
- **Dependencias:** T1.4
- **Estado:** [x] Completada

### T1.6 - Proveedores Groq, GitHub Models y Health Check
- **Prioridad:** X / Completada
- **Descripción:** Añadir `GroqProvider`, `GitHubModelsProvider` y método `health_check()` en `ProviderManager`.
- **Archivos implicados:** `apa/core/providers.py`, `apa/config/settings.py`
- **Criterio de aceptación:** Pool de 61+ modelos; `health_check()` retorna estado de todos los proveedores.
- **Dependencias:** T1.5
- **Estado:** [x] Completada

## Fase 2: Orquestador SDD (Spec-Driven Development)

### T2.1 - Parser de spec.md
- **Prioridad:** X / Completada
- **Descripción:** Implementar `parse_spec()` en `planner.py` usando un LLM para extraer objetivo, inputs, outputs y criterios en JSON.
- **Archivos implicados:** `apa/core/planner.py`
- **Criterio de aceptación:** Convierte `specs/example.md` en un dict estructurado válido.
- **Dependencias:** T1.3
- **Estado:** [x] Completada

### T2.2 - Generador de plan de tareas
- **Prioridad:** X / Completada
- **Descripción:** Implementar `generate_plan()` que use un LLM para descomponer la spec en tareas atómicas con dependencias.
- **Archivos implicados:** `apa/core/planner.py`
- **Criterio de aceptación:** Genera y guarda `plan.json` con tareas que tienen `acceptance_criterion` verificable.
- **Dependencias:** T2.1
- **Estado:** [x] Completada

## Fase 3: Agentes Autónomos

### T3.1 - Agente generador de código (GeneratorAgent)
- **Prioridad:** X / Completada
- **Descripción:** Implementar `GeneratorAgent` con métodos `generate()`, `generate_and_test()` y `save_to_sandbox()`.
- **Archivos implicados:** `apa/agents/generator.py`
- **Criterio de aceptación:** Genera código Python válido, lo ejecuta en el NAS y verifica `CRITERIO OK`.
- **Dependencias:** T2.2, T0.3
- **Estado:** [x] Completada

### T3.2 - Agente corrector con escalado de modelo
- **Prioridad:** X / Completada
- **Descripción:** Implementar `CorrectorAgent` con `analyze_error()` y `correction_loop()` para arreglar código fallido (3 intentos máximo).
- **Archivos implicados:** `apa/agents/corrector.py`
- **Criterio de aceptación:** Corrige errores de sintaxis y lógica simple de forma autónoma.
- **Dependencias:** T3.1
- **Estado:** [x] Completada

## Fase 4: Interfaz Web y Experiencia Inicial

### T4.1 - Generación de la interfaz web por el propio APA
- **Prioridad:** X / Completada
- **Descripción:** Usar el propio APA para generar `apa/interface/app.py` (FastAPI) basado en una spec de interfaz.
- **Archivos implicados:** `apa/interface/app.py`, `apa/specs/interface_spec.md`
- **Criterio de aceptación:** Interfaz web funcional en `localhost:8080` con textarea para spec y progreso en tiempo real.
- **Dependencias:** T0.4
- **Estado:** [x] Completada

## Mejoras Post-Fase 4 (Robustez y Calidad)

### T_REF.1 - Lector de proyectos existentes (ProjectReader)
- **Prioridad:** X / Completada
- **Descripción:** Implementar `ProjectReader` para analizar carpetas de código existente y generar contexto/specs de refactorización.
- **Archivos implicados:** `apa/core/project_reader.py`
- **Criterio de aceptación:** `get_stats()` y `to_context()` funcionan sobre el propio proyecto APA.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### T_UI.1 - Mejoras interfaz: entrada de proyectos + descarga
- **Prioridad:** X / Completada
- **Descripción:** Añadir pestaña "Analizar proyecto", historial y fix del endpoint `/download` para obtener archivos del NAS.
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** Se puede analizar una carpeta local y generar spec de refactorización.
- **Dependencias:** T_REF.1
- **Estado:** [x] Completada

### T_DOC.1 - Agente documentador (DocumenterAgent)
- **Prioridad:** X / Completada
- **Descripción:** Implementar agente que genere `README.md`, `CONFIGURATION.md`, `API.md` y `DEVELOPMENT.md`.
- **Archivos implicados:** `apa/agents/documenter.py`
- **Criterio de aceptación:** Documentación generada sin alucinaciones (usa firmas reales de AST y variables de entorno reales).
- **Dependencias:** T_REF.1
- **Estado:** [x] Completada

### Fusión - Refactorización de Router y Providers (sin hardcoding)
- **Prioridad:** X / Completada
- **Descripción:** Re-implementar `router.py` y `providers.py` para eliminar listas estáticas y depender exclusivamente de APIs reales y rankings dinámicos (Arena).
- **Archivos implicados:** `apa/core/router.py`, `apa/core/providers.py`
- **Criterio de aceptación:** Pool de 165+ modelos detectados dinámicamente. Selector usa `arena_fetcher` para ranking.
- **Dependencias:** T1.6
- **Estado:** [x] Completada

### Arena - Implementación de arena_fetcher para rankings dinámicos
- **Prioridad:** X / Completada
- **Descripción:** Crear `arena_fetcher.py` para descargar rankings ELO de HuggingFace/GitHub y cachearlos.
- **Archivos implicados:** `apa/core/arena_fetcher.py`
- **Criterio de aceptación:** `get_score_for_model()` retorna un score real o 50.0 si falla la red.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

## Bloque A: Correcciones Críticas de Robustez

### A1 - Fix get_available_models en ProviderManager
- **Prioridad:** X / Completada
- **Descripción:** Corregir bug donde el escalado fallaba porque `ProviderManager` no tenía el método `get_available_models`.
- **Archivos implicados:** `apa/core/providers.py`
- **Criterio de aceptación:** El escalado de modelos funciona sin errores de atributo.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### A2 - Fix sandbox multi-archivo: estructura de carpetas en NAS
- **Prioridad:** X / Completada
- **Descripción:** Ajustar `generator.py` y `mcp/server.py` para inyectar dependencias y resolver imports entre archivos generados.
- **Archivos implicados:** `apa/agents/generator.py`, `apa/agents/corrector.py`
- **Criterio de aceptación:** Proyectos multi-archivo ejecutan correctamente en el NAS (los imports funcionan).
- **Dependencias:** T0.3
- **Estado:** [x] Completada

### A3 - Fix verificación de checkpoint en test_full.py
- **Prioridad:** X / Completada
- **Descripción:** Corregir falsos negativos en el test de integración relacionados con IDs hardcodeados y la lógica de verificación de dependencias.
- **Archivos implicados:** `apa/tests/test_full.py`
- **Criterio de aceptación:** `test_full.py` pasa las 5 verificaciones.
- **Dependencias:** T0.4
- **Estado:** [x] Completada

### A4 - T16 - Re-ejecución y cierre de integración
- **Prioridad:** X / Completada
- **Descripción:** Validar que tras los fixes A1-A3 el sistema completo pasa la batería de pruebas de integración.
- **Archivos implicados:** `apa/tests/test_full.py`
- **Criterio de aceptación:** 5/5 verificaciones OK.
- **Dependencias:** A1, A2, A3
- **Estado:** [x] Completada

### A5 - Inyección de dependencias en generación y corrección
- **Prioridad:** X / Completada
- **Descripción:** Modificar orquestador para inyectar el código de tareas dependientes en el prompt del generador/corrector.
- **Archivos implicados:** `apa/core/orchestrator.py`, `apa/agents/generator.py`
- **Criterio de aceptación:** Las tareas reciben el código de sus dependencias como contexto.
- **Dependencias:** T3.1
- **Estado:** [x] Completada

### A6 - Escalado de modelo por ranking ELO en corrector
- **Prioridad:** X / Completada
- **Descripción:** Modificar `corrector.py` para escalar a modelos significativamente más potentes (basado en ranking Arena) en intentos 2 y 3.
- **Archivos implicados:** `apa/agents/corrector.py`
- **Criterio de aceptación:** En intento 3 usa el mejor modelo disponible globalmente, no solo el siguiente en la lista.
- **Dependencias:** Arena
- **Estado:** [x] Completada

### A7 - Reducción de logs de módulos secundarios
- **Prioridad:** X / Completada
- **Descripción:** Configurar niveles de log (WARNING para módulos ruidosos) para limpiar la salida de terminal.
- **Archivos implicados:** `apa/core/orchestrator.py`, `apa/mcp/server.py`
- **Criterio de aceptación:** La terminal muestra principalmente eventos del orquestador y checkpoints.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### A8 - Mejora de generación con inyección de dependencias
- **Prioridad:** X / Completada
- **Descripción:** Añadir instrucción explícita en el prompt para que el código generado no use imports relativos, sino que copie la funcionalidad necesaria.
- **Archivos implicados:** `apa/agents/generator.py`, `apa/agents/corrector.py`
- **Criterio de aceptación:** El código generado para `utils_operations` no falla por `ModuleNotFoundError`.
- **Dependencias:** A5
- **Estado:** [x] Completada

### A9 - Diagnóstico de fallo persistente en utils_operations
- **Prioridad:** X / Completada
- **Descripción:** Identificar que el fallo era una combinación de spec ambigua y estrategia de corrección repetitiva.
- **Archivos implicados:** `apa/tests/test_full.py`, `apa/agents/corrector.py`
- **Criterio de aceptación:** Diagnóstico documentado y plan de acción claro.
- **Dependencias:** A8
- **Estado:** [x] Completada

### A10 - Ajuste de spec y mejora de estrategia de corrección
- **Prioridad:** X / Completada
- **Descripción:** Actualizar `SPEC_CONTENT` en `test_full.py` con criterios explícitos e implementar estrategia de corrección progresiva (`simplify`, `rewrite`).
- **Archivos implicados:** `apa/tests/test_full.py`, `apa/agents/corrector.py`
- **Criterio de aceptación:** `utils_operations` pasa el criterio `CRITERIO OK`.
- **Dependencias:** A9
- **Estado:** [x] Completada

## Bloque B: Robustez y Monitoreo

### B1 - Dashboard de monitoreo en interfaz web
- **Prioridad:** X / Completada
- **Descripción:** Añadir al panel de control métricas de uso de caché, tasa de éxito, costes y modelos utilizados.
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** El dashboard muestra estadísticas en tiempo real.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### B2 - Soporte de Ollama para tareas simples
- **Prioridad:** X / Completada
- **Descripción:** Integrar `OllamaProvider` en el router y priorizarlo para tareas de corrección simple (baja latencia).
- **Archivos implicados:** `apa/core/providers.py`, `apa/core/router.py`
- **Criterio de aceptación:** Tareas de corrección simples se ejecutan en modelos locales si están disponibles.
- **Dependencias:** T1.5
- **Estado:** [x] Completada

### B3 - Batería de specs de prueba ampliada
- **Prioridad:** X / Completada
- **Descripción:** Crear 5 specs de prueba adicionales (API REST, CLI, script de datos, etc.) para validar la robustez del planner y generador.
- **Archivos implicados:** `apa/tests/specs/*.md`
- **Criterio de aceptación:** 5/5 specs se ejecutan sin errores fatales.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

## Bloque C: Sistema de Skills

### C1 - Sistema de skills reutilizables (SkillsManager)
- **Prioridad:** X / Completada
- **Descripción:** Implementar `SkillsManager` para indexar y recuperar patrones de código (skills) por tipo de tarea y keywords.
- **Archivos implicados:** `apa/core/skills_manager.py`
- **Criterio de aceptación:** `find(task_description)` retorna el skill más relevante.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### C2 - Skills base: FastAPI, pytest, dataclasses, CLI
- **Prioridad:** X / Completada
- **Descripción:** Crear skills iniciales en Python para los patrones más comunes.
- **Archivos implicados:** `apa/skills/*.py`
- **Criterio de aceptación:** Las tareas de tipo API usan automáticamente el skill de FastAPI.
- **Dependencias:** C1
- **Estado:** [x] Completada

### C3 - Integración de skills en generator
- **Prioridad:** X / Completada
- **Descripción:** Modificar `GeneratorAgent` para inyectar el código del skill relevante en el prompt de generación.
- **Archivos implicados:** `apa/agents/generator.py`
- **Criterio de aceptación:** Tasa de éxito en primer intento mejora para tareas con skill asociado.
- **Dependencias:** C2
- **Estado:** [x] Completada

## Bloque D: Chatbot en Interfaz

### D1 - Endpoint /chat en interfaz web
- **Prioridad:** X / Completada
- **Descripción:** Crear endpoint POST `/chat` que reciba mensajes en lenguaje natural y los responda usando el router de APA.
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** El chat responde con contexto sobre el proyecto APA.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### D2 - Conversión conversación -> spec (SpecBuilder)
- **Prioridad:** X / Completada
- **Descripción:** Implementar `SpecBuilder` que analiza el historial del chat y extrae/estructura una spec de software.
- **Archivos implicados:** `apa/core/spec_builder.py`
- **Criterio de aceptación:** Una conversación ambigua genera preguntas para clarificar la spec.
- **Dependencias:** D1
- **Estado:** [x] Completada

### D3 - UI del chatbot en interfaz web
- **Prioridad:** X / Completada
- **Descripción:** Añadir una pestaña "Chat" en la interfaz con un área de conversación y botón "Convertir a Spec".
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** El usuario puede chatear y generar una spec automáticamente.
- **Dependencias:** D2
- **Estado:** [x] Completada

### D4 - Validador de completitud de spec
- **Prioridad:** X / Completada
- **Descripción:** `SpecBuilder.is_ready()` verifica que la spec tenga objetivo, inputs, outputs y criterio.
- **Archivos implicados:** `apa/core/spec_builder.py`
- **Criterio de aceptación:** El botón "Lanzar APA" se habilita solo cuando la spec está completa.
- **Dependencias:** D2
- **Estado:** [x] Completada

## Bloque E: Soporte Multi-Lenguaje (Base)

### E1 - language_detector.py (detección con perfiles)
- **Prioridad:** X / Completada
- **Descripción:** Implementar detector de lenguaje basado en heurísticas (keywords, extensión) para asignar un perfil a cada tarea.
- **Archivos implicados:** `apa/core/language_detector.py`
- **Criterio de aceptación:** `detect("Crear API con Express")` -> `javascript`.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### E2 - language_profiles.py (perfiles de lenguaje)
- **Prioridad:** X / Completada
- **Descripción:** Definir perfiles para Python, JavaScript, Bash, SQL, C++, React Native, Flutter (extensión, intérprete, plantilla de prompt).
- **Archivos implicados:** `apa/core/language_profiles.py`
- **Criterio de aceptación:** Cada perfil contiene la configuración necesaria para generar y ejecutar código en ese lenguaje.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### E3 - SkillsManager: filtrar por lenguaje
- **Prioridad:** X / Completada
- **Descripción:** Añadir campo `language` a los skills y modificar `find()` para filtrar primero por lenguaje.
- **Archivos implicados:** `apa/core/skills_manager.py`, `apa/skills/*.py`
- **Criterio de aceptación:** Una tarea de JavaScript no recibe un skill de Python.
- **Dependencias:** C1, E1
- **Estado:** [x] Completada

### E4 - NASConnector: execute_code multi-lenguaje
- **Prioridad:** X / Completada
- **Descripción:** Extender `execute_code()` para aceptar un parámetro `language` y usar el intérprete adecuado (`node`, `bash`, `g++`, etc.).
- **Archivos implicados:** `apa/mcp/server.py`
- **Criterio de aceptación:** El NAS ejecuta correctamente código JavaScript y Bash.
- **Dependencias:** E2
- **Estado:** [x] Completada

### E5 - GeneratorAgent: uso de perfiles de lenguaje
- **Prioridad:** X / Completada
- **Descripción:** Adaptar `GeneratorAgent` para usar el perfil de lenguaje correspondiente (prompt, extensión, validación).
- **Archivos implicados:** `apa/agents/generator.py`
- **Criterio de aceptación:** Genera código JavaScript válido cuando la tarea lo requiere.
- **Dependencias:** E1, E2
- **Estado:** [x] Completada

### E6 - Spec_parser y planner: propagar campo 'language'
- **Prioridad:** X / Completada
- **Descripción:** Añadir campo `language` a las tareas del plan para que el orquestador y agentes sepan qué perfil usar.
- **Archivos implicados:** `apa/core/spec_parser.py`, `apa/core/planner.py`
- **Criterio de aceptación:** El `plan.json` incluye el campo `language` para cada tarea.
- **Dependencias:** E1
- **Estado:** [x] Completada

### E7 - Skills base multi-lenguaje (Express, Jest, etc.)
- **Prioridad:** X / Completada
- **Descripción:** Crear skills para Express.js, React Native, Flutter, Bash scripting y SQL queries.
- **Archivos implicados:** `apa/skills/*.py`
- **Criterio de aceptación:** El sistema puede sugerir patrones para estos frameworks/lenguajes.
- **Dependencias:** E3
- **Estado:** [x] Completada

### E8 - Prueba de integración multi-lenguaje
- **Prioridad:** X / Completada
- **Descripción:** Crear `test_multilenguaje.py` que valide un proyecto con tareas en Python, JavaScript y Bash.
- **Archivos implicados:** `apa/tests/test_multilenguaje.py`
- **Criterio de aceptación:** Todas las tareas se ejecutan en el sandbox con el intérprete correcto.
- **Dependencias:** E4, E5, E6
- **Estado:** [x] Completada

## Bloque G: Precios y Ranking Arena

### G1 - Fix arena_fetcher.py (fuente híbrida HF -> GitHub)
- **Prioridad:** X / Completada
- **Descripción:** Corregir `ArenaFetcher` para priorizar GitHub (raw URL) sobre HuggingFace debido a cambios en la API de HF.
- **Archivos implicados:** `apa/core/arena_fetcher.py`
- **Criterio de aceptación:** El ranking se descarga correctamente sin errores 401.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### G2 - Fix parsing de precios en providers.py
- **Prioridad:** X / Completada
- **Descripción:** Corregir la extracción de `pricing` en `OpenRouterProvider` (la API devuelve strings como "0.0000015").
- **Archivos implicados:** `apa/core/providers.py`
- **Criterio de aceptación:** Los modelos de pago muestran un coste > 0.0 en el dashboard.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### G3 - price_estimator.py (estimación por similitud)
- **Prioridad:** X / Completada
- **Descripción:** Implementar `estimate_price_details()` que usa el modelo con precio conocido más cercano en calidad (ranking Arena) para estimar el coste (+20% margen).
- **Archivos implicados:** `apa/core/price_estimator.py`
- **Criterio de aceptación:** Modelos sin precio listado reciben una estimación con `source="similarity"`.
- **Dependencias:** G1, G2
- **Estado:** [x] Completada

### G4 - Integración de price_estimator en el dashboard
- **Prioridad:** X / Completada
- **Descripción:** Modificar el cálculo de costes en la interfaz para usar `price_estimator` y mostrar el margen de confianza.
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** El dashboard muestra costes estimados (marcados con ~) y reales.
- **Dependencias:** G3
- **Estado:** [x] Completada

### G5 - Documentación integral (BITACORA, WHITEPAPER, etc.)
- **Prioridad:** X / Completada
- **Descripción:** Crear la estructura inicial de `BITACORA.md`, `WHITEPAPER.md` y `COST_COMPARISON.md`.
- **Archivos implicados:** `docs/*.md`
- **Criterio de aceptación:** Los documentos existen y contienen la información base del proyecto.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

---

# 🚧 Tareas Pendientes, Actuales y Próximas

## Bloque V: Validación Estática Multi-Lenguaje

### V0 - Validación estática genérica en NASConnector
- **Prioridad:** X / Cancelada
- **Descripción:** Implementar `validate_statically(code, language)` en `NASConnector` que ejecute comandos de validación (`node --check`, `bash -n`, `g++ -fsyntax-only`, etc.) antes de la ejecución real.
- **Archivos implicados:** `apa/mcp/server.py`
- **Criterio de aceptación:** Código JavaScript inválido (`console.log("Hola);`) retorna `success: False` con un mensaje de error descriptivo sin intentar ejecutarlo.
- **Dependencias:** E4
- **Estado:** [x] Cancelada
### V6 - Integración de validación en GeneratorAgent
- **Prioridad:** X / Completada
- **Descripción:** Modificar `GeneratorAgent.generate_and_test()` para que, antes de llamar a `execute_code`, invoque `validate_statically`. Si falla, pasar directamente al corrector.
- **Archivos implicados:** `apa/agents/generator.py`
- **Criterio de aceptación:** Una tarea de JavaScript con error sintáctico no llega a ejecutarse en el NAS y se deriva al corrector.
- **Dependencias:** V0
- **Estado:** [x] Completada

### V7 – Validación híbrida adaptativa (local + remota segura)
- **Prioridad:** X / Completada
- **Descripción:** Implementar un mecanismo de validación que primero intente validación local (rápida, con herramientas del sistema). Si la herramienta local no está disponible, recurre a una validación remota aislada en el NAS (usando SFTP y SSH directo, sin execute_code ni write_file). Esto elimina la dependencia de herramientas locales sin sacrificar robustez.
- **Archivos implicados:** `apa/agents/generator.py`, `apa/mcp/server.py`
- **Criterio de aceptación:** Si `node` no está instalado localmente, una tarea JavaScript se valida remotamente en el NAS y el log muestra el mensaje de fallback. Las pruebas unitarias de `generator.py` y `server.py` pasan sin errores.
- **Dependencias:** V6
- **Estado:** [x] Completada

## Bloque Q: Calidad de Generación y Corrección

### Q1 - Refinamiento de prompts de generación
- **Prioridad:** X / Completada
- **Descripción:**     Descripción: Refactorizar language_profiles.py a funciones individuales y mejorar prompt_template de los 7 lenguajes soportados con reglas sintácticas estrictas. Crear skill express_api.py para JavaScript. Implementar nuevas anclas AST en el ensamblador. Crear test de validación integral. Meta: Refactorizar language_profiles.py a funciones modulares. Mejorar prompts de 7 lenguajes con reglas sintácticas explícitas (>500 caracteres cada uno). Crear skill express_api.py con 9 patrones. Implementar 4 anclas AST nuevas. Reducir tasa de error estimada en primera generación del ~35% al <15% para JavaScript y estableciendo baseline de calidad para los demás lenguajes.
- **Archivos implicados:** apa/core/language_profiles.py, apa/skills/express_api.py, tools/ensamblador_gui.py, apa/tests/test_q1_validacion_completa.py
- **Criterio de aceptación:** Tests de validación pasan (11/11). Todos los prompts tienen >500 caracteres con reglas explícitas. Skill express_api funcional. Anclas AST nuevas operativas.
- **Dependencias:** E2
- **Estado:** [x] Completada

### Q2 - Mejora del análisis de errores en CorrectorAgent
- **Prioridad:** X / Completada
- **Descripción:** Ampliar clasificación de errores por lenguaje (`missing_import`, `indentation_error`, etc.) y estrategias de corrección asociadas.
- **Archivos implicados:** `apa/agents/corrector.py`
- **Criterio de aceptación:** Clasifica correctamente >90% de una muestra de 50 errores reales.
- **Dependencias:** V0
- **Estado:** [x] Completada

## Bloque F: Autonomía y Resiliencia (Replanificación)

### F1 - replan_task() en Planner
- **Prioridad:** Media / Pendiente
- **Descripción:** Añadir método `replan_task(task, error_context)` que, ante un fallo irrecuperable, proponga descomponer la tarea en subtareas.
- **Archivos implicados:** `apa/core/planner.py`
- **Criterio de aceptación:** Ante un error de "lógica compleja", el planner sugiere dividir la tarea.
- **Dependencias:** T2.2
- **Estado:** [ ] Pendiente

### F2 - Integrar replanificación en orquestador
- **Prioridad:** Media / Pendiente
- **Descripción:** Modificar `Orchestrator._run_task()` para que, tras 3 intentos fallidos, llame a `replan_task` e inserte las nuevas subtareas en el plan.
- **Archivos implicados:** `apa/core/orchestrator.py`
- **Criterio de aceptación:** Una tarea fallida genera dinámicamente subtareas que se ejecutan en el mismo proyecto.
- **Dependencias:** F1
- **Estado:** [ ] Pendiente

### F5 - Advertencia de capacidad de modelos (Nivel 0)
- **Prioridad:** Media / Pendiente
- **Descripción:** Evaluar si los modelos disponibles (calidad/tipo) son adecuados para la tarea antes de ejecutar el plan.
- **Archivos implicados:** `apa/core/orchestrator.py`
- **Criterio de aceptación:** Muestra advertencia si se intenta generar C++ pero no hay modelos con capacidad `coding` en C++.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

## Bloque P: Empaquetado, Instalación y Documentación

### P1 - Script de instalación automática
- **Prioridad:** Alta / Pendiente
- **Descripción:** Crear `install.sh` y `install.ps1` para instalar dependencias (Python, Node, Docker) y configurar el entorno.
- **Archivos implicados:** `install.sh`, `install.ps1`
- **Criterio de aceptación:** Una máquina limpia queda lista para ejecutar APA tras ejecutar el script.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

### P2 - Imagen Docker de APA
- **Prioridad:** Alta / Pendiente
- **Descripción:** Crear `Dockerfile` y `docker-compose.yml` para levantar la interfaz y un sandbox local (eliminando dependencia del NAS).
- **Archivos implicados:** `Dockerfile`, `docker-compose.yml`
- **Criterio de aceptación:** `docker-compose up` inicia la interfaz en `localhost:8080`.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

### P6 - Plantilla .env comentada
- **Prioridad:** Alta / Pendiente
- **Descripción:** Crear `.env.example` con todas las variables de entorno documentadas y ejemplos.
- **Archivos implicados:** `.env.example`
- **Criterio de aceptación:** El archivo cubre todas las claves usadas en `settings.py`.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

## Bloque H: Experiencia de Usuario (UX)

### H1 - Modo revisión del plan antes de ejecutar
- **Prioridad:** Media / Pendiente
- **Descripción:** Pausar la ejecución tras generar el plan para que el usuario pueda aprobarlo o modificarlo.
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** Ventana modal con el plan y botones "Ejecutar" / "Cancelar".
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

### H2 - Registro visual enriquecido en tiempo real
- **Prioridad:** Media / Pendiente
- **Descripción:** Añadir pestaña "Progreso" con tabla de tareas actualizada vía SSE (estado, tiempo, modelo, resultado).
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** La tabla se actualiza en tiempo real durante la ejecución.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

### H5 - Mejora visual CSS profesional
- **Prioridad:** Media / Pendiente
- **Descripción:** Refinar el CSS de la interfaz para un aspecto más moderno y consistente (tema oscuro profesional).
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** Interfaz visualmente pulida y coherente.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

### H6 - Métrica de tiempo por lenguaje en dashboard
- **Prioridad:** Media / Pendiente
- **Descripción:** Registrar y mostrar el tiempo medio de ejecución por lenguaje (últimos 10 proyectos).
- **Archivos implicados:** `apa/core/usage_tracker.py`, `apa/interface/app.py`
- **Criterio de aceptación:** El dashboard incluye una sección "Tiempo medio por lenguaje".
- **Dependencias:** J1
- **Estado:** [ ] Pendiente

### H7 - Contexto de autoconocimiento en el chat
- **Prioridad:** Media / Pendiente
- **Descripción:** El chat de APA debe responder sobre sí mismo basándose en `BITACORA.md` y `WHITEPAPER.md`.
- **Archivos implicados:** `apa/interface/app.py`
- **Criterio de aceptación:** Al preguntar "¿Qué lenguajes soportas?", responde correctamente basado en la documentación real.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

## Bloque R: Refactorización y Ampliación de Proyectos

### R1 - Mejorar ProjectReader para specs de refactorización
- **Prioridad:** Media / Pendiente
- **Descripción:** Usar un LLM para analizar el código leído y generar una spec de refactorización de alta calidad.
- **Archivos implicados:** `apa/core/project_reader.py`
- **Criterio de aceptación:** La spec incluye secciones específicas de "Problemas identificados".
- **Dependencias:** T_REF.1
- **Estado:** [ ] Pendiente

## Bloque TS: TypeScript

### TS1 - Soporte para TypeScript
- **Prioridad:** Media / Pendiente
- **Descripción:** Añadir perfil `typescript`, skill base, ejecución con `ts-node` y validación con `tsc --noEmit`.
- **Archivos implicados:** `apa/core/language_profiles.py`, `apa/mcp/server.py`
- **Criterio de aceptación:** Una tarea de TypeScript se ejecuta correctamente en el NAS.
- **Dependencias:** V0
- **Estado:** [ ] Pendiente
## Bloque L – Aplicaciones de Escritorio (GUI)

### L1 – Refinamiento de prompts para GUIs
- **Prioridad:** ALta
- **Descripción:** Mejorar `prompt_template` en el perfil `python` y añadir un skill específico `tkinter_gui.py` con ejemplos de ventanas, layouts, botones y manejo de eventos. Incluir recordatorios de buenas prácticas (usar `StringVar`, evitar bloquear el hilo principal).
- **Archivos implicados:** `apa/skills/tkinter_gui.py` (nuevo), `apa/core/language_profiles.py`
- **Criterio de aceptación:** Al solicitar una GUI con tkinter, el prompt incluye un ejemplo mínimo funcional y advertencias sobre hilos. La tasa de errores sintácticos en primeras generaciones de GUI se reduce en un 30%.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente

### L2 – Skill para integración de componentes
- **Prioridad:** Alta
- **Descripción:** Crear skill `gui_integration.py` que enseñe a APA cómo estructurar una aplicación con múltiples módulos (parser, transcriptor, PDF) e integrarlos en una GUI funcional, usando hilos para tareas largas y actualizando la interfaz con `after()`.
- **Archivos implicados:** `apa/skills/gui_integration.py` (nuevo)
- **Criterio de aceptación:** APA es capaz de tomar módulos separados (parser, transcriptor) y generar un `main.py` que los orquesta con una GUI, usando `threading` y `after()` correctamente.
- **Dependencias:** L1
- **Estado:** [ ] Pendiente

### L3 – Validación estática específica para GUIs
- **Prioridad:** Alta
- **Descripción:** Extender `validate_statically` (V0) para que, en código Python que importe `tkinter`, ejecute `pylint` o `pyflakes` con reglas específicas (errores de sintaxis, variables no definidas, cadenas sin cerrar). Detectar errores comunes de GUI antes de ejecutar.
- **Archivos implicados:** `apa/mcp/server.py`
- **Criterio de aceptación:** Código con `tkinter` que contenga un `StringVar` mal usado o una cadena sin cerrar es rechazado antes de la ejecución, con un mensaje de error claro.
- **Dependencias:** V0
- **Estado:** [ ] Pendiente

### L4 – Manejo de hilos y concurrencia en GUI
- **Prioridad:** Media
- **Descripción:** Añadir al corrector estrategias para corregir bloqueos de interfaz. Si detecta `tkinter` y operaciones largas sin `threading`, sugerir envolver en hilos y usar `queue` para comunicar resultados.
- **Archivos implicados:** `apa/agents/corrector.py`
- **Criterio de aceptación:** Si una tarea de GUI falla por bloqueo, el corrector sugiere automáticamente mover la lógica pesada a un hilo.
- **Dependencias:** L2
- **Estado:** [ ] Pendiente

### L5 – Prueba de integración de GUI en test_full.py
- **Prioridad:** Media
- **Descripción:** Ampliar la suite con un test que genere una aplicación GUI simple (ej. un contador con botón) y verifique que se ejecuta sin errores de sintaxis y responde a eventos básicos (simulados).
- **Archivos implicados:** `apa/tests/test_full.py`
- **Criterio de aceptación:** El test genera una ventana simple, simula un clic y verifica que el contador se incrementa, todo dentro del sandbox del NAS.
- **Dependencias:** L3
- **Estado:** [ ] Pendiente

## Bloque AS – Motor de Ensamblaje Autónomo

### AS1 – assembler.py — Motor de ensamblaje puro
- **Prioridad:** X / Completada
- **Descripción:** Módulo `apa/core/assembler.py` con clase `Assembler` que encapsula: backup atómico del script target, inserción de imports sin duplicados, inserción de bloques atómicos por ancla (después/antes/reemplazar), ejecución del script ensamblado (local o NAS), captura de output y generación de resumen estructurado para el Planificador. Sin dependencias de Tkinter. Utilizable desde GUI, CLI y orquestador.
- **Archivos implicados:** `apa/core/assembler.py` (nuevo)
- **Criterio de aceptación:** `Assembler.assemble(script, blocks, anchor_map)` retorna `AssemblyResult(success, output, backup_path, summary)`. Tests unitarios pasan.
- **Dependencias:** Ninguna
- **Estado:** [x] Completada

### AS2 – Actualizar ensamblador GUI para usar assembler.py
- **Prioridad:** X / Completada
- **Descripción:** `tools/ensamblador_gui.py` pestaña 3 delega toda la lógica a `assembler.py`. La GUI solo gestiona entrada/salida visual. Botón "Aprobar" guarda en disco, marca tarea completada en el plan y genera resumen copiable para el Planificador. Botón "Rechazar" restaura backup automáticamente.
- **Archivos implicados:** `tools/ensamblador_gui.py`
- **Criterio de aceptación:** Flujo completo: pegar bloque → ancla → ensamblar → ejecutar → ver output → aprobar/rechazar. Sin pasos manuales intermedios.
- **Dependencias:** AS1
- **Estado:** [x] Completada

### AS3 – Nivel 2: SemiAutoAgent — ensamblaje y prueba de bloques completos
- **Prioridad:** Media
- **Descripción:** Agente que recibe una tarea del Planificador, genera el bloque atómico via LLM, llama a `assembler.py` para ensamblarlo, ejecuta validación individual y `test_full.py` si el Planificador lo indica. Devuelve resultado al Planificador sin intervención del Director.
- **Archivos implicados:** `apa/agents/semi_auto_agent.py` (nuevo), `apa/core/assembler.py`
- **Criterio de aceptación:** Tarea atómica planificada → bloque generado, ensamblado, ejecutado y resultado reportado al Planificador sin intervención humana.
- **Dependencias:** AS1, F1, F2
- **Estado:** [ ] Pendiente

### AS4 – Nivel 2: Validación automática en dos fases
- **Prioridad:** Media
- **Descripción:** El Planificador puede marcar una tarea con `validate: [individual, integration]`. `SemiAutoAgent` ejecuta primero el script ensamblado solo, y si pasa, ejecuta `test_full.py`. Ambos resultados van al resumen del Planificador.
- **Archivos implicados:** `apa/agents/semi_auto_agent.py`, `apa/core/assembler.py`
- **Criterio de aceptación:** Tarea con `validate: [individual, integration]` → dos outputs de validación en el resumen. Fallo en individual → no lanza integration.
- **Dependencias:** AS3
- **Estado:** [ ] Pendiente

### AS5 – Nivel 3: SelfImproveAgent — automejora autónoma
- **Prioridad:** Baja
- **Descripción:** APA recibe descripción en lenguaje natural del Director. Planifica internamente, genera bloques, los ensambla en su propio código, valida en dos fases y reporta resultado. El Director solo aprueba o rechaza el resultado final. Equivalente a lo que hacen los mejores agentes de codificación actuales, aplicado a la propia base de código de APA.
- **Archivos implicados:** `apa/agents/self_improve_agent.py` (nuevo), `apa/core/assembler.py`, `apa/core/planner.py`, `apa/agents/semi_auto_agent.py`
- **Criterio de aceptación:** "Añade validación estática para TypeScript" → APA genera plan, implementa, ensambla, valida y entrega resultado sin intervención manual.
- **Dependencias:** AS4, F1, F2
- **Estado:** [ ] Pendiente

### HF1 – HuggingFaceProvider (modelos gratuitos vía Inference API)
- **Prioridad:** Media
- **Descripción:** Crear un nuevo proveedor `HuggingFaceProvider` en `apa/core/providers.py` que utilice la Inference API gratuita de HuggingFace. Debe listar los modelos disponibles para el usuario (con su token HF) y permitir ejecutar inferencias sin coste, ampliando el pool de modelos gratuitos más allá de OpenRouter y Ollama.
- **Archivos implicados:** `apa/core/providers.py`, `apa/config/settings.py`
- **Criterio de aceptación:** `ProviderManager.health_check()` incluye a HuggingFace si el token HF está configurado. `get_all_models()` devuelve modelos de HuggingFace junto con los de otros proveedores.
- **Dependencias:** Ninguna
- **Estado:** [ ] Pendiente
