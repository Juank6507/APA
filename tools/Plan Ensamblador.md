
# PLAN DE MEJORA: Sistema de Anclas y Parser (v3.1)

## OBJETIVO

Expandir el sistema de anclas del `ensamblador_gui.py` para cubrir el 100% de los requerimientos de localización de código por parte de un LLM.

---

## 1. ESTADO ACTUAL

### 1.1 Anclas Implementadas

| Ancla | Tipo | Implementación |
|-------|------|----------------|
| `INICIO_ARCHIVO` | Archivo | ✅ Completo |
| `FIN_ARCHIVO` | Archivo | ✅ Completo |
| `ARCHIVO_NUEVO` | Archivo | ✅ Completo |
| `DESPUES_FUNCION:nombre` | Función | ✅ Completo |
| `ANTES_FUNCION:nombre` | Función | ✅ Completo |
| `REEMPLAZAR_FUNCION:nombre` | Función | ✅ Completo |
| `FIN_CLASE:nombre` | Clase | ✅ Completo |
| `INSERTAR_ANTES_MAIN` | Especial | ✅ Completo |
| `REEMPLAZAR_BLOQUE_MAIN` | Especial | ✅ Completo |
| `REEMPLAZAR_VARIABLE:nombre` | Variable | ⚠️ Básico |

### 1.2 Cobertura Actual

```
Cobertura total: 45%

Funcionalidades faltantes críticas:
- Métodos de clase
- Funciones async
- Anclas posicionales
- Anclas por patrón
- Anclas contextuales
```

---

## 2. ANCLAS A IMPLEMENTAR

### 2.1 Anclas de Clase (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `INICIO_CLASE:Nombre` | Inserta al principio de la clase (después de `class Nombre:`) | Añadir atributos |
| `ANTES_CLASE:Nombre` | Inserta antes de la definición de clase | Añadir decoradores |
| `DESPUES_CLASE:Nombre` | Inserta después de la clase (alias de FIN_CLASE) | Añadir clases relacionadas |
| `REEMPLAZAR_CLASE:Nombre` | Reemplaza la clase completa | Refactorizar clase |
| `CLASE_HEREDA:Nombre` | Inserta en clase que hereda de Nombre | Extender subclases |

### 2.2 Anclas de Método (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `DESPUES_METODO:Clase.metodo` | Inserta después de un método específico | Añadir nuevo método |
| `ANTES_METODO:Clase.metodo` | Inserta antes de un método específico | Añadir método relacionado |
| `REEMPLAZAR_METODO:Clase.metodo` | Reemplaza método específico | Refactorizar método |
| `DESPUES_METODO:metodo` | Inserta después de cualquier método con ese nombre | Método global |

### 2.3 Anclas de Variable (MEJORADO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `REEMPLAZAR_VARIABLE:nombre` | Reemplaza línea de variable | ⚠️ Mejorar regex |
| `DESPUES_VARIABLE:nombre` | Inserta después de variable | Añadir configuración |
| `ANTES_VARIABLE:nombre` | Inserta antes de variable | Preparar contexto |
| `VARIABLE_EN_CLASE:Clase.var` | Variable como atributo de clase | Modificar self.var |

### 2.4 Anclas de Import (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `DESPUES_IMPORT:modulo` | Inserta después de import específico | Añadir from relacionado |
| `ANTES_IMPORTS` | Inserta antes de todos los imports | Añadir comentario o config |
| `FIN_IMPORTS` | Inserta al final de la sección de imports | Añadir nuevo import |
| `REEMPLAZAR_IMPORT:modulo` | Reemplaza import específico | Cambiar versión/módulo |

### 2.5 Anclas Posicionales (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `LINEA:num` | Inserta en línea específica (1-indexed) | Inserción exacta |
| `DESPUES_LINEA:num` | Inserta después de línea num | Posición relativa |
| `ANTES_LINEA:num` | Inserta antes de línea num | Posición relativa |
| `RANGO_LINEAS:inicio-fin` | Reemplaza rango de líneas | Modificación precisa |

### 2.6 Anclas por Patrón (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `LINEA_CONTIENE:texto` | Primera línea que contiene texto | Localizar por contenido |
| `DESPUES_LINEA_CONTIENE:texto` | Después de línea con texto | Inserción contextual |
| `ANTES_LINEA_CONTIENE:texto` | Antes de línea con texto | Inserción contextual |
| `PATRON:regex` | Primera coincidencia de regex | Localización flexible |
| `DESPUES_PATRON:regex` | Después de coincidencia regex | Inserción por patrón |

