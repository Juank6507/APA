# APA – Bitácora del Proyecto

## Resumen ejecutivo

APA (Agente de Programación Autónoma) es un sistema que recibe especificaciones en lenguaje natural, las planifica en tareas atómicas, genera código en múltiples lenguajes, lo ejecuta en un sandbox real (NAS), corrige errores automáticamente y aprende de sus éxitos mediante un sistema de auto‑skills. A fecha de abril de 2026, el sistema soporta 7 lenguajes (Python, JavaScript, Bash, SQL, C++, React Native y Flutter) y su suite de integración pasa todas las verificaciones.

## Hitos del desarrollo
<!-- AUTO-HITOS-START -->
_Sin hitos completados aún_
<!-- AUTO-HITOS-END -->

| Bloque | Descripción | Estado | Fecha aprox. |
|--------|-------------|--------|--------------|
| Fase 0–4 | Infraestructura base, router multi‑proveedor, orquestador, agentes, interfaz web | ✅ | Marzo 2026 |
| Bloque C | Sistema de skills con auto‑aprendizaje (C1–C9) | ✅ | Abril 2026 |
| Bloque E | Multi‑lenguaje base (Python, JS, Bash, SQL) | ✅ | Abril 2026 |
| Bloque F | Soporte para C++ (perfil, compilación, skill) | ✅ | Abril 2026 |
| Bloque G | Móviles: React Native y Flutter (perfiles, skills) | ✅ | Abril 2026 |
| Estabilización | Tolerancia SSH (H2), logging mejorado (H3) | ✅ | Abril 2026 |

## Arquitectura general

APA se compone de cuatro capas principales:

1. **Interfaz de usuario**: FastAPI en `localhost:8080`. Permite chat, carga de especificaciones, dashboard de métricas y análisis de proyectos.
2. **Planificación y orquestación**: `spec_parser.py` y `planner.py` convierten la especificación en un plan de tareas atómicas. `orchestrator.py` coordina la ejecución, maneja dependencias y checkpointing.
3. **Agentes de ejecución**: `GeneratorAgent` genera código usando LLMs y lo ejecuta en el sandbox. `CorrectorAgent` analiza fallos y corrige (hasta 3 intentos).
4. **Sandbox multi‑lenguaje**: `NASConnector` ejecuta el código en un contenedor Docker alojado en un NAS Synology, accedido vía SSH.

Capas transversales: `Router` LLM, `SkillsManager`, `UsageTracker`, `Checkpoint`, `LLMCache`.

## Paralelización y sistema multi‑agente

Una de las características más potentes de APA es su capacidad para ejecutar **múltiples tareas en paralelo** cuando no existen dependencias entre ellas. El `Orchestrator` analiza el grafo de dependencias y lanza simultáneamente todas las tareas independientes utilizando un **pool de workers** (por defecto, 3 workers concurrentes).

Cada tarea es manejada por un **agente generador** que trabaja de forma asíncrona. Si una tarea falla, entra en acción el **agente corrector**, que puede operar en paralelo con otras tareas exitosas. Este diseño multi‑agente permite que APA:

- Reduzca drásticamente el tiempo total de ejecución en proyectos con múltiples archivos independientes.
- Mantenga la robustez: un fallo en una tarea no bloquea la ejecución de las demás (a menos que exista dependencia).
- Escale fácilmente añadiendo más workers según la capacidad del hardware.

## Autonomía y resiliencia

### Checkpointing y reanudación ante interrupciones

Cada vez que una tarea se completa (con éxito o fallo irrecuperable), el `Orchestrator` guarda el estado completo del plan en `specs/<project_id>/plan.json`. Este mecanismo de **checkpointing** permite que, si el proceso de APA se interrumpe (por caída del sistema, desconexión de red, o cierre manual), al reiniciar el proyecto **se reanude exactamente desde la última tarea completada**, sin repetir el trabajo ya realizado.

