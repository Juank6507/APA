# GUÍA OPERATIVA — ENSAMBLAJE ATÓMICO APA v3.1
# Para uso del Director y referencia de los Agentes
# Fecha: 2026-04-26

---

## 1. LOS PARTICIPANTES Y SUS ROLES

### Director (Tú)
Coordinador del proceso. Tiene visión estratégica, poder de veto y es el único
que interactúa físicamente con la herramienta ensamblador_gui.py. No escribe
código ni decide estructuras — evalúa resultados y toma decisiones finales.

### Planificador (Agente 1)
Ingeniero de análisis. Recibe el archivo de código y una tarea en lenguaje
natural. Su trabajo es entender la estructura del archivo, decidir DÓNDE y
CÓMO aplicar cada cambio, y entregar un output estructurado que la herramienta
pueda parsear automáticamente. No escribe código funcional.

### Codificador (Agente 2)
Ingeniero de implementación. Recibe las instrucciones del Planificador y escribe
el código Python puro. No decide ubicaciones ni gestiona imports. Entrega
únicamente el bloque de código solicitado, sin envolturas ni explicaciones.

### Ensamblador (ensamblador_gui.py v3.1)
La herramienta que automatiza el proceso. Tiene tres pestañas:
- ⚡ Procesar Prompt: genera prompts blindados con fingerprint para el agente
- 📋 Plan de Mejoras: gestiona el backlog de tareas de APA
- 🧩 Ensamblador: recibe los outputs de ambos agentes y hace la cirugía

---

## 2. CAPACIDADES DEL ENSAMBLADOR v3.1

### 40 tipos de anclas disponibles en 5 categorías:

**Categoría AST (estructurales):**
    INICIO_ARCHIVO              → Insertar al principio del archivo
    FIN_ARCHIVO                 → Insertar al final del archivo
    FIN_CLASE:NombreClase       → Al final de una clase
    INICIO_CLASE:NombreClase    → Al inicio de una clase (tras su definición)
    ANTES_CLASE:NombreClase     → Justo antes de una clase
    REEMPLAZAR_CLASE:NombreClase → Reescribir una clase completa
    ANTES_FUNCION:nombre        → Justo antes de una función
    DESPUES_FUNCION:nombre      → Justo después de una función
    REEMPLAZAR_FUNCION:nombre   → Reescribir una función completa
    ANTES_METODO:Clase.metodo   → Antes de un método dentro de una clase
    DESPUES_METODO:Clase.metodo → Después de un método dentro de una clase
    REEMPLAZAR_METODO:Clase.metodo → Reescribir un método específico
    REEMPLAZAR_VARIABLE:nombre  → Reemplazar una asignación de variable

**Categoría posicional:**
    LINEA:N                     → En la línea N exacta
    DESPUES_LINEA:N             → Después de la línea N
    ANTES_LINEA:N               → Antes de la línea N
    RANGO_LINEAS:inicio-fin     → Reemplazar un rango de líneas
    LINEA_CONTIENE:texto        → En la línea que contiene ese texto
    DESPUES_LINEA_CONTIENE:texto → Después de la línea que contiene ese texto
    ANTES_LINEA_CONTIENE:texto  → Antes de la línea que contiene ese texto

**Categoría imports:**
    FIN_IMPORTS                 → Después del último import del archivo
    DESPUES_IMPORT:modulo       → Después del import de ese módulo
    ANTES_IMPORTS               → Antes del primer import

**Categoría bloques:**
    DESPUES_BLOQUE_IF:condicion → Después del bloque if con esa condición
    DESPUES_BLOQUE_FOR:variable → Después del bloque for con esa variable
    DESPUES_BLOQUE_TRY          → Después del bloque try/except
    DESPUES_BLOQUE_WITH:expr    → Después del bloque with con esa expresión

**Categoría decoradores y comentarios:**
    ANTES_DECORADOR:nombre      → Antes de una función con ese decorador
    DESPUES_DECORADOR:nombre    → Después de una función con ese decorador
    TODO:texto                  → En la línea del comentario TODO con ese texto
    DESPUES_COMENTARIO:texto    → Después de un comentario con ese texto

**Anclas contextuales compuestas:**
    EN_CLASE:Nombre|LINEA_CONTIENE:texto → Dentro de una clase, en línea que contiene texto

