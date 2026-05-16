# apa/agents/semi_auto_agent.py
"""
SemiAutoAgent v3.0 — Agente semi-autónomo que orquesta el pipeline
Planificador → Codificador → Integrador usando call_llm().

CAMBIO PRINCIPAL v3.0:
  Reemplaza el Ensamblador mecánico (anclas, indentación, parseo AST)
  por un Integrador inteligente (LLM) que recibe:
  1. El archivo original completo
  2. La especificación del Planificador
  3. El código del Codificador
  Y produce el archivo final integrado.

  El ensamblador mecánico (assembler.py) se mantiene para el Tab 2
  (Ensamblador Manual) de la GUI, pero el modo semi-autónomo y el
  modo autónomo de APA usan ahora el Integrador.

Nivel 2 (AS3): Ejecución multi-tarea con retroalimentación paso a paso.

El Director describe una tarea, APA genera un plan de N subtareas,
las ejecuta una por una, el Director ve cada resultado y pulsa
Aprobar o Rechazar antes de pasar a la siguiente.

Si una tarea se rechaza, el Director puede dar instrucciones de
corrección y APA la reintenta (máximo 2 reintentos).

Flujo:
  IDLE → generate_plan() → PLANNED → execute_next() → EXECUTING → AWAITING_APPROVAL
       → approve() → PLANNED (siguiente tarea) / COMPLETED (última)
       → reject(feedback) → EXECUTING (reintento) / FAILED (máx reintentos)
"""

import os
import sys
import logging
import re
import json
import threading
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

# Asegurar que apa.core es importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.router import call_llm
from core.assembly_validator import AssemblyValidator

logger = logging.getLogger(__name__)


# ─── V3PlanParser: Parser sin anclas para el formato v3.0 ───

class V3PlanParser:
    """Parser del output del Planificador para el pipeline v3.0.
    
    A diferencia de PlannerOutputParser (assembler.py), NO requiere el campo
    ANCLA. El Integrador se encarga de posicionar el código basándose en la
    descripción textual del Planificador.
    
    Formato esperado del Planificador v3.0:
    ```markdown
    ## TAREA DE ENSAMBLAJE
    - SCRIPT: ruta/archivo.py
    - TAREA_ID: T1
    - MODO_EJECUCION: local
    
    ## BLOQUE
    # INSTRUCCIÓN PARA CODIFICADOR:
    # {descripción}
    
    ## IMPORTS_NUEVOS
    {módulo}
    ```
    """
    
    # Regex para campos escalares (tolerantes a espacios)
    _RE_SCRIPT   = re.compile(r'(?:-|##)?\s*#?\s*SCRIPT\s*:\s*(.+)', re.IGNORECASE)
    _RE_TAREA_ID = re.compile(r'(?:-|##)?\s*#?\s*TAREA_?ID\s*:\s*(\S+)', re.IGNORECASE)
    _RE_MODO     = re.compile(r'(?:-|##)?\s*#?\s*MODO_?EJECUCION\s*:\s*(\S+)', re.IGNORECASE)
    
    @classmethod
    def _parse_imports(cls, text: str) -> list:
        """Parser robusto de imports desde sección ## IMPORTS_NUEVOS."""
        imports = []
        marker = None
        for line in text.split('\n'):
            if re.search(r'##\s*IMPORTS_NUEVOS', line, re.IGNORECASE):
                marker = line
                break
        if marker is None:
            return imports
        
        after = text.split(marker, 1)[1]
        section_lines = []
        for line in after.split('\n'):
            if line.strip().startswith('##') and 'IMPORTS' not in line:
                break
            section_lines.append(line)
        
        for line in section_lines:
            raw = line.strip()
            if not raw or raw.startswith('#'):
                continue
            if raw.startswith('- '):
                raw = raw[2:].strip()
            elif raw.startswith('-'):
                raw = raw[1:].strip()
            if not raw:
                continue
            if raw.startswith("import ") or raw.startswith("from "):
                canonical = raw
            else:
                clean = raw.strip().rstrip('.,; \t')
                if not clean or not re.match(r'^[\w][\w\.]*$', clean):
                    continue
                canonical = "import " + clean
            if canonical not in imports:
                imports.append(canonical)
        return imports
    
    @classmethod
    def parse_single(cls, text: str) -> dict:
        """Parsea un bloque individual del Planificador (sin requerir ANCLA)."""
        result = {
            "script": "",
            "tarea_id": "",
            "modo": "local",
            "imports_nuevos": [],
            "errores": [],
        }
        
        # Extraer campos escalares
        m = cls._RE_SCRIPT.search(text)
        if m:
            result["script"] = m.group(1).strip()
        m = cls._RE_TAREA_ID.search(text)
        if m:
            result["tarea_id"] = m.group(1).strip()
        m = cls._RE_MODO.search(text)
        if m:
            modo_raw = m.group(1).strip().lower()
            result["modo"] = "nas" if "nas" in modo_raw else "local"
        
        # Extraer imports
        result["imports_nuevos"] = cls._parse_imports(text)
        
        # Solo requerir SCRIPT (ANCLA ya no es obligatoria en v3.0)
        if not result["script"]:
            result["errores"].append("Falta campo SCRIPT.")
        
        return result
    
    @classmethod
    def parse_blocks(cls, text: str) -> list:
        """Extrae múltiples bloques del output del Planificador v3.0.
        
        Retorna una lista de dicts, cada uno con:
        - script, tarea_id, modo, imports_nuevos, bloque_texto (contenido completo)
        """
        blocks = []
        
        # Estrategia 1: Buscar múltiples ## TAREA DE ENSAMBLAJE
        task_pattern = re.compile(r'^##\s*TAREA\s*DE\s*ENSAMBLAJE', re.MULTILINE)
        task_matches = list(task_pattern.finditer(text))
        
        if task_matches:
            for i, match in enumerate(task_matches):
                start = match.start()
                end = task_matches[i + 1].start() if i + 1 < len(task_matches) else len(text)
                task_text = text[start:end]
                
                parsed = cls.parse_single(task_text)
                parsed["bloque_texto"] = task_text.strip()
                blocks.append(parsed)
            
            if blocks:
                return blocks
        
        # Estrategia 2: Un solo bloque (sin encabezado ## TAREA DE ENSAMBLAJE explícito)
        parsed = cls.parse_single(text)
        if not parsed["errores"]:
            parsed["bloque_texto"] = text.strip()
            blocks.append(parsed)
            return blocks
        
        # Estrategia 3: Intentar extraer SCRIPT al menos
        # (el Planificador puede responder en un formato ligeramente diferente)
        m = cls._RE_SCRIPT.search(text)
        if m:
            parsed = {
                "script": m.group(1).strip(),
                "tarea_id": "T1",
                "modo": "local",
                "imports_nuevos": cls._parse_imports(text),
                "errores": [],
                "bloque_texto": text.strip(),
            }
            blocks.append(parsed)
            return blocks
        
        # No se pudo parsear nada útil
        return blocks


