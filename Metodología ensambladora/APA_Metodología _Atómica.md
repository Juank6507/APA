
# METODOLOGÍA DE ENSAMBLAJE ATÓMICO APA (v7.0)

## 1. Filosofía

El desarrollo se realiza mediante **cirugía de código precisa**. No se reescribe el archivo completo; se inyectan o reemplazan bloques atómicos (funciones, clases) en puntos exactos del archivo existente mediante **Anclas AST** (Árbol de Sintaxis Abstracta).

El sistema garantiza:
- **Precisión estructural** mediante anclas AST (no números de línea)
- **Indentación correcta** aplicada automáticamente por el Ensamblador
- **Prevención de duplicados** en imports
- **Validación automática** de sintaxis antes de ejecutar

---

## 2. Roles

### Director (Tú)
- Posee la visión estratégica
- Coordina a los agentes
- Valida resultados
- Único que interactúa con la herramienta `ensamblador_gui.py`
- **Poder de veto:** si el código funciona técnicamente pero no le convence, puede rechazarlo

### Planificador (Agente 1)
    -Ingenierio de software especializado en planificación de tareas
    -Descomponer objetivos en tareas atómicas
    -Generar instrucciones al codificador que lo ayuden a genera un código de calidad que cumpla con el objetivo y estádares 
    -Entregar todos los output cuadros de código
    -Es el único de los agentes que ve el código existente y lo pide si no lo tiene o lo tiene obsoletos en memoria
     
### Codificador (Agente 2)
- Ingeniero de Implementación
- Función: **Escribir el Bloque Atómico**
- No decide la ubicación
- Define **QUÉ** hace el código
- El Ensamblador corrige su indentación si es incorrecta

### Agente Asistente (Chat)
- Función: **Ejecutar y Coordininar**
- Descompone objetivos en tareas atómicas
- Genera código completo cuando tiene contexto
- Produce informes y documentos
- Gestiona flujo entre Director y agentes externos

---

## 3. Flujo de Trabajo

### PASO A: Inicio de Sesión (Solo una vez)

1. Iniciar chat con **Planificador** usando Prompt A
2. Iniciar chat con **Codificador** usando Prompt B

### PASO B: Ciclo de Tarea

1. **Director → Agente Asistente:** Envía objetivo estratégico
2. **Agente Asistente:** Según el plan trabajo del director busca la tarea a realizarse y se la entrega al director en foema de lenguaje natural
3. **Director → Planificador:** Envía tarea al planificador
4. **Planificador → Director:** Descompone la tarea en bloques y entrega OUTPUT ESTRUCTURADO (delimitado por 4 backticks)
5. **Director → Ensamblador:** Pega output del planificador en panel superior
6. **Director → Codificador:** Envía output del planificador estructurado en`## BLOQUEs`
7. **Codificador → Director:** Devuelve código Python puro
8. **Director → Ensamblador:** Pega código en panel inferior
9. **Ensamblador:** Pulsa `🚀 ENSAMBLAR + EJECUTAR`

### PASO C: Decisión del Director

| Escenario      | Acción                                | Resultado                                       |
|----------------|---------------------------------------|-------------------------------------------------|
| **Rechazo**    | NO APROBAR. Pulsar "Copiar resultado" | Planificador NO actualiza memoria               |
| **Aprobación** | Pulsar `✅ APROBAR`                  | Archivo guardado, Planificador actualiza memoria|

## 4. Anclas AST Implementadas

### Anclas Originales

| Ancla                       | Cuándo usarla                   | Ejemplo                                  |
|-----------------------------|---------------------------------|------------------------------------------|
| `INICIO_ARCHIVO`            | Imports y código inicial        | `ANCLA: INICIO_ARCHIVO`                  |
| `FIN_ARCHIVO`               | Código al final del archivo     | `ANCLA: FIN_ARCHIVO`                     |
| `FIN_CLASE:Nombre`          | Nuevo método al final de clase  | `ANCLA: FIN_CLASE:DeviceManager`         |
| `ANTES_FUNCION:nombre`      | Insertar ANTES de una función   | `ANCLA: ANTES_FUNCION:reset_system`      |
| `DESPUES_FUNCION:nombre`    | Insertar DESPUÉS de una función | `ANCLA: DESPUES_FUNCION:__init__`        |
| `REEMPLAZAR_FUNCION:nombre` | Reescribir función existente    | `ANCLA: REEMPLAZAR_FUNCION:scan_devices` |