### Capacidades adicionales:
- Resaltado en rojo de líneas modificadas vs baseline
- Corrección automática de indentación del Codificador
- Detección y rechazo de código fantasma (solo comentarios/pass)
- Limpieza automática de backticks de markdown
- Imports deduplicados (no añade si ya existe)
- Validación de sintaxis Python tras cada ensamblaje
- Backup automático con timestamp antes de guardar
- Acumulación de múltiples tareas sobre el mismo script en memoria
- Detección de cambio de script entre tareas

---

## 3. PROMPTS INICIALES

### PROMPT A: AGENTE PLANIFICADOR

    Eres un Ingeniero de Software Senior. Tu rol es el de Agente Planificador de Ensamblaje Atómico del proyecto APA.
    
    ## FORMATO DE ENTREGA OBLIGATORIO
    
    Tu respuesta debe consistir ÚNICAMENTE en un bloque de código delimitado por CUATRO BACKTICKS. PROHIBIDO incluir texto explicativo, introducciones o despedidas fuera de ese bloque.
    
    PLANTILLA EXACTA:
    
        ## TAREA DE ENSAMBLAJE
        - SCRIPT: {ruta/archivo.py}
        - TAREA_ID: {ID}
        - ANCLA: {ANCLA_AST}
        - MODO_EJECUCION: {local | nas}
        
        ## BLOQUE
        
        # INSTRUCCIÓN PARA CODIFICADOR:
        # {descripción técnica de lo que debe implementar}
        # INDENTACIÓN: {0=código global | 4=método de clase}
        #
        # DATOS ESPECÍFICOS:
        # {incluir valores exactos del código original si aplica}
        
        ## IMPORTS_NUEVOS
        {nombre_modulo}
    
    **REGLA DE DATOS:** El Codificador NO tiene acceso al archivo original. Debes incluir los valores específicos en la sección DATOS ESPECÍFICOS.

### PROMPT B: AGENTE CODIFICADOR

    Eres un Ingeniero de Software Senior. Tu rol es el de Agente Codificador de Script Atómico del proyecto APA.
    
    ## FORMATO DE ENTREGA OBLIGATORIO
    
    Responde ÚNICAMENTE con código Python puro. Sin backticks, sin explicaciones.
    
    **REGLA DE CONTEXTO:** Si la instrucción NO incluye los valores específicos que necesitas, responde:
    
        FALTA CONTEXTO: Incluye los valores específicos del código original.
    
    No inventes valores. Solo usa lo que se te proporciona en la instrucción.

---

## 4. PASO A PASO DE OPERATORIA

### FASE 0 — Inicio de sesión (una sola vez por sesión)

**Paso 0.1** — Abrir la herramienta:
    python tools/ensamblador_gui.py

**Paso 0.2** — Verificar que la ruta raíz apunta a tu proyecto APA.
Si no la detectó automáticamente, usar el botón 📂 Examinar en Pestaña 1.

**Paso 0.3** — Iniciar chat con el Planificador pegando el PROMPT A completo.
Esperar confirmación: "Entendido. Adjunta el archivo y la primera tarea."

**Paso 0.4** — Iniciar chat con el Codificador pegando el PROMPT B completo.
Esperar confirmación: "Entendido. Envíame la instrucción."

---

### FASE 1 — Ciclo de tarea (repetir por cada tarea del plan)

**Paso 1.1 — Director → Planificador:**
Enviar la tarea en lenguaje natural + el archivo actual adjunto.

Ejemplo:
    "Adjunto device_manager.py. Tarea T3: Añadir clase Logger vacía antes
    de la función reset_system, y añadir import logging."

**Paso 1.2 — Planificador → Director:**
El Planificador entrega su output estructurado. Ejemplo real:

    ## TAREA DE ENSAMBLAJE
    - SCRIPT: apa/core/device_manager.py
    - TAREA_ID: T3
    - ANCLA: ANTES_FUNCION:reset_system
    - MODO_EJECUCION: local

    ## BLOQUE
    ```python
    # INSTRUCCIÓN PARA CODIFICADOR:
    # Crea clase Logger vacía (solo pass).
    # INDENTACIÓN: 0
    ```

    ## IMPORTS_NUEVOS
    logging

**Paso 1.3 — Director → Herramienta (Panel Izquierdo):**
En la pestaña 🧩 Ensamblador, pegar el output completo del Planificador
en el panel izquierdo "📥 Output del Planificador".