### 2.7 Anclas de Bloque (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `DESPUES_BLOQUE_IF:condición` | Después de bloque if específico | Extender lógica |
| `DESPUES_BLOQUE_FOR:variable` | Después de bloque for | Añadir post-procesamiento |
| `DESPUES_BLOQUE_TRY` | Después de bloque try/except | Añadir manejo de errores |
| `DESPUES_BLOQUE_WITH:recurso` | Después de bloque with | Limpieza o continuación |

### 2.8 Anclas de Decorador (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `ANTES_DECORADOR:nombre` | Antes de decorador específico | Añadir decorador previo |
| `DESPUES_DECORADOR:nombre` | Después de decorador | Añadir decorador posterior |
| `REEMPLAZAR_DECORADOR:nombre` | Reemplaza decorador | Cambiar parámetros |

### 2.9 Anclas de Comentario (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `DESPUES_COMENTARIO:texto` | Después de comentario que contiene texto | Insertar documentación |
| `ANTES_COMENTARIO:texto` | Antes de comentario específico | Añadir código previo |
| `TODO:texto` | Localiza comentario # TODO con texto | Implementar TODO |

### 2.10 Anclas Contextuales (NUEVO)

| Ancla | Descripción | Ejemplo |
|-------|-------------|---------|
| `EN_CLASE:Nombre|DESPUES_FUNCION:x` | Combinación: dentro de clase X, después de función | Contexto múltiple |
| `EN_FUNCION:nombre|LINEA_CONTIENE:x` | Dentro de función, línea con texto | Contexto anidado |
| `PRIMERA_COINCIDENCIA:ancla` | Primera ocurrencia cuando hay múltiples | Desambiguación |
| `ULTIMA_COINCIDENCIA:ancla` | Última ocurrencia cuando hay múltiples | Desambiguación |

---

## 3. MEJORAS AL PARSER

### 3.1 Soporte para Funciones Async

```python
# ACTUAL
if isinstance(node, ast.FunctionDef):

# MEJORADO
if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
```

### 3.2 Soporte para Métodos de Clase

```python
# NUEVO: Parser de notación Clase.metodo
def parse_method_reference(ref: str) -> tuple:
    """
    Parsea 'Clase.metodo' → ('Clase', 'metodo')
    Parsea 'metodo' → (None, 'metodo')
    """
    if '.' in ref:
        parts = ref.split('.', 1)
        return parts[0], parts[1]
    return None, ref
```

### 3.3 Regex Mejorada para Variables

```python
# ACTUAL (limitado)
pattern = re.compile(rf'^{re.escape(var_name)}\s*[=:]', re.IGNORECASE)

# MEJORADO (completo)
pattern = re.compile(
    rf'^(\s*(?:self\.)?\s*{re.escape(var_name)}\s*[=:]|\s*{re.escape(var_name)}\s*:)',
    re.IGNORECASE
)
```

### 3.4 Soporte para Múltiples Coincidencias

```python
# NUEVO: Retornar lista de ubicaciones
def resolve_anchor_all(content: str, anchor_raw: str) -> list:
    """
    Retorna todas las ubicaciones que coinciden con el ancla.
    Útil cuando hay múltiples funciones con el mismo nombre.
    """
    pass
```

---

## 4. NUEVOS CAMPOS DEL PARSER

### 4.1 Campo CONTEXTO (NUEVO)

```markdown
- CONTEXTO: EN_CLASE:MiClase
```

Permite especificar el contexto donde se debe buscar el ancla.

### 4.2 Campo COINCIDENCIA (NUEVO)

```markdown
- COINCIDENCIA: PRIMERA | ULTIMA | TODAS
```

Especifica cuál coincidencia usar cuando hay múltiples.

### 4.3 Campo LINEA (NUEVO)

```markdown
- LINEA: 42
```

Alternativa numérica para inserción exacta.

---

## 5. FORMATO COMPLETO DEL OUTPUT PLANIFICADOR

```markdown
## DATOS_TAREA

- SCRIPT: mi_modulo.py
- TAREA_ID: V15
- ANCLA: DESPUES_METODO:App._setup_button
- CONTEXTO: EN_CLASE:App
- MODO_EJECUCION: local
- INDENTACIÓN: 8
- COINCIDENCIA: PRIMERA

## IMPORTS_NUEVOS

from tkinter import ttk
import logging

## DESCRIPCION

Añade un nuevo botón al método de configuración de la interfaz.

## CODIGO

... (bloque de código)
```