# ─── Helpers de métricas v2.0 ───

def _extract_llm_metadata(response: dict, prefix: str) -> dict:
    """Extrae métricas de una respuesta de call_llm() con un prefijo dado.
    
    Args:
        response: Dict retornado por call_llm()
        prefix: "planning", "coding" o "integration"
    
    Returns:
        Dict con claves prefijadas: {prefix}_model, {prefix}_provider, etc.
    """
    return {
        f"{prefix}_model": response.get("model_used", ""),
        f"{prefix}_provider": response.get("provider", ""),
        f"{prefix}_tokens": (response.get("tokens_input", 0) + response.get("tokens_output", 0)),
        f"{prefix}_tokens_input": response.get("tokens_input", 0),
        f"{prefix}_tokens_output": response.get("tokens_output", 0),
        f"{prefix}_latency_ms": response.get("latency_ms", 0),
        f"{prefix}_cost_usd": response.get("cost_usd", 0.0),
        f"{prefix}_arena_score": response.get("arena_score"),
    }


# ─── Estados del agente ───

class AgentState(Enum):
    """Estados de la máquina de estados del SemiAutoAgent."""
    IDLE = "idle"
    PLANNING = "planning"
    PLANNED = "planned"            # Plan generado, esperando ejecución
    EXECUTING = "executing"        # Ejecutando tarea (Codificador + Integrador)
    AWAITING_APPROVAL = "awaiting_approval"  # Tarea ejecutada, espera decisión
    COMPLETED = "completed"        # Todas las tareas completadas
    FAILED = "failed"              # Error irrecuperable
    CANCELLED = "cancelled"        # Cancelado por el usuario


class TaskStatus(Enum):
    """Estado de una tarea individual."""
    PENDING = "pending"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskInfo:
    """Información de una tarea individual del plan."""
    task_id: str = ""
    script: str = ""
    anchor: str = ""
    status: TaskStatus = TaskStatus.PENDING
    attempt: int = 0               # Número de intento actual
    max_attempts: int = 3          # Máximo de intentos (1 original + 2 reintentos)
    planner_output: str = ""       # Output del Planificador para esta tarea
    coder_output: str = ""         # Output del Codificador para esta tarea
    assembled_content: str = ""    # Contenido integrado resultante (v3.0: del Integrador)
    validation_result: dict = field(default_factory=dict)
    error: Optional[str] = None
    rejection_feedback: str = ""   # Instrucciones de corrección del Director


@dataclass
class SemiAutoResult:
    """Resultado del pipeline semi-autónomo (tarea única).

    v3.0: Incluye métricas completas de las 3 llamadas LLM
    (planning + coding + integration).
    """
    success: bool = False
    planner_output: str = ""
    coder_output: str = ""
    assembled_content: str = ""      # v3.0: Contenido del Integrador
    script_name: str = ""
    task_id: str = ""
    validation_result: dict = field(default_factory=dict)
    error: Optional[str] = None
    model_used_planner: str = ""
    model_used_coder: str = ""
    model_used_integrator: str = ""  # v3.0: Modelo usado por el Integrador
    log: list = field(default_factory=list)
    # Métricas de las 3 llamadas LLM
    planning_provider: str = ""
    planning_tokens_input: int = 0
    planning_tokens_output: int = 0
    planning_latency_ms: int = 0
    planning_cost_usd: float = 0.0
    planning_arena_score: Optional[float] = None
    coding_provider: str = ""
    coding_tokens_input: int = 0
    coding_tokens_output: int = 0
    coding_latency_ms: int = 0
    coding_cost_usd: float = 0.0
    coding_arena_score: Optional[float] = None
    # v3.0: Métricas del Integrador
    integration_provider: str = ""
    integration_tokens_input: int = 0
    integration_tokens_output: int = 0
    integration_latency_ms: int = 0
    integration_cost_usd: float = 0.0
    integration_arena_score: Optional[float] = None


@dataclass
class PlanResult:
    """Resultado de la fase de planificación."""
    success: bool = False
    tasks: List[TaskInfo] = field(default_factory=list)
    raw_planner_output: str = ""
    error: Optional[str] = None
    model_used: str = ""
    log: list = field(default_factory=list)


# ─── System Prompts ───

PLANIFICADOR_SYSTEM_PROMPT = """Eres un Ingeniero de Software Senior. Tu rol es el de Agente Planificador del proyecto APA.

## FORMATO DE SALIDA

Tu respuesta SIEMPRE debe ser UN ÚNICO bloque ```markdown```. Sin texto antes ni después.

Plantilla para UNA tarea:

## TAREA DE ENSAMBLAJE
- SCRIPT: {ruta/archivo.py}
- TAREA_ID: {ID}
- MODO_EJECUCION: {local | nas}

## BLOQUE

# INSTRUCCIÓN PARA CODIFICADOR:
# {descripción técnica precisa y específica}
# DATOS ESPECÍFICOS:
# {contexto de estructuras existentes si aplica}

# VALIDACIÓN:
# - {criterio verificable}

## IMPORTS_NUEVOS
{módulo}

Omite IMPORTS_NUEVOS si no hay imports.

Para múltiples tareas, repite el bloque ## TAREA DE ENSAMBLAJE separado por ---.

## REGLAS CRÍTICAS

1. **ESPECIFICACIÓN QUIRÚRGICA**: Describe exactamente qué hay que hacer. Indica nombre exacto de la clase/método donde se inserta, nombre del método anterior/posterior, y si es un método nuevo o reemplazo.
2. **SEPARACIÓN DE ROLES**: El BLOQUE contiene SOLO comentarios de instrucción. NUNCA código ejecutable.
3. **DATOS ESPECÍFICOS OBLIGATORIOS**: Cuando la tarea implique estructura EXISTENTE, indica qué existe en esa posición. Nombra las funciones/métodos/classes que ya están.
4. **REGLA ANTI-ERROR IMPORTS**: Tarea solo imports → BLOQUE VACÍO.
5. **APIs EXTERNAS**: Especificar SIEMPRE la firma completa.

## NOTA
Ya no necesitas especificar ANCLAS AST. El Integrador se encarga de colocar el código en la posición correcta basándose en tu descripción. Simplemente describe con precisión dónde va el cambio.
"""