La herramienta parsea automáticamente y muestra en verde:
    ✅ script: device_manager.py | tarea: T3 | ancla: ANTES_FUNCION:reset_system

**Paso 1.4 — Director → Codificador:**
Copiar SOLO la sección ## BLOQUE del output del Planificador y enviarla
al chat del Codificador.

Lo que se envía al Codificador:
    ```python
    # INSTRUCCIÓN PARA CODIFICADOR:
    # Crea clase Logger vacía (solo pass).
    # INDENTACIÓN: 0
    ```

**Paso 1.5 — Codificador → Director:**
El Codificador entrega el bloque de código puro. Ejemplo:

    # ── TAREA T3: Logger ──

    class Logger:
        pass

**Paso 1.6 — Director → Herramienta (Panel Derecho):**
En el panel derecho "📝 Código del Codificador", pegar el código recibido.

**Paso 1.7 — Director → Herramienta:**
Pulsar 🚀 ENSAMBLAR + EJECUTAR.

La herramienta realiza automáticamente:
    1. Parsea el output del Planificador
    2. Carga el script desde disco (o usa la versión en memoria si es la misma tarea)
    3. Inyecta los imports nuevos (logging)
    4. Resuelve el ancla ANTES_FUNCION:reset_system via AST
    5. Aplica corrección de indentación automática
    6. Inserta el bloque class Logger en la posición correcta
    7. Valida sintaxis Python
    8. Ejecuta el script completo
    9. Muestra resultado con líneas modificadas en ROJO

---

### FASE 2 — Decisión del Director

**ESCENARIO A — Éxito técnico pero el Director no está satisfecho:**

El código funciona (✅ Returncode: 0) pero el Director quiere cambios.
El Director NO pulsa APROBAR.
El Director pulsa 📋 Copiar resultado.
El informe dice "Estado: ⏳ PENDIENTE".
El Director pega en el chat del Planificador añadiendo instrucciones:
    "Rehazlo, la clase Logger debe heredar de BaseLogger."
El Planificador ve PENDIENTE → NO actualiza su memoria → mantiene el archivo anterior.
El Director pulsa ↩ Deshacer para volver al estado anterior.
Repetir desde el Paso 1.2.

**ESCENARIO B — Todo correcto:**

El Director revisa el código (líneas en rojo muestran qué cambió).
Está satisfecho. Pulsa ✅ APROBAR.
La herramienta: hace backup automático, guarda en disco, limpia los paneles de input.
El Director pulsa 📋 Copiar resultado.
El informe dice "Estado: ✅ APROBADO".
El Director pega en el chat del Planificador.
El Planificador ve APROBADO → actualiza su mapa mental → confirma listo.

---

### FASE 3 — Sincronización (tras cada aprobación)

**Director → Planificador:**
Pegar el resumen copiado (que incluye estado APROBADO y líneas del script).

**Planificador responde:**
    MEMORIA ACTUALIZADA
    - Tarea T3: completada
    - device_manager.py: clase Logger añadida antes de reset_system, import logging añadido
    - Listo para siguiente tarea.

**Director → Pestaña Plan:**
Escribir T3 en el campo "ID de tarea" y pulsar "Marcar Completada".
La herramienta actualiza automáticamente PLAN_MEJORAS_APA.md.

---

### FASE 4 — Acumulación de tareas sobre el mismo script

El ensamblador mantiene el script en memoria entre tareas.
Si las tareas T3, T4 y T5 afectan al mismo archivo, NO hace falta cargar
el archivo entre tareas. La herramienta detecta automáticamente si el script
solicitado coincide con el que está en memoria y acumula los cambios.

Si la siguiente tarea es sobre un script distinto, la herramienta lo detecta,
limpia la memoria y carga el nuevo script automáticamente.

Para volver al estado guardado en disco en cualquier momento: botón 🔄 en la
vista del script.

Para descartar TODO y empezar de cero: botón 💣 Resetear.

---

## 5. REGLAS DE DECISIÓN PARA EL PLANIFICADOR

### Cuándo usar cada ancla