---

## 6. PRIORIDADES DE IMPLEMENTACIÓN

### Fase 1 - Crítico (Inmediato)

| Prioridad | Ancla | Justificación |
|-----------|-------|---------------|
| P0 | `DESPUES_METODO:Clase.metodo` | Esencial para POO |
| P0 | `REEMPLAZAR_METODO:Clase.metodo` | Esencial para POO |
| P0 | `INICIO_CLASE:Nombre` | Esencial para POO |
| P0 | `REEMPLAZAR_CLASE:Nombre` | Esencial para POO |
| P0 | Soporte `AsyncFunctionDef` | Python moderno |

### Fase 2 - Importante (Corto plazo)

| Prioridad | Ancla | Justificación |
|-----------|-------|---------------|
| P1 | `LINEA:num` | Control preciso |
| P2 | `LINEA_CONTIENE:texto` | Búsqueda flexible |
| P2 | `FIN_IMPORTS` | Organización imports |
| P2 | `VARIABLE_EN_CLASE:Clase.var` | Atributos de clase |

### Fase 3 - Deseable (Mediano plazo)

| Prioridad | Ancla | Justificación |
|-----------|-------|---------------|
| P3 | `DESPUES_BLOQUE_*` | Control fino |
| P3 | `PATRON:regex` | Máxima flexibilidad |
| P3 | `EN_CLASE:X|ANCLA:Y` | Contexto múltiple |
| P3 | `TODO:texto` | Automatización tareas |

---

## 7. ESQUEMA DE CLASE ACTUALIZADO

```python
class PlannerOutputParser:
    """Parser v3.1 - Sistema de Anclas Completo"""
    
    # Regex para campos (existentes + nuevos)
    _RE_SCRIPT      = re.compile(r'-\s*SCRIPT\s*:\s*(.+)', re.IGNORECASE)
    _RE_TAREA_ID    = re.compile(r'-\s*TAREA_?ID\s*:\s*(\S+)', re.IGNORECASE)
    _RE_ANCLA       = re.compile(r'-\s*ANCLA\s*:\s*(.+)', re.IGNORECASE)
    _RE_MODO        = re.compile(r'-\s*MODO_?EJECUCION\s*:\s*(\S+)', re.IGNORECASE)
    _RE_CONTEXTO    = re.compile(r'-\s*CONTEXTO\s*:\s*(.+)', re.IGNORECASE)      # NUEVO
    _RE_COINCIDENCIA= re.compile(r'-\s*COINCIDENCIA\s*:\s*(\S+)', re.IGNORECASE) # NUEVO
    _RE_LINEA       = re.compile(r'-\s*LINEA\s*:\s*(\d+)', re.IGNORECASE)        # NUEVO
    _RE_INDENT      = re.compile(r'#\s*INDENTACIÓN\s*:\s*(\d+)', re.IGNORECASE)
    
    @classmethod
    def parse(cls, text: str) -> dict:
        result = {
            "script": "", 
            "tarea_id": "", 
            "ancla_raw": "",
            "modo": "local", 
            "imports_nuevos": [], 
            "errores": [],
            "contexto": "",      # NUEVO
            "coincidencia": "PRIMERA",  # NUEVO
            "linea": None,       # NUEVO
        }
        # ... parseo de campos
        return result
    
    @staticmethod
    def resolve_anchor(content: str, anchor_raw: str, contexto: str = "") -> tuple:
        """
        Resuelve ancla v3.1 con soporte completo.
        
        Retorna: (line_number, line_content, action)
        - action: "ANTES" | "DESPUES" | "REEMPLAZAR" | "REEMPLAZAR_RANGO"
        """
        # Implementación completa...
        pass
    
    @staticmethod
    def resolve_anchor_all(content: str, anchor_raw: str) -> list:
        """Retorna todas las coincidencias del ancla."""
        pass
```

---

## 8. TESTING

### 8.1 Casos de Prueba Requeridos