CODIFICADOR_SYSTEM_PROMPT = """Eres un Ingeniero de Software Senior. Tu rol es el de Agente Codificador de Script Atómico del proyecto APA.

## FORMATO DE ENTREGA OBLIGATORIO
Tu respuesta SIEMPRE debe ser UN ÚNICO bloque de código Markdown de Python, envuelto en ```python``` al inicio y ``` al final.
- NUNCA incluyas texto, comentarios o explicaciones fuera del bloque de código.
- La primera línea DENTRO del bloque debe ser el comentario de ruta: # {ruta/archivo.py}

## REGLA 0 — COMPUERTA DE ENTRADA
Antes de escribir, respóndete internamente:
¿La instrucción describe explícitamente una función, método o clase a implementar?
    SÍ → escribe exactamente ese bloque dentro del marco markdown.
    NO → no escribas nada.

## REGLAS DE FORMATO INTERNO
1. Primera línea SIEMPRE: # {ruta/archivo.py}
2. Indentación: aplica la indentación que corresponda según el contexto.
3. Bloques completos: si piden reescribir, entrega la unidad completa.
4. Imports: implementar CORRECTAMENTE según IMPORTS_NUEVOS recibido.
5. Ignora comentarios # INSTRUCCIÓN... del prompt. Tu respuesta es solo código ejecutable.

## REGLA DE INTEGRACIÓN
Todo código debe estar DENTRO de una función, método o clase.
NUNCA dejar líneas sueltas fuera de una unidad arquitectónica.

## REGLA DE VALIDACIÓN
Al final de TODO código, incluir exactamente:
if __name__ == "__main__":
    # === VALIDACIÓN TAREA: {ID} ===
    [Tests ejecutables que cubran CADA criterio de la sección VALIDACIÓN]
"""

# Prompt del Integrador (importado de prompts/integrador_prompt.py)
# Se carga perezosamente para evitar imports circulares
_INTEGRADOR_PROMPTS = None

def _get_integrador_prompts():
    """Carga perezosa de los prompts del Integrador."""
    global _INTEGRADOR_PROMPTS
    if _INTEGRADOR_PROMPTS is None:
        try:
            from prompts.integrador_prompt import (
                INTEGRADOR_SYSTEM_PROMPT,
                INTEGRADOR_USER_PROMPT_TEMPLATE,
                INTEGRADOR_CORRECCION_ADDENDUM,
            )
            _INTEGRADOR_PROMPTS = {
                "system": INTEGRADOR_SYSTEM_PROMPT,
                "user_template": INTEGRADOR_USER_PROMPT_TEMPLATE,
                "correction_addendum": INTEGRADOR_CORRECCION_ADDENDUM,
            }
        except ImportError:
            # Fallback si no se encuentra el módulo de prompts
            _INTEGRADOR_PROMPTS = {
                "system": _DEFAULT_INTEGRADOR_SYSTEM_PROMPT,
                "user_template": _DEFAULT_INTEGRADOR_USER_TEMPLATE,
                "correction_addendum": "",
            }
    return _INTEGRADOR_PROMPTS

# Fallback embebido
_DEFAULT_INTEGRADOR_SYSTEM_PROMPT = """Eres un Ingeniero de Software Senior. Tu rol es el de Agente Integrador del proyecto APA.

Recibes:
1. El contenido ORIGINAL de un archivo Python
2. La ESPECIFICACIÓN de cambio del Planificador
3. El CÓDIGO NUEVO del Codificador

Debes producir el archivo FINAL completo: el original con el código nuevo integrado correctamente.

REGLAS CRÍTICAS:
1. ENTREGA el archivo COMPLETO. Nunca fragmentos.
2. INTEGRA, no reemplaces. Fusiona el código nuevo con el existente.
3. SI el Codificador generó una clase completa pero solo se necesitaba un método, extrae el método e insértalo donde corresponde. NO dupliques la clase.
4. SI el código nuevo necesita imports, añádelos al bloque de imports existente.
5. SI el código nuevo colisiona con algo existente, reemplaza la versión antigua por la nueva.
6. MANTIENE el estilo del archivo original.
7. NO re-planifiques. Solo integra.

Formato: UN ÚNICO bloque ```python``` con el archivo completo. Primera línea: # {ruta/archivo.py}
"""

_DEFAULT_INTEGRADOR_USER_TEMPLATE = """## ARCHIVO ORIGINAL ({script_name}):
```python
{original_content}
```

## ESPECIFICACIÓN DE CAMBIO (del Planificador):
{planner_specification}

## CÓDIGO NUEVO DEL CODIFICADOR:
```python
{coder_code}
```

Integra el código nuevo en el archivo original según la especificación. Entrega el archivo completo. Primera línea: # {script_name}
"""

# Prompt extra para cuando el Director corrige una tarea rechazada
CORRECCION_SYSTEM_ADDENDUM = """

## CONTEXTO DE CORRECCIÓN
El Director ha RECHAZADO la versión anterior del código con las siguientes observaciones:
{feedback}

Debes corregir el código para abordar estas observaciones. Mantén la misma estructura
pero aplica los cambios solicitados. No repitas los mismos errores.
"""