El sistema registra:
- Tareas completadas.
- Código generado para cada tarea.
- Dependencias resueltas.

Esto es especialmente valioso en proyectos largos o cuando se utilizan modelos de pago, ya que evita el desperdicio de tokens.

### Escalamiento de modelos en el CorrectorAgent

Cuando una tarea falla, el `CorrectorAgent` analiza el error y, si el fallo persiste, **escala a modelos más potentes** en intentos sucesivos. Por ejemplo:

- Intento 1: modelo rápido/económico (ej. `qwen/qwen3-coder:free`).
- Intento 2: modelo balanceado.
- Intento 3: modelo de alta capacidad (ej. `google/gemma-4-26b`).

Esta estrategia maximiza la probabilidad de corrección sin incurrir en costes excesivos en fallos triviales.

### Tolerancia a fallos y replanificación (en desarrollo)

El plan de mejoras incluye la capacidad de **replanificar** una tarea cuando los 3 intentos de corrección fallan. El `Planner` analizará el error y descompondrá la tarea en subtareas más simples, en lugar de simplemente marcarla como fallida. Esto aumentará aún más la autonomía del sistema.

## Flujo de trabajo

1. El usuario proporciona una especificación (chat o archivo markdown multi‑archivo).
2. `spec_parser` extrae archivos, dependencias y lenguaje.
3. `planner` genera `plan.json` con tareas atómicas.
4. `orchestrator` ejecuta las tareas en orden (respetando dependencias) e **inyecta el código de las tareas ya completadas** en el prompt de las tareas dependientes.
5. Las tareas independientes se ejecutan **en paralelo** gracias al pool de workers.
6. El código se valida y ejecuta en el NAS. Si el criterio de aceptación se cumple, la tarea se marca como completada y se guarda checkpoint.
7. Si falla, el `CorrectorAgent` analiza el error, escala el modelo si es necesario y reintenta (hasta 3 veces).
8. Al finalizar, se genera `GENERATED_CODE.md` y `COST_REPORT.md`.
9. Opcionalmente, se extraen nuevos skills automáticamente y se almacenan en `apa/skills/`.

## Lenguajes soportados

<!-- AUTO-LANGUAGES-START -->
| Lenguaje | Extensiones | Intérprete |
|----------|-------------|------------|
| `python` | `.py, .pyw` | `python3` |
| `javascript` | `.js, .mjs, .cjs` | `node` |
| `bash` | `.sh, .bash` | `bash` |
| `sql` | `.sql` | `sqlite3` |
| `cpp` | `.cpp, .cc, .cxx, .h, .hpp` | `g++` |
| `react-native` | `.js, .jsx, .ts, .tsx` | `node` |
| `dart` | `.dart` | `/opt/flutter/bin/dart` |
<!-- AUTO-LANGUAGES-END -->

## Estadísticas del proyecto

<!-- AUTO-STATS-START -->
- **Líneas de código**: 22,320
- **Archivos Python**: 85
- **Total archivos**: 377
<!-- AUTO-STATS-END -->

## Tecnologías clave

- **Python 3.11** + FastAPI + Uvicorn
- **LLMs**: OpenRouter, Anthropic, OpenAI, Groq, Together, Ollama (local)
- **Paramiko** para SSH al NAS
- **Docker** en NAS Synology para sandbox aislado
- **SQLite** para caché, checkpoint y tracking de uso
- **HuggingFace `datasets`** para rankings Arena

## Próximos pasos
<!-- AUTO-PROXIMOS-START -->
_No hay tareas pendientes registradas_
<!-- AUTO-PROXIMOS-END -->

- Validación estática para todos los lenguajes (Bloque V).
- Empaquetado como imagen Docker y binarios ejecutables (Bloque P).
- Soporte para TypeScript.
- Implementación de replanificación ante fallos irrecuperables (Bloque F).

<!-- AUTO-UPDATED-START -->
*Última actualización automática: 2026-04-26 16:16:47*
<!-- AUTO-UPDATED-END -->