### Anclas Nuevas (v7.0)

| Ancla                        | Cuándo usarla                    | Ejemplo                         |
|------------------------------|----------------------------------|---------------------------------|
| `INSERTAR_ANTES_MAIN`        | Insertar código antes del bloque | `ANCLA: INSERTAR_ANTES_MAIN`    |
|                              |`if __name__`                     |                                 |
| `REEMPLAZAR_BLOQUE_MAIN`     | Reemplazar todo el bloque main   | `ANCLA: REEMPLAZAR_BLOQUE_MAIN` |
|                              |                                  | LANGUAGE_PROFILES               |       
| `REEMPLAZAR_VARIABLE:nombre` | Reemplazar variable global       |`ANCLA: REEMPLAZAR_VARIABLE:`    |
| `ARCHIVO_NUEVO`              | Crear archivo desde cero         | `ANCLA: ARCHIVO_NUEVO`          |

**Reglas de elección:**
- Insertar algo nuevo junto a algo existente → `ANTES_FUNCION` o `DESPUES_FUNCION`
- Modificar el interior de algo existente → `REEMPLAZAR_FUNCION`
- Insertar antes del main → `INSERTAR_ANTES_MAIN`
- Crear archivo nuevo → `ARCHIVO_NUEVO`
- **NUNCA** usar `REEMPLAZAR_FUNCION` para insertar código adicional

---

## 5. Resumen Prompts Iniciales (Verlo conpleto en el documento existente)

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

## 6. Reglas de Oro

1. **Sin Archivo, No Hay Plan:** El Planificador nunca trabaja sin ver el código (o tenerlo en memoria).

2. **Anclaje Lógico:** Preferir inserción al final de clases/bloques funcionales antes que en medio.

3. **Limpieza de Output:** El Codificador nunca debe incluir comentarios de instrucción en su código final.

4. **Veto de Calidad:** Un "Éxito técnico" no es lo mismo que una "Aprobación". Solo la aprobación cambia el estado real del proyecto.

5. **Indentación Garantizada:** El Ensamblador corrige automáticamente la indentación incorrecta del Codificador.

6. **Sin Duplicados:** El Ensamblador detecta y evita imports duplicados.

7. **Datos Específicos:** El Planificador SIEMPRE debe incluir los valores específicos del código original para que el Codificador no alucine.

---

## 7. Búsqueda de Plan

El ensamblador busca archivos de plan automáticamente usando el patrón `PLAN_*.md`:

- Busca en el directorio raíz del proyecto
- Busca en subdirectorios si no encuentra en raíz
- Ordena por fecha de modificación (más reciente primero)
- Carga automáticamente el plan más reciente

---

## 8. Posicionamiento Automático de Scroll

Al cargar el plan, el ensamblador posiciona automáticamente el scroll en la tarea prioritaria siguiendo este orden:

1. **Actual** - Tarea marcada con `/ Actual` en Prioridad
2. **Próxima** - Tarea marcada con `/ Próxima` en Prioridad
3. **Alta** - Primera tarea con prioridad `Alta` y estado pendiente

---

## 9. Completar Tareas

El sistema permite marcar tareas como completadas:

1. Ingresar ID de tarea (ej: Q1.2)
2. El sistema busca la tarea en el plan
3. Modifica el estado de `[ ]` a `[x]`
4. Actualiza la prioridad a `X / Completada`
5. Refresca la vista y posiciona el scroll en la tarea completada

---

## 10. Lecciones Aprendidas

| Problema                                  | Solución                                   |
|-------------------------------------------|--------------------------------------------|
| Ancla vacía o números de línea cambiantes | Anclas AST basadas en nombres              |
| Indentación incorrecta del Codificador    | Ensamblador detecta duplicación y corrige  |
| Código duplicado en REEMPLAZAR            | Eliminar función antigua antes de insertar |
| Codificador alucina valores               | Regla de DATOS ESPECÍFICOS obligatoria     |
| `ANTES_FUNCION` sin separación            | Línea en blanco automática por debajo      |
| Import duplicado                          | Verificar existencia antes de añadir       |
| Plan no encontrado                        | Búsqueda flexible con patrón PLAN_*.md     |
| Scroll siempre al inicio                  | Posicionamiento automático por prioridad   |