class SemiAutoAgent:
    """
    Agente semi-autónomo que orquesta el pipeline completo:
    Prompt → Planificador (LLM) → Codificador (LLM) → Integrador (LLM) → Validación
    
    v3.0: El Ensamblador mecánico ha sido reemplazado por el Integrador (LLM).
    El Integrador recibe el archivo original + especificación + código nuevo
    y produce el archivo final integrado, evitando los problemas de anclas
    e indentación del ensamblador mecánico.
    
    Nivel 2 (AS3): Ejecución multi-tarea con retroalimentación paso a paso.
    """

    def __init__(self, project_root: str = "", project_id: Optional[str] = None):
        """
        Inicializa el agente semi-autónomo.

        Args:
            project_root: Ruta raíz del proyecto para resolver archivos.
            project_id: ID del proyecto para tracking de métricas en UsageTracker.
        """
        self.project_root = project_root
        self._project_id = project_id
        self._validator = AssemblyValidator()  # v3.0: Validador independiente
        self._cancelled = False
        
        # Estado de la máquina de estados
        self._state = AgentState.IDLE
        self._plan: List[TaskInfo] = []
        self._current_task_index = -1
        self._raw_planner_output = ""
        self._original_contents: Dict[str, str] = {}  # script → contenido original
        self._log: List[str] = []
        self._model_used_planner = ""
        # v3.0: Metadata de las llamadas LLM (planning)
        self._planner_llm_metadata: Dict[str, Any] = {}

    # ─── Propiedades ───

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def plan(self) -> List[TaskInfo]:
        return self._plan

    @property
    def current_task(self) -> Optional[TaskInfo]:
        if 0 <= self._current_task_index < len(self._plan):
            return self._plan[self._current_task_index]
        return None

    @property
    def current_task_index(self) -> int:
        return self._current_task_index

    @property
    def log(self) -> List[str]:
        return self._log

    def get_progress_summary(self) -> dict:
        """Retorna resumen del progreso para la GUI."""
        total = len(self._plan)
        approved = sum(1 for t in self._plan if t.status == TaskStatus.APPROVED)
        rejected = sum(1 for t in self._plan if t.status == TaskStatus.REJECTED)
        failed = sum(1 for t in self._plan if t.status == TaskStatus.FAILED)
        pending = sum(1 for t in self._plan if t.status == TaskStatus.PENDING)
        return {
            "state": self._state.value,
            "total_tasks": total,
            "approved": approved,
            "rejected": rejected,
            "failed": failed,
            "pending": pending,
            "current_index": self._current_task_index,
        }

    # ─── Cancelación ───

    def cancel(self):
        """Cancela la ejecución del agente."""
        self._cancelled = True
        if self._state == AgentState.EXECUTING:
            self._state = AgentState.CANCELLED
            self._log.append("Cancelado por el usuario durante ejecución")

    # ─── Fase 1: Planificación ───

    def generate_plan(
        self,
        user_prompt: str,
        target_file: str = "",
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> PlanResult:
        """
        Genera un plan de ensamblaje a partir del prompt del Director.
        
        Llama al Planificador (LLM), parsea el output y retorna la lista
        de tareas. No ejecuta nada — solo planifica.
        
        Args:
            user_prompt: Instrucción en lenguaje natural del Director.
            target_file: Archivo objetivo (ruta relativa). Si está vacío,
                         el Planificador lo determinará.
            on_progress: Callback de progreso (etapa, mensaje).
        
        Returns:
            PlanResult con la lista de tareas y estado del plan.
        """
        self._cancelled = False
        self._state = AgentState.PLANNING
        self._plan = []
        self._current_task_index = -1
        self._log = []
        self._original_contents = {}
        
        result = PlanResult()
        self._log.append(f"Planificación: {user_prompt[:80]}")
        
        try:
            self._report(on_progress, "planificador", "Consultando Planificador...")
            
            # Obtener contenido del archivo objetivo si existe
            existing_content = ""
            if target_file and self.project_root:
                file_path = self._resolve_file(target_file)
                if file_path and os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    self._original_contents[target_file] = existing_content
                    self._log.append(f"Contenido original cargado: {len(existing_content)} chars")
            
            planner_user_prompt = self._build_planner_prompt(
                user_prompt, target_file, existing_content
            )

            self._report(on_progress, "planificador", f"Consultando Planificador (modelo: seleccionando...)...")
            self._log.append(f"[PLANIFICADOR] Enviando consulta al LLM...")

            planner_response = call_llm(
                task_type="planning",
                system_prompt=PLANIFICADOR_SYSTEM_PROMPT,
                user_prompt=planner_user_prompt,
                max_tokens=3000,
                temperature=0.1,
                project_id=self._project_id,
            )

            if not planner_response.get("success"):
                detail = planner_response.get('error', 'sin respuesta')
                model = planner_response.get('model_used', 'desconocido')
                attempts = planner_response.get('attempts', '?')
                result.error = f"Error del Planificador (modelo: {model}, intentos: {attempts}): {detail}"
                self._log.append(f"[PLANIFICADOR] ERROR: {result.error}")
                self._report(on_progress, "planificador", f"Error: {detail}")
                self._state = AgentState.FAILED
                return result

            planner_output = planner_response["content"]
            result.raw_planner_output = planner_output
            result.model_used = planner_response.get("model_used", "")
            self._model_used_planner = result.model_used
            self._raw_planner_output = planner_output
            # v3.0: Guardar metadata del planificador
            self._planner_llm_metadata = _extract_llm_metadata(planner_response, "planning")
            result.log = self._log.copy()
            self._log.append(f"[PLANIFICADOR] OK — modelo: {result.model_used}, intentos: {planner_response.get('attempts', '?')}")
            self._report(on_progress, "planificador", f"Planificador respondió (modelo: {result.model_used})")

            if self._cancelled:
                self._state = AgentState.CANCELLED
                result.error = "Cancelado por el usuario"
                return result

            # Parsear output del Planificador en tareas (v3.0: usa V3PlanParser, sin anclas)
            self._log.append(f"[PLANIFICADOR] Parseando output ({len(planner_output)} chars)...")
            self._report(on_progress, "planificador", "Parseando plan...")
            blocks_data = V3PlanParser.parse_blocks(planner_output)
            
            if not blocks_data:
                result.error = "Error de parseo: No se pudo extraer ninguna tarea del output del Planificador."
                self._log.append(f"[PLANIFICADOR] ERROR parseo: sin bloques detectados")
                self._state = AgentState.FAILED
                return result
            
            # Verificar errores de parseo
            parse_errors = []
            for bd in blocks_data:
                for err in bd.get("errores", []):
                    parse_errors.append(err)
            if parse_errors:
                # Si solo faltan anclas, no es error en v3.0
                non_anchor_errors = [e for e in parse_errors if "ANCLA" not in e.upper()]
                if non_anchor_errors:
                    result.error = f"Error de parseo: {'; '.join(non_anchor_errors)}"
                    self._log.append(f"[PLANIFICADOR] ERROR parseo: {result.error}")
                    self._state = AgentState.FAILED
                    return result
            
            # Crear TaskInfo para cada bloque
            for bd in blocks_data:
                task = TaskInfo(
                    task_id=bd.get("tarea_id", f"T{len(self._plan)+1}"),
                    script=bd.get("script", target_file),
                    anchor="",  # v3.0: Ya no se usan anclas
                    planner_output=bd.get("bloque_texto", self._extract_task_block(planner_output, bd.get("tarea_id", ""))),
                    status=TaskStatus.PENDING,
                )
                self._plan.append(task)
                self._log.append(f"[PLANIFICADOR] Tarea planificada: {task.task_id} → {task.script}")
            
            result.tasks = self._plan
            result.success = True
            
            self._state = AgentState.PLANNED
            self._report(on_progress, "planificador", 
                         f"Plan generado: {len(self._plan)} tarea(s)")
            
            return result

        except Exception as e:
            result.error = f"Error inesperado en planificación: {e}"
            self._log.append(f"EXCEPCIÓN: {e}")
            logger.error(f"SemiAutoAgent.generate_plan error: {e}", exc_info=True)
            self._state = AgentState.FAILED
            return result

    # ─── Fase 2: Ejecución paso a paso ───

    def execute_next(
        self,
        on_progress: Optional[Callable[[str, str], None]] = None,
        on_complete: Optional[Callable[[SemiAutoResult], None]] = None,
    ) -> bool:
        """
        Ejecuta la siguiente tarea pendiente del plan.
        
        La ejecución es asíncrona (en un hilo separado). Cuando termina,
        llama a on_complete con el resultado y cambia el estado a
        AWAITING_APPROVAL.
        
        Args:
            on_progress: Callback de progreso (etapa, mensaje).
            on_complete: Callback cuando la tarea se completa.
        
        Returns:
            True si se inició la ejecución, False si no hay tareas pendientes.
        """
        if self._state not in (AgentState.PLANNED, AgentState.AWAITING_APPROVAL):
            return False
        
        # Encontrar la siguiente tarea pendiente
        next_index = -1
        for i, task in enumerate(self._plan):
            if task.status == TaskStatus.PENDING:
                next_index = i
                break
        
        if next_index < 0:
            # No hay más tareas pendientes
            self._state = AgentState.COMPLETED
            self._log.append("Todas las tareas completadas")
            return False
        
        self._current_task_index = next_index
        self._state = AgentState.EXECUTING
        self._cancelled = False
        
        task = self._plan[next_index]
        task.status = TaskStatus.EXECUTING
        task.attempt += 1
        
        self._log.append(f"Ejecutando {task.task_id} (intento {task.attempt}/{task.max_attempts})")
        
        # Ejecutar en hilo separado para no bloquear la GUI
        def _run():
            result = self._execute_single_task(task, on_progress)
            
            if self._cancelled:
                self._state = AgentState.CANCELLED
                task.status = TaskStatus.FAILED
                task.error = "Cancelado por el usuario"
            elif result.success:
                self._state = AgentState.AWAITING_APPROVAL
                task.status = TaskStatus.AWAITING_APPROVAL
                task.coder_output = result.coder_output
                task.assembled_content = result.assembled_content
                task.validation_result = result.validation_result
                self._log.append(f"Tarea {task.task_id} ejecutada OK — esperando aprobación")
            else:
                # Error en la ejecución
                if task.attempt >= task.max_attempts:
                    task.status = TaskStatus.FAILED
                    task.error = result.error
                    self._log.append(f"Tarea {task.task_id} FALLIDA tras {task.attempt} intentos: {result.error}")
                    # No cambiamos a FAILED global — las demás tareas pueden seguir
                    self._state = AgentState.PLANNED
                else:
                    # Reintento automático si es error de sintaxis
                    val = result.validation_result or {}
                    is_syntax_error = (
                        val.get("returncode", -1) != 0 and
                        "SyntaxError" in str(val.get("output", ""))
                    )
                    if is_syntax_error and task.attempt < task.max_attempts:
                        self._log.append(f"SyntaxError detectado — reintento automático ({task.attempt}/{task.max_attempts})")
                        task.rejection_feedback = f"SyntaxError en el código anterior: {val.get('output', '')[:500]}"
                        # Reintentar automáticamente
                        task.status = TaskStatus.PENDING
                        # Programar reintento
                        self.root_after_safe(0, lambda: self.execute_next(on_progress, on_complete))
                        return
                    else:
                        task.status = TaskStatus.AWAITING_APPROVAL  # Pausar para intervención humana
                        self._state = AgentState.AWAITING_APPROVAL
                        task.error = result.error
                        task.coder_output = result.coder_output
                        task.assembled_content = result.assembled_content
                        task.validation_result = result.validation_result
                        self._log.append(f"Tarea {task.task_id} con errores — esperando decisión del Director")
            
            if on_complete:
                on_complete(result)
        
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return True

    def approve(self) -> bool:
        """
        Aprueba la tarea actual y guarda los cambios en disco.
        
        Returns:
            True si se aprobó correctamente, False si no hay tarea pendiente.
        """
        if self._state != AgentState.AWAITING_APPROVAL:
            return False
        
        task = self.current_task
        if not task:
            return False
        
        # Guardar el contenido integrado en disco
        if task.script and task.assembled_content and self.project_root:
            file_path = self._resolve_file(task.script)
            if file_path:
                # Crear directorio si no existe
                os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else ".", exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(task.assembled_content)
                self._log.append(f"Tarea {task.task_id} APROBADA — guardado en {file_path}")
                # Actualizar contenido original para la siguiente tarea
                self._original_contents[task.script] = task.assembled_content
            else:
                self._log.append(f"Tarea {task.task_id} APROBADA — archivo no encontrado para guardar")
        else:
            self._log.append(f"Tarea {task.task_id} APROBADA")
        
        task.status = TaskStatus.APPROVED
        self._state = AgentState.PLANNED
        
        # Verificar si quedan tareas pendientes
        pending = sum(1 for t in self._plan if t.status == TaskStatus.PENDING)
        if pending == 0:
            self._state = AgentState.COMPLETED
            self._log.append("Plan completado — todas las tareas aprobadas")
        
        return True

    def reject(self, feedback: str = "") -> bool:
        """
        Rechaza la tarea actual. Si quedan intentos, se reintenta con
        las instrucciones de corrección. Si no, se marca como fallida.
        
        Args:
            feedback: Instrucciones de corrección del Director.
        
        Returns:
            True si se va a reintentar, False si se marca como fallida.
        """
        if self._state != AgentState.AWAITING_APPROVAL:
            return False
        
        task = self.current_task
        if not task:
            return False
        
        task.rejection_feedback = feedback
        task.status = TaskStatus.REJECTED
        self._log.append(f"Tarea {task.task_id} RECHAZADA — feedback: {feedback[:100]}")
        
        if task.attempt < task.max_attempts:
            # Reintentar — cambiar estado a pendiente
            task.status = TaskStatus.PENDING
            self._state = AgentState.PLANNED
            self._log.append(f"Tarea {task.task_id} — reintento {task.attempt + 1}/{task.max_attempts}")
            return True
        else:
            # Máximo de intentos alcanzado — marcar como fallida
            task.status = TaskStatus.FAILED
            self._state = AgentState.PLANNED
            self._log.append(f"Tarea {task.task_id} — máximo de intentos alcanzado, marcada como FALLIDA")
            # Verificar si quedan tareas pendientes
            pending = sum(1 for t in self._plan if t.status == TaskStatus.PENDING)
            if pending == 0:
                self._state = AgentState.COMPLETED
            return False

    def skip_task(self) -> bool:
        """
        Salta la tarea actual sin aprobarla ni guardarla.
        
        Returns:
            True si se saltó correctamente.
        """
        if self._state != AgentState.AWAITING_APPROVAL:
            return False
        
        task = self.current_task
        if not task:
            return False
        
        task.status = TaskStatus.SKIPPED
        self._state = AgentState.PLANNED
        self._log.append(f"Tarea {task.task_id} SALTADA")
        
        pending = sum(1 for t in self._plan if t.status == TaskStatus.PENDING)
        if pending == 0:
            self._state = AgentState.COMPLETED
        
        return True

    # ─── Ejecución de tarea única (interna) ───

    def _execute_single_task(
        self,
        task: TaskInfo,
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> SemiAutoResult:
        """Ejecuta una tarea individual: Codificador → Integrador → Validación.
        
        v3.0: Reemplaza el Ensamblador mecánico por el Integrador (LLM).
        El Integrador recibe el archivo original, la especificación y el código
        del Codificador, y produce el archivo final integrado.
        """
        result = SemiAutoResult()
        result.task_id = task.task_id
        result.script_name = task.script
        
        try:
            # ─── ETAPA 2: Llamar al Codificador ───
            self._report(on_progress, "codificador", 
                         f"Consultando Codificador para {task.task_id}...")
            self._log.append(f"[CODIFICADOR] {task.task_id} — Enviando consulta al LLM...")
            
            # Obtener contenido actual del archivo
            original_content = self._original_contents.get(task.script, "")
            if not original_content and task.script and self.project_root:
                file_path = self._resolve_file(task.script)
                if file_path and os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        original_content = f.read()
            
            # Construir prompt del Codificador
            coder_user_prompt = self._build_coder_prompt(
                task.planner_output, original_content,
                correction_feedback=task.rejection_feedback if task.attempt > 1 else ""
            )

            coder_response = call_llm(
                task_type="generation",
                system_prompt=CODIFICADOR_SYSTEM_PROMPT,
                user_prompt=coder_user_prompt,
                max_tokens=4000,
                temperature=0.1,
                project_id=self._project_id,
            )

            if not coder_response.get("success"):
                result.error = f"Error del Codificador (modelo: {coder_response.get('model_used','?')}, intentos: {coder_response.get('attempts','?')}): {coder_response.get('error', 'sin respuesta')}"
                self._log.append(f"[CODIFICADOR] ERROR: {result.error}")
                self._report(on_progress, "codificador", f"Error: {coder_response.get('error', 'sin respuesta')}")
                return result

            coder_output = coder_response["content"]
            result.coder_output = coder_output
            result.model_used_coder = coder_response.get("model_used", "")
            # Métricas del codificador
            result.coding_provider = coder_response.get("provider", "")
            result.coding_tokens_input = coder_response.get("tokens_input", 0)
            result.coding_tokens_output = coder_response.get("tokens_output", 0)
            result.coding_latency_ms = coder_response.get("latency_ms", 0)
            result.coding_cost_usd = coder_response.get("cost_usd", 0.0)
            result.coding_arena_score = coder_response.get("arena_score")
            self._log.append(f"[CODIFICADOR] OK — modelo: {result.model_used_coder}, intentos: {coder_response.get('attempts', '?')}")
            self._report(on_progress, "codificador", f"Código generado (modelo: {result.model_used_coder})")

            if self._cancelled:
                result.error = "Cancelado por el usuario"
                return result

            # ─── ETAPA 3: Integrar (v3.0: reemplaza al Ensamblador mecánico) ───
            self._report(on_progress, "integrador", 
                         f"Integrando {task.task_id}...")
            self._log.append(f"[INTEGRADOR] {task.task_id} — Integrando código en {task.script}...")

            integrator_prompts = _get_integrador_prompts()
            integrator_user_prompt = integrator_prompts["user_template"].format(
                script_name=task.script,
                original_content=original_content if original_content else "# (archivo nuevo)",
                planner_specification=task.planner_output,
                coder_code=self._extract_python_code(coder_output),
            )

            # Si es un reintento, añadir contexto de corrección
            integrator_system = integrator_prompts["system"]
            if task.attempt > 1 and task.rejection_feedback:
                integrator_system += integrator_prompts["correction_addendum"].format(
                    feedback=task.rejection_feedback
                )

            integrator_response = call_llm(
                task_type="integration",
                system_prompt=integrator_system,
                user_prompt=integrator_user_prompt,
                max_tokens=8000,  # El integrador devuelve el archivo completo
                temperature=0.1,
                project_id=self._project_id,
            )

            if not integrator_response.get("success"):
                result.error = f"Error del Integrador (modelo: {integrator_response.get('model_used','?')}): {integrator_response.get('error', 'sin respuesta')}"
                self._log.append(f"[INTEGRADOR] ERROR: {result.error}")
                self._report(on_progress, "integrador", f"Error: {integrator_response.get('error', 'sin respuesta')}")
                return result

            integrated_content = self._extract_python_code(integrator_response["content"])
            result.assembled_content = integrated_content
            result.model_used_integrator = integrator_response.get("model_used", "")
            # Métricas del integrador
            result.integration_provider = integrator_response.get("provider", "")
            result.integration_tokens_input = integrator_response.get("tokens_input", 0)
            result.integration_tokens_output = integrator_response.get("tokens_output", 0)
            result.integration_latency_ms = integrator_response.get("latency_ms", 0)
            result.integration_cost_usd = integrator_response.get("cost_usd", 0.0)
            result.integration_arena_score = integrator_response.get("arena_score")

            self._log.append(f"[INTEGRADOR] OK — modelo: {result.model_used_integrator}")
            self._report(on_progress, "integrador", f"Código integrado (modelo: {result.model_used_integrator})")

            # ─── ETAPA 4: Validar ───
            self._report(on_progress, "validador", "Validando código integrado...")
            self._log.append(f"[VALIDADOR] {task.task_id} — Validando...")

            validation_result = AssemblyValidator.validate(
                content=integrated_content,
                script_path=task.script,
                validation_mode="auto",
            )
            result.validation_result = validation_result

            val_rc = validation_result.get("returncode", -1)
            if val_rc == 0:
                self._log.append(f"[VALIDADOR] Validación OK")
                result.success = True
            else:
                val_out = validation_result.get("output", "")[:300]
                self._log.append(f"[VALIDADOR] Validación FALLIDA: {val_out}")
                # v3.0: Si la validación falla, marcamos como no exitoso
                # pero aún entregamos el contenido para que el Director decida
                result.success = False
                result.error = f"Validación fallida: {val_out}"

            result.planner_output = task.planner_output
            self._report(
                on_progress,
                "integrador",
                "Integración completada" if result.success else "Integración con errores de validación"
            )

            return result

        except Exception as e:
            result.error = f"Error inesperado: {e}"
            self._log.append(f"EXCEPCIÓN: {e}")
            logger.error(f"SemiAutoAgent._execute_single_task error: {e}", exc_info=True)
            return result

    # ─── Compatibilidad: run() para tarea única ───

    def run(
        self,
        user_prompt: str,
        target_file: str = "",
        original_content: str = "",
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> SemiAutoResult:
        """
        Ejecuta el pipeline semi-autónomo completo (tarea única).
        
        Método de compatibilidad que combina generate_plan() + execute_next()
        en una sola llamada. Para multi-tarea, usar generate_plan() + execute_next().
        """
        self._cancelled = False
        result = SemiAutoResult()
        result.log.append(f"Inicio: {user_prompt[:80]}")

        try:
            # ─── ETAPA 1: Llamar al Planificador ───
            self._report(on_progress, "planificador", "Consultando Planificador...")
            
            planner_user_prompt = self._build_planner_prompt(
                user_prompt, target_file, original_content
            )

            planner_response = call_llm(
                task_type="planning",
                system_prompt=PLANIFICADOR_SYSTEM_PROMPT,
                user_prompt=planner_user_prompt,
                max_tokens=3000,
                temperature=0.1,
                project_id=self._project_id,
            )

            if not planner_response.get("success"):
                result.error = f"Error del Planificador: {planner_response.get('error', 'sin respuesta')}"
                result.log.append(f"ERROR Planificador: {result.error}")
                return result

            planner_output = planner_response["content"]
            result.planner_output = planner_output
            result.model_used_planner = planner_response.get("model_used", "")
            # Métricas del planificador
            result.planning_provider = planner_response.get("provider", "")
            result.planning_tokens_input = planner_response.get("tokens_input", 0)
            result.planning_tokens_output = planner_response.get("tokens_output", 0)
            result.planning_latency_ms = planner_response.get("latency_ms", 0)
            result.planning_cost_usd = planner_response.get("cost_usd", 0.0)
            result.planning_arena_score = planner_response.get("arena_score")
            # Guardar metadata del planificador
            planner_llm_metadata = _extract_llm_metadata(planner_response, "planning")
            result.log.append(f"Planificador OK (modelo: {result.model_used_planner})")

            if self._cancelled:
                result.error = "Cancelado por el usuario"
                return result

            # ─── ETAPA 1.5: Parsear output del Planificador (v3.0: sin anclas) ───
            parsed = V3PlanParser.parse_single(planner_output)
            non_anchor_errors = [e for e in parsed.get("errores", []) if "ANCLA" not in e.upper()]
            if non_anchor_errors:
                result.error = f"Error de parseo del Planificador: {'; '.join(non_anchor_errors)}"
                result.log.append(f"ERROR parseo: {result.error}")
                return result

            result.script_name = parsed.get("script", target_file)
            result.task_id = parsed.get("tarea_id", "T1")

            # Resolver archivo si no se proporcionó target_file
            if not target_file:
                target_file = result.script_name

            # Obtener contenido original si no se proporcionó
            if not original_content and self.project_root and target_file:
                file_path = self._resolve_file(target_file)
                if file_path and os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        original_content = f.read()
                    result.log.append(f"Contenido original cargado: {len(original_content)} chars")

            self._report(on_progress, "planificador", f"Plan generado: {target_file} | {result.task_id}")

            # ─── ETAPA 2: Llamar al Codificador ───
            self._report(on_progress, "codificador", "Consultando Codificador...")

            coder_user_prompt = self._build_coder_prompt(planner_output, original_content)

            coder_response = call_llm(
                task_type="generation",
                system_prompt=CODIFICADOR_SYSTEM_PROMPT,
                user_prompt=coder_user_prompt,
                max_tokens=4000,
                temperature=0.1,
                project_id=self._project_id,
            )

            if not coder_response.get("success"):
                result.error = f"Error del Codificador (modelo: {coder_response.get('model_used','?')}, intentos: {coder_response.get('attempts','?')}): {coder_response.get('error', 'sin respuesta')}"
                result.log.append(f"ERROR Codificador: {result.error}")
                return result

            coder_output = coder_response["content"]
            result.coder_output = coder_output
            result.model_used_coder = coder_response.get("model_used", "")
            # Métricas del codificador
            result.coding_provider = coder_response.get("provider", "")
            result.coding_tokens_input = coder_response.get("tokens_input", 0)
            result.coding_tokens_output = coder_response.get("tokens_output", 0)
            result.coding_latency_ms = coder_response.get("latency_ms", 0)
            result.coding_cost_usd = coder_response.get("cost_usd", 0.0)
            result.coding_arena_score = coder_response.get("arena_score")
            result.log.append(f"Codificador OK (modelo: {result.model_used_coder})")

            if self._cancelled:
                result.error = "Cancelado por el usuario"
                return result

            # ─── ETAPA 3: Integrar (v3.0) ───
            self._report(on_progress, "integrador", "Integrando código...")

            integrator_prompts = _get_integrador_prompts()
            integrator_user_prompt = integrator_prompts["user_template"].format(
                script_name=target_file,
                original_content=original_content if original_content else "# (archivo nuevo)",
                planner_specification=planner_output,
                coder_code=self._extract_python_code(coder_output),
            )

            integrator_response = call_llm(
                task_type="integration",
                system_prompt=integrator_prompts["system"],
                user_prompt=integrator_user_prompt,
                max_tokens=8000,
                temperature=0.1,
                project_id=self._project_id,
            )

            if not integrator_response.get("success"):
                result.error = f"Error del Integrador: {integrator_response.get('error', 'sin respuesta')}"
                result.log.append(f"ERROR Integrador: {result.error}")
                return result

            integrated_content = self._extract_python_code(integrator_response["content"])
            result.assembled_content = integrated_content
            result.model_used_integrator = integrator_response.get("model_used", "")
            # Métricas del integrador
            result.integration_provider = integrator_response.get("provider", "")
            result.integration_tokens_input = integrator_response.get("tokens_input", 0)
            result.integration_tokens_output = integrator_response.get("tokens_output", 0)
            result.integration_latency_ms = integrator_response.get("latency_ms", 0)
            result.integration_cost_usd = integrator_response.get("cost_usd", 0.0)
            result.integration_arena_score = integrator_response.get("arena_score")
            result.log.append(f"Integrador OK (modelo: {result.model_used_integrator})")

            # ─── ETAPA 4: Validar ───
            self._report(on_progress, "validador", "Validando...")

            validation_result = AssemblyValidator.validate(
                content=integrated_content,
                script_path=target_file,
                validation_mode="auto",
            )
            result.validation_result = validation_result
            result.success = validation_result.get("returncode", -1) == 0

            result.log.append(f"Validación: {'OK' if result.success else 'CON ERRORES'}")

            return result

        except Exception as e:
            result.error = f"Error inesperado: {e}"
            result.log.append(f"EXCEPCIÓN: {e}")
            logger.error(f"SemiAutoAgent.run error: {e}", exc_info=True)
            return result

    # ─── Helpers ───

    def _build_planner_prompt(
        self,
        user_instruction: str,
        target_file: str,
        existing_content: str,
    ) -> str:
        """Construye el prompt de usuario para el Planificador.
        
        v3.0: Aumenta max_content a 8000 para que el Planificador tenga
        más contexto del archivo y pueda generar especificaciones más precisas.
        """
        prompt_parts = [f"INSTRUCCIÓN DEL DIRECTOR:\n{user_instruction}"]

        if target_file:
            prompt_parts.append(f"\nSCRIPT OBJETIVO: {target_file}")

        if existing_content:
            # v3.0: Aumentar límite de 4000 a 8000 para mejor contexto
            max_content = 8000
            content_to_include = existing_content
            if len(content_to_include) > max_content:
                content_to_include = content_to_include[:max_content] + "\n# ... (truncado)"
            prompt_parts.append(f"\nCONTENIDO ACTUAL DEL ARCHIVO:\n```python\n{content_to_include}\n```")

        # Si es un archivo nuevo, indicarlo
        if not existing_content and target_file:
            prompt_parts.append("\nNOTA: Este es un ARCHIVO NUEVO.")

        return "\n".join(prompt_parts)

    def _build_coder_prompt(
        self,
        planner_output: str,
        existing_content: str,
        correction_feedback: str = "",
    ) -> str:
        """Construye el prompt de usuario para el Codificador.
        
        v3.0: Aumenta max_content a 6000 para que el Codificador tenga
        más contexto del archivo existente.
        """
        prompt_parts = [planner_output]

        if existing_content:
            # v3.0: Aumentar límite de 3000 a 6000
            max_content = 6000
            content_to_include = existing_content
            if len(content_to_include) > max_content:
                content_to_include = content_to_include[:max_content] + "\n# ... (truncado)"
            prompt_parts.append(
                f"\nCONTEXTO — Código existente en el archivo:\n```python\n{content_to_include}\n```"
            )

        # Añadir contexto de corrección si es un reintento
        if correction_feedback:
            prompt_parts.append(
                f"\nOBSERVACIONES DEL DIRECTOR (versión anterior rechazada):\n{correction_feedback}"
            )
            prompt_parts.append(
                "\nCorrige el código para abordar estas observaciones. No repitas los mismos errores."
            )

        return "\n".join(prompt_parts)

    def _extract_python_code(self, llm_output: str) -> str:
        """Extrae el código Python de la respuesta del LLM.
        
        El Codificador y el Integrador devuelven código envuelto en
        ```python ... ```. Este método extrae solo el código.
        """
        # Intentar extraer bloque ```python ... ```
        pattern = r'```python\s*\n(.*?)```'
        match = re.search(pattern, llm_output, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Intentar bloque genérico ``` ... ```
        pattern = r'```\s*\n(.*?)```'
        match = re.search(pattern, llm_output, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Si no hay bloques, devolver tal cual
        return llm_output.strip()

    def _extract_task_block(self, planner_output: str, task_id: str) -> str:
        """Extrae el bloque del Planificador correspondiente a una tarea específica."""
        if not task_id:
            return planner_output
        
        # Buscar el bloque que contiene la tarea_id
        blocks = planner_output.split("---")
        for block in blocks:
            if task_id in block:
                return block.strip()
        
        # Si no se encuentra por task_id, devolver todo
        return planner_output

    def _resolve_file(self, script_name: str) -> Optional[str]:
        """Resuelve la ruta de un archivo relativo al proyecto."""
        if not self.project_root:
            return None

        # Buscar archivo en el proyecto
        root = self.project_root
        candidates = [
            os.path.join(root, script_name),
            os.path.join(root, "apa", script_name),
        ]

        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

        # Búsqueda recursiva
        for dirpath, dirnames, filenames in os.walk(root):
            # Ignorar dirs ocultos y __pycache__
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
            basename = os.path.basename(script_name)
            if basename in filenames:
                return os.path.join(dirpath, basename)

        # Si no se encuentra, crear la ruta (para ARCHIVO_NUEVO)
        candidate = os.path.join(root, script_name)
        return candidate

    def _report(
        self,
        callback: Optional[Callable[[str, str], None]],
        stage: str,
        message: str,
    ):
        """Reporta progreso al callback."""
        if callback:
            try:
                callback(stage, message)
            except Exception:
                pass

    def root_after_safe(self, ms, fn):
        """Stub para root.after() — la GUI debe sobreescribir esto."""
        # En modo consola, ejecutar directamente
        try:
            fn()
        except Exception:
            pass
