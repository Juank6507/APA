# APA – Análisis comparativo de costes  
## APA vs. LLMs directos vs. desarrollo tradicional

---

## Metodología

Para evaluar el impacto económico de APA, comparamos el coste total de desarrollar un proyecto de software típico en tres escenarios:

1. **Usando APA** (automatización completa con generación, corrección y sandbox integrados).
2. **Pagando tokens directamente a proveedores de LLM** (sin la capa de orquestación de APA, requiriendo intervención humana para pruebas y correcciones).
3. **Desarrollo tradicional pre‑IA** (programadores, servidores, tiempo).

El proyecto de referencia es **"Calculadora modular con validación y caché"**, el mismo que utiliza la suite de integración de APA (`test_full.py`). Este proyecto consta de 4 tareas atómicas, genera unos 50.000 tokens entre prompt y completion, y requiere pruebas en múltiples archivos.

Los costes de personal e infraestructura se basan en estimaciones conservadoras del mercado español/europeo en 2026.

---

## Precios actuales de referencia

<!-- AUTO-PRICES-TABLE-START -->
| Modelo | Prompt ($/1k) | Completion ($/1k) | Fuente | Confianza |
|--------|---------------|-------------------|--------|-----------|
| `openai/gpt-4o` | 0.002500 | 0.010000 | openrouter | 1.00 |
| `anthropic/claude-opus-4.7` | 0.005000 | 0.025000 | openrouter | 1.00 |
| `meta-llama/llama-3-70b` | 0.000612 | 0.000888 | similarity | 1.00 |
| `google/gemini-1.5-pro` | 0.036000 | 0.216000 | similarity | 1.00 |
| `qwen/qwen2.5-coder-32b` | 0.000792 | 0.001200 | similarity | 1.00 |
<!-- AUTO-PRICES-TABLE-END -->

---

## Escenario 1: Usando APA

APA optimiza el uso de tokens mediante:
- Prompts refinados y reutilización de respuestas (caché LLM).
- Corrección automática que reduce iteraciones fallidas.
- Paralelización de tareas independientes.

### Costes directos (tokens)

| Concepto | Cantidad | Precio unitario (por 1k tokens) | Coste |
|----------|----------|---------------------------------|-------|
| Tokens de prompt | 30.000 | $0.005 (estimado APA) | $0.15 |
| Tokens de completion | 20.000 | $0.025 (estimado APA) | $0.50 |
| **Subtotal tokens** | | | **$0.65** |
| Factor de infraestructura (12%) | | | $0.08 |
| **Total tokens** | | | **$0.73** |

*Nota: Los precios unitarios corresponden a la estimación por similitud que APA aplica a modelos sin precio público (margen del 20% incluido). Para modelos con precio real (ej. GPT‑4o), el coste sería aún más preciso.*

### Costes indirectos

| Concepto | Coste |
|----------|-------|
| Electricidad NAS (4h de uso a 20W) | $0.01 |
| Tiempo de supervisión humana | 5 minutos ($5.00/h) | $0.42 |
| **Total indirectos** | **$0.43** |

### Tiempo total de ejecución

- **APA**: 8 minutos (ejecución automatizada en segundo plano).
- Supervisión humana: 5 minutos para revisión final.

**Coste total Escenario 1 (APA): $0.73 + $0.43 = $1.16**  
**Tiempo total efectivo: 13 minutos**

---

## Escenario 2: Pagando tokens directamente a proveedores (sin APA)

En este escenario, un desarrollador utiliza un chat LLM (ej. ChatGPT, Claude) para generar el código, pero debe:
- Copiar y pegar manualmente cada archivo.
- Probar el código en su máquina local.
- Volver a preguntar al LLM si hay errores.
- Resolver dependencias entre archivos por sí mismo.

La falta de optimización de prompts y de corrección automática **aumenta el número de iteraciones** y, por tanto, el consumo de tokens.

### Costes directos (tokens)

| Concepto | Cantidad | Precio unitario (OpenRouter real) | Coste |
|----------|----------|-----------------------------------|-------|
| Tokens de prompt | 60.000 | $0.005 | $0.30 |
| Tokens de completion | 40.000 | $0.025 | $1.00 |
| **Total tokens** | | | **$1.30** |

*Nota: Se estima un 100% más de tokens debido a iteraciones adicionales y falta de caché.*

### Costes indirectos

| Concepto | Coste |
|----------|-------|
| Tiempo de desarrollador (1 hora) | $30.00 |
| **Total indirectos** | **$30.00** |

### Tiempo total

- Interacción con LLM + pruebas manuales: 1 hora.

**Coste total Escenario 2 (LLM directo): $1.30 + $30.00 = $31.30**  
**Tiempo total: 1 hora**

---

## Escenario 3: Desarrollo tradicional (pre‑IA)

Antes de la explosión de la IA generativa, un proyecto como este habría requerido:

- Un programador junior para escribir el código.
- Un entorno de desarrollo local o en la nube.
- Pruebas manuales y depuración.

### Costes directos

| Concepto | Cantidad | Coste unitario | Coste |
|----------|----------|----------------|-------|
| Horas de programación | 8 horas | $30/h | $240.00 |
| Horas de prueba/depuración | 4 horas | $30/h | $120.00 |
| **Total personal** | | | **$360.00** |

### Costes de infraestructura

| Concepto | Coste |
|----------|-------|
| Servidor de desarrollo (VM en la nube, 1 día) | $2.00 |
| Electricidad / gastos generales | $1.00 |
| **Total infraestructura** | **$3.00** |

### Tiempo total

- 1.5 días laborables (12 horas efectivas).

**Coste total Escenario 3 (Tradicional): $360.00 + $3.00 = $363.00**  
**Tiempo total: 12 horas**

---

## Tabla comparativa

| Métrica | APA | LLM Directo | Desarrollo Tradicional |
|---------|-----|-------------|------------------------|
| Coste tokens | $0.73 | $1.30 | N/A |
| Coste personal | $0.42 | $30.00 | $360.00 |
| Coste infraestructura | $0.01 | $0.00 | $3.00 |
| **Coste total** | **$1.16** | **$31.30** | **$363.00** |
| Tiempo total | 13 min | 1 h | 12 h |
| **Ahorro vs. tradicional** | **99.7%** | **96.3%** | – |

---

## Conclusiones

1. **APA reduce el coste en más de un 99%** comparado con el desarrollo tradicional, y en un **96%** frente al uso directo de LLMs sin orquestación.
2. El ahorro no solo es económico, sino de **tiempo**: lo que antes tomaba días, ahora toma minutos.
3. La optimización de tokens y la caché de APA minimizan el gasto en APIs, haciendo viable el uso de modelos de pago incluso para proyectos pequeños.
4. La automatización de la corrección y la ejecución en sandbox **eliminan el coste de personal cualificado** para tareas repetitivas, permitiendo a los equipos centrarse en labores de mayor valor.

APA no es solo una herramienta de generación de código: es un **multiplicador de productividad** con un retorno de inversión inmediato.

---

*Los cálculos se basan en datos reales de ejecución del proyecto de prueba de APA (abril 2026) y en tarifas estándar del sector. Las estimaciones de tokens para el Escenario 2 son conservadoras; en la práctica, el número de iteraciones podría ser aún mayor.*

<!-- AUTO-UPDATED-START -->
*Precios actualizados: 2026-04-26 16:16:47*
<!-- AUTO-UPDATED-END -->