| Situación | Ancla correcta |
|---|---|
| Añadir código al final del archivo | FIN_ARCHIVO |
| Añadir un nuevo método a una clase | FIN_CLASE:NombreClase |
| Insertar una clase antes de una función existente | ANTES_FUNCION:nombre |
| Insertar una función después de otra | DESPUES_FUNCION:nombre |
| Modificar el interior de una función | REEMPLAZAR_FUNCION:nombre |
| Modificar un método específico dentro de una clase | REEMPLAZAR_METODO:Clase.metodo |
| Añadir solo imports | IMPORTS_NUEVOS + bloque python vacío |
| Insertar después del último import | FIN_IMPORTS |

### Regla de separación — nunca violar esto

El Planificador describe. El Codificador escribe.

Si el Planificador escribe código funcional en el bloque python, el Codificador
lo copiará en lugar de implementarlo correctamente. El error más común:

    ❌ MAL (T2 real):
    ## BLOQUE
    ```python
    # INSTRUCCIÓN: ...
    def reset_system():          ← código funcional en el bloque
        print('System Reset')
        return True
    ```

    ✅ BIEN:
    ## BLOQUE
    ```python
    # INSTRUCCIÓN: Crea función reset_system que imprime 'System Reset' y retorna True.
    # INDENTACIÓN: 0
    ```

---

## 6. REGLAS DE DECISIÓN PARA EL CODIFICADOR

### La compuerta de entrada

Antes de escribir cualquier cosa:
¿Hay una descripción explícita de función, método o clase en la instrucción?

    - "Crea función X" → SÍ → escribir
    - "Crea clase Y"   → SÍ → escribir
    - (bloque vacío)   → NO → no escribir nada
    - "Añade import"   → NO → no escribir nada (el sistema lo hace)

### Lo que NUNCA debe aparecer en el output del Codificador

- Backticks (``` python ```)
- Líneas import
- Texto explicativo antes o después del código
- Confirmaciones ("Aquí el código:", "Tarea completada:")
- Comentarios de instrucción reproducidos (# INSTRUCCIÓN:...)

---

## 7. SEÑALES DE ERROR Y CÓMO RESOLVERLAS

| Señal en la herramienta | Causa probable | Acción |
|---|---|---|
| ⚠️ Faltan: Falta campo ANCLA | El Planificador omitió el campo ANCLA | Pedir al Planificador que lo incluya |
| ❌ Ancla no encontrada | La función/clase del ancla no existe en el script | Verificar nombre exacto con el Planificador |
| ❌ SyntaxError línea N | El Codificador entregó código con error | Copiar el error y enviarlo al Codificador para corrección |
| Script diferente detectado | La tarea actual es sobre un archivo distinto | Normal — la herramienta limpia y recarga automáticamente |
| ⚠️ FALTA CONTEXTO (Planificador) | El Planificador perdió el rastro del archivo | Adjuntar el archivo actualizado al chat del Planificador |
| Líneas en rojo incorrectas | El Codificador añadió código no pedido | Usar ↩ Deshacer y corregir la instrucción al Codificador |
| (sin output) en ejecución | El script es un módulo, no produce output directo | Normal — Returncode 0 confirma que carga sin errores |

---

## 8. FLUJO COMPLETO RESUMIDO (REFERENCIA RÁPIDA)

```
INICIO DE SESIÓN
    → Abrir herramienta
    → Iniciar Planificador con PROMPT A
    → Iniciar Codificador con PROMPT B

POR CADA TAREA:
    Director  →[tarea en lenguaje natural + archivo]→  Planificador
    Planificador  →[output estructurado]→  Director
    Director  →[pega output Planificador en panel izquierdo]→  Herramienta
    Director  →[sección BLOQUE del Planificador]→  Codificador
    Codificador  →[código puro]→  Director
    Director  →[pega código en panel derecho]→  Herramienta
    Director  →[pulsa 🚀 ENSAMBLAR + EJECUTAR]→  Herramienta

    SI RESULTADO OK Y DIRECTOR APRUEBA:
        → Pulsar ✅ APROBAR
        → Pulsar 📋 Copiar resultado
        → Pegar en Planificador (actualiza memoria)
        → Marcar tarea completada en Pestaña Plan

    SI RESULTADO NO SATISFACE:
        → NO pulsar APROBAR
        → Pulsar 📋 Copiar resultado
        → Pegar en Planificador con instrucciones de corrección
        → Pulsar ↩ Deshacer
        → Repetir desde el Planificador
```

---

*Guía operativa v3.1 — Sistema de Ensamblaje Atómico APA*
*Última actualización: 2026-04-26*