---

## 11. Pruebas de Validación (v7.0)

| #  | Prueba                          | Descripción                           | Estado   |
|----|---------------------------------|---------------------------------------|----------|
| B1 | Función con decorador           | `@property` manejado correctamente    | ✅ PASS |
| C3 | Import duplicado                | No duplica imports existentes         | ✅ PASS |
| A1 | `ANTES_FUNCION` primera función | Inserta correctamente al principio    | ✅ PASS |
| E1 | Acumulación + Undo múltiple     | 3 tareas acumuladas, 3 undos exitosos | ✅ PASS |
| B2 | Función `async def`             | Soporte para funciones asíncronas     | ✅ PASS |
| D3 | Líneas vacías intermedias       | Conserva estructura con espacios      | ✅ PASS |
| F1 | Script no existe                | Mensaje de error claro, no crashea    | ✅ PASS |
| G1 | Ancla INSERTAR_ANTES_MAIN       | Posiciona antes del bloque main       | ✅ PASS |
| G2 | Ancla REEMPLAZAR_VARIABLE       | Reemplaza variable global             | ✅ PASS |
| G3 | Ancla ARCHIVO_NUEVO             | Crea archivo desde cero               | ✅ PASS |

---

## 12. Archivos del Sistema

| Archivo                         | Descripción                                |
|---------------------------------|--------------------------------------------|
| `ensamblador_gui.py`            | Herramienta gráfica (v3.0+) con parser AST |
| `prompt_gui.py`                 | Prototipo original de referencia           |
| `apa/core/language_profiles.py` | Perfiles de lenguaje con prompts mejorados |
| `apa/skills/express_api.py`     | Skill para Express.js                      |
| `APA_Metodología_Atómica.md`    | Este documento                             |

## 13. Resumen de la metodología

Se trabaja con agentes planificador (p) y codificador (c) con el objetivo de perfilar el trabajo del ensamblador_gui.py. El p descompone una tarea en partes si está trabando sobre un código determinado lo pide y le entrega al c la tarea dividida en la partes que antes desglosó con un formato determinado y cada tarea de esas tiene su ancla para ser insertada por el ensamblador (e) en el lugar correcto, con la identación apropiada y también le menciona las dependencias de cada tarea. El c recibe cada bloque de tareas implementa sus dependencias desarrolla el código parte por parte (tarea a tarea) sin marcar explícitamente donde comienza y termina una tarea, le da la identación que el p le entregó e  implementa la validación de cada tarea del bloque en el if__name__. El output del cada agente se entrega  al e y este lo tiene que ensamblar con el estandar de la buenas practicas de python, estructurado por partes y cada parte en su lugar correspondiente y separado por una línea blanca que divide cada bloque estructural. 1ero El nombre de script y sus comentarios iniciales( si existen) este bloque no necesita anclas, 2do Las dependencias que el ensamblador tiene que ser capaz de evitar que se dupliquen las ordena en el orden de implementación y la entrega en un bloque, tampoco lleva ancla y se colocan de forma predeterminada detrás de los comentarios iniciales y el nombre. 3ero Las clases, métodos, funciones y partes de código que entrega el c y que se ubican en el ancla que dice el p en su output, se le coloca la identación correspondiente y se si no es la correcta el e da un aviso para que corrija el código. 4to La validación de código se coloca al final También sin ancla alguno 5to El código completo se válida y se aprueba de forma automática. Al aprobar es que el código se guarda en disco y se crea un copia del archivo original, si se desea deshacer la tarea actual, que está sin guardar se le da a la tecla deshacer y se puede volver paso a paso al código original guardado anteriormente. Este es el flujo de trabajo actual de APA_.Metodología_ Atómica.

---

*Versión 7.0 — Metodología actualizada con nuevas anclas y mejoras*