```python
TEST_CASES = [
    # Anclas de archivo
    ("INICIO_ARCHIVO", "archivo.py", (1, "primera línea")),
    ("FIN_ARCHIVO", "archivo.py", (N, "última línea")),
    
    # Anclas de función
    ("DESPUES_FUNCION:main", "def main():...", (5, "fin de main")),
    ("ANTES_FUNCION:main", "def main():...", (2, "antes de main")),
    ("REEMPLAZAR_FUNCION:main", "def main():...", (3, "inicio main")),
    
    # Anclas de clase (NUEVO)
    ("INICIO_CLASE:App", "class App:", (2, "dentro de App")),
    ("ANTES_CLASE:App", "class App:", (1, "antes de App")),
    ("REEMPLAZAR_CLASE:App", "class App:", (1, "inicio App")),
    
    # Anclas de método (NUEVO)
    ("DESPUES_METODO:App.__init__", "class App:...", (15, "fin __init__")),
    ("REEMPLAZAR_METODO:App.run", "class App:...", (20, "inicio run")),
    
    # Anclas posicionales (NUEVO)
    ("LINEA:42", "archivo.py", (42, "línea 42")),
    ("RANGO_LINEAS:10-15", "archivo.py", (10, "línea 10")),
    
    # Anclas por patrón (NUEVO)
    ("LINEA_CONTIENE:TODO", "# TODO: fix", (3, "línea con TODO")),
    
    # Async (NUEVO)
    ("DESPUES_FUNCION:async_main", "async def async_main():", (5, "fin async")),
]
```

---

## 9. DOCUMENTACIÓN PARA EL LLM

### 9.1 Guía de Anclas para el Planificador

```
REGLAS PARA ESPECIFICAR ANCLAS:

1. ANCLAS DE ARCHIVO (sin contexto requerido):
   - INICIO_ARCHIVO
   - FIN_ARCHIVO
   - ARCHIVO_NUEVO

2. ANCLAS DE FUNCIÓN (global):
   - ANTES_FUNCION:nombre
   - DESPUES_FUNCION:nombre
   - REEMPLAZAR_FUNCION:nombre

3. ANCLAS DE CLASE:
   - INICIO_CLASE:Nombre → inserta dentro de la clase
   - ANTES_CLASE:Nombre → inserta antes de la definición
   - FIN_CLASE:Nombre → inserta al final de la clase
   - REEMPLAZAR_CLASE:Nombre → reemplaza toda la clase

4. ANCLAS DE MÉTODO (usar notación Clase.metodo):
   - ANTES_METODO:Clase.metodo
   - DESPUES_METODO:Clase.metodo
   - REEMPLAZAR_METODO:Clase.metodo

5. ANCLAS DE VARIABLE:
   - REEMPLAZAR_VARIABLE:nombre
   - DESPUES_VARIABLE:nombre
   - VARIABLE_EN_CLASE:Clase.atributo

6. ANCLAS POSICIONALES:
   - LINEA:42 → inserta en línea exacta
   - DESPUES_LINEA:42 → inserta después de línea
   - RANGO_LINEAS:10-15 → reemplaza líneas 10 a 15

7. ANCLAS POR PATRÓN:
   - LINEA_CONTIENE:texto → primera línea que contiene "texto"
   - PATRON:regex → primera coincidencia de expresión regular

8. CONTEXTO (para desambiguación):
   - CONTEXTO: EN_CLASE:MiClase
   - COINCIDENCIA: PRIMERA | ULTIMA

9. ESPECIALES:
   - INSERTAR_ANTES_MAIN
   - REEMPLAZAR_BLOQUE_MAIN
   - FIN_IMPORTS
```

---

## 10. MÉTRICAS DE ÉXITO

| Métrica | Actual | Objetivo |
|---------|--------|----------|
| Cobertura de anclas | 45% | 100% |
| Tipos de ancla soportados | 10 | 35+ |
| Precisión de localización | ~80% | 99%+ |
| Soporte POO | 25% | 100% |
| Soporte código async | 0% | 100% |
| Desambiguación múltiple | No | Sí |

---

## 11. PRÓXIMOS PASOS

1. **Implementar Fase 1** (P0) - Anclas críticas POO y async
2. **Actualizar `resolve_anchor()`** con nueva lógica
3. **Añadir `resolve_anchor_all()`** para múltiples coincidencias
4. **Crear tests unitarios** para cada tipo de ancla
5. **Actualizar documentación** del sistema APA
6. **Implementar Fase 2** (P1-P2)
7. **Implementar Fase 3** (P3)

---

**Fin del Plan de Mejora**
```

¿Necesita que proceda a implementar el código de la Fase 1 (crítica) en el archivo `ensamblador_gui.py`?