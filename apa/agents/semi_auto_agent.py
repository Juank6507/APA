# apa/agents/semi_auto_agent.py
"""
SemiAutoAgent — Agente semi-autónomo que orquesta el pipeline
Planificador → Codificador → Ensamblador usando call_llm().

Nivel 2 (AS3): Ejecución multi-tarea con retroalimentación paso a paso.

El Director describe una tarea, APA genera un plan de N subtareas,
las ejecuta una por una, el Director ve cada resultado y pulsa
Aprobar o Rechazar antes de pasar a la siguiente.

Si una tarea se rechaza, el Director puede dar instrucciones de
corrección y APA la reintenta (máximo 2 reintentos).

Flujo:
  IDLE → plan() → PLANNED → execute_next() → EXECUTING → AWAITING_APPROVAL
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
from core.assembler import Assembler, PlannerOutputParser

logger = logging.getLogger(__name__)

# ─── Helpers de métricas v2.0 ───

def _extract_llm_metadata(response: dict, prefix: str) -> dict:
    """Extrae métricas de una respuesta de call_llm() con un prefijo dado.
    
    call_llm() ahora retorna: tokens_input, tokens_output, latency_ms,
    cost_usd, arena_score, provider, model_used, success.
    
    El assembler._log_assembly_usage() espera claves como:
    planning_model, planning_provider, planning_tokens_input, etc.
    
    Args:
        response: Dict retornado por call_llm()
        prefix: "planning" o "coding"
    
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


def _build_llm_metadata(planner_metadata: dict, coder_response: dict) -> dict:
    """Construye el dict llm_metadata completo para assembler.run_full().
    
    Combina la metadata del planificador (ya extraída) con la metadata
    del codificador (recién recibida) en un solo dict que el ensamblador
    usa para registrar 3 entradas en UsageTracker:
    1. assembly (proceso local)
    2. planning (LLM planificador)
    3. coding (LLM codificador)
    
    Args:
        planner_metadata: Dict de _extract_llm_metadata(planner_response, "planning")
        coder_response: Dict retornado por call_llm() para el codificador
    
    Returns:
        Dict combinado con claves planning_* y coding_*
    """
    coder_metadata = _extract_llm_metadata(coder_response, "coding")
    metadata = {}
    metadata.update(planner_metadata)
    metadata.update(coder_metadata)
    # Arena score global (del modelo de planning, que es el que seleccionó el router)
    metadata["arena_score"] = planner_metadata.get("planning_arena_score")
    return metadata

# ─── Estados del agente ───

class AgentState(Enum):
    """Estados de la máquina de estados del SemiAutoAgent."""
    IDLE = "idle"
    PLANNING = "planning"
    PLANNED = "planned"            # Plan generado, esperando ejecución
    EXECUTING = "executing"        # Ejecutando tarea (Codificador + Ensamblador)
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
    assembled_content: str = ""    # Contenido ensamblado resultante
    validation_result: dict = field(default_factory=dict)
    error: Optional[str] = None
    rejection_feedback: str = ""   # Instrucciones de corrección del Director


@dataclass
class SemiAutoResult:
    """Resultado del pipeline semi-autónomo (tarea única).

    v2.0: Incluye métricas completas de las llamadas LLM.
    """
    success: bool = False
    planner_output: str = ""
    coder_output: str = ""
    assembled_content: str = ""
    script_name: str = ""
    task_id: str = ""
    validation_result: dict = field(default_factory=dict)
    error: Optional[str] = None
    model_used_planner: str = ""
    model_used_coder: str = ""
    log: list = field(default_factory=list)
    # v2.0: Métricas completas de las llamadas LLM
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


@dataclass
class PlanResult:
    """Resultado de la fase de planificación."""
    success: bool = False
    tasks: List[TaskInfo] = field(default_factory=list)
    raw_planner_output: str = ""
    error: Optional[str] = None
    model_used: str = ""
    log: list = field(default_factory=list)


# ─── System Prompts (de Prompts_Iniciales_Agentes.md) ───

PLANIFICADOR_SYSTEM_PROMPT = """Eres un Ingeniero de Software Senior. Tu rol es el de Agente Planificador de Ensamblaje Atómico del proyecto APA.

## FORMATO DE SALIDA

Tu respuesta SIEMPRE debe ser UN ÚNICO bloque ```markdown```. Sin texto antes ni después.

Plantilla para UNA tarea:

## TAREA DE ENSAMBLAJE
- SCRIPT: {ruta/archivo.py}
- TAREA_ID: {ID}
- ANCLA: {ANCLA_AST}
- MODO_EJECUCION: {local | nas}

## BLOQUE

# INSTRUCCIÓN PARA CODIFICADOR:
# {descripción técnica}
# INDENTACIÓN: {0 | 4 | 8}
# DATOS ESPECÍFICOS:
# {contexto de estructuras existentes si aplica}

# VALIDACIÓN:
# - {criterio verificable}

## IMPORTS_NUEVOS
{módulo}

Omite IMPORTS_NUEVOS si no hay imports.

Para múltiples tareas, repite el bloque ## TAREA DE ENSAMBLAJE separado por ---.

## REGLAS CRÍTICAS

1. **UN ANCLA = UNA OPERACIÓN**: Cada tarea tiene su propia ancla.
2. **SEPARACIÓN DE ROLES**: El BLOQUE contiene SOLO comentarios de instrucción. NUNCA código ejecutable.
3. **DATOS ESPECÍFICOS OBLIGATORIOS**: Cuando la tarea implique estructura EXISTENTE, indica qué existe en esa posición.
4. **REGLA ANTI-ERROR IMPORTS**: Tarea solo imports → BLOQUE VACÍO.
5. **APIs EXTERNAS**: Especificar SIEMPRE la firma completa.

## ANCLAS DISPONIBLES

INICIO_ARCHIVO | FIN_ARCHIVO | FIN_CLASE:Nombre | INICIO_CLASE:Nombre
ANTES_FUNCION:nombre | DESPUES_FUNCION:nombre | REEMPLAZAR_FUNCION:nombre
ANTES_CLASE:Nombre | DESPUES_METODO:Clase.metodo | REEMPLAZAR_METODO:Clase.met
FIN_IMPORTS | INSERTAR_ANTES_MAIN | REEMPLAZAR_BLOQUE_MAIN | ARCHIVO_NUEVO

## REGLA DE ELECCIÓN

- Archivo nuevo → ARCHIVO_NUEVO
- Añadir algo nuevo → ANTES_FUNCION, DESPUES_FUNCION, FIN_CLASE
- Modificar existente → REEMPLAZAR_FUNCION, REEMPLAZAR_METODO
- Solo imports → IMPORTS_NUEVOS (BLOQUE vacío)
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
2. Indentación: aplica INDENTACIÓN: X espacios si se especifica.
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
    Prompt → Planificador (LLM) → Codificador (LLM) → Ensamblador
    
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
        self._project_id = project_id  # v2.0: Para tracking de métricas
        self.assembler = Assembler()
        self._cancelled = False
        
        # Estado de la máquina de estados
        self._state = AgentState.IDLE
        self._plan: List[TaskInfo] = []
        self._current_task_index = -1
        self._raw_planner_output = ""
        self._original_contents: Dict[str, str] = {}  # script → contenido original
        self._log: List[str] = []
        self._model_used_planner = ""
        # v2.0: Metadata de la última llamada al planificador (para pasar al ensamblador)
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

    def plan(
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
            
            # Construir prompt del Planificador
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
            # v2.0: Guardar metadata del planificador para pasar al ensamblador
            self._planner_llm_metadata = _extract_llm_metadata(planner_response, "planning")
            result.log = self._log.copy()
            self._log.append(f"[PLANIFICADOR] OK — modelo: {result.model_used}, intentos: {planner_response.get('attempts', '?')}")
            self._report(on_progress, "planificador", f"Planificador respondió (modelo: {result.model_used})")

            if self._cancelled:
                self._state = AgentState.CANCELLED
                result.error = "Cancelado por el usuario"
                return result

            # Parsear output del Planificador en tareas
            self._log.append(f"[PLANIFICADOR] Parseando output ({len(planner_output)} chars)...")
            self._report(on_progress, "planificador", "Parseando plan...")
            blocks_data = PlannerOutputParser._parse_blocks(planner_output)
            
            if not blocks_data:
                # Intentar parseo simple (tarea única sin formato de bloques)
                self._log.append("[PLANIFICADOR] Sin bloques multi-tarea — intentando parseo simple...")
                parsed = PlannerOutputParser.parse(planner_output)
                if parsed.get("errores"):
                    result.error = f"Error de parseo: {'; '.join(parsed['errores'])}"
                    self._log.append(f"[PLANIFICADOR] ERROR parseo: {result.error}")
                    self._state = AgentState.FAILED
                    return result
                blocks_data = [{
                    "script": parsed.get("script", target_file),
                    "tarea_id": parsed.get("tarea_id", "T1"),
                    "anchor": parsed.get("ancla_raw", "FIN_ARCHIVO"),
                }]
            
            # Crear TaskInfo para cada bloque
            for bd in blocks_data:
                task = TaskInfo(
                    task_id=bd.get("tarea_id", f"T{len(self._plan)+1}"),
                    script=bd.get("script", target_file),
                    anchor=bd.get("anchor", "FIN_ARCHIVO"),
                    planner_output=self._extract_task_block(planner_output, bd.get("tarea_id", "")),
                    status=TaskStatus.PENDING,
                )
                self._plan.append(task)
                self._log.append(f"[PLANIFICADOR] Tarea planificada: {task.task_id} → {task.script} @ {task.anchor}")
            
            result.tasks = self._plan
            result.success = True
            
            self._state = AgentState.PLANNED
            self._report(on_progress, "planificador", 
                         f"Plan generado: {len(self._plan)} tarea(s)")
            
            return result

        except Exception as e:
            result.error = f"Error inesperado en planificación: {e}"
            self._log.append(f"EXCEPCIÓN: {e}")
            logger.error(f"SemiAutoAgent.plan error: {e}", exc_info=True)
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
                    # Reintento automático si es error de sintaxis (P4 del asesor)
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
        
        # Guardar el contenido ensamblado en disco
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
        """Ejecuta una tarea individual: Codificador → Ensamblador."""
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
            # v2.0: Métricas del codificador
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

            self._report(on_progress, "codificador", "Código generado, ensamblando...")

            # ─── ETAPA 3: Ensamblar ───
            self._report(on_progress, "ensamblador", 
                         f"Ensamblando {task.task_id}...")
            self._log.append(f"[ENSAMBLADOR] {task.task_id} — Ensamblando código en {task.script}...")

            # v2.0: Construir llm_metadata con métricas de planning + coding
            coder_llm_metadata = _build_llm_metadata(
                planner_metadata=self._planner_llm_metadata,
                coder_response=coder_response,
            )

            assembly_result = self.assembler.run_full(
                planner_text=task.planner_output,
                coder_text=coder_output,
                original_content=original_content,
                script_name=task.script,
                duplicate_action="replace",
                validation_override="new",
                project_id=self._project_id,
                llm_metadata=coder_llm_metadata,
            )

            result.assembled_content = assembly_result.assembled_content
            result.validation_result = assembly_result.validation_result
            result.success = assembly_result.success
            result.planner_output = task.planner_output
            self._log.append(f"[ENSAMBLADOR] {task.task_id} — {'OK' if assembly_result.success else 'CON ERRORES'}")
            
            # Log de validación
            val = result.validation_result or {}
            val_rc = val.get("returncode", -1)
            if val_rc == 0:
                self._log.append(f"[ENSAMBLADOR] Validación OK (sin errores de sintaxis)")
            else:
                val_out = val.get("output", "")[:200]
                self._log.append(f"[ENSAMBLADOR] Validación: returncode={val_rc}, output: {val_out}")

            if hasattr(assembly_result, 'log') and assembly_result.log:
                result.log = assembly_result.log

            self._report(
                on_progress,
                "ensamblador",
                "Ensamblaje completado" if assembly_result.success else "Ensamblaje con errores"
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
        
        Método de compatibilidad que combina plan() + execute_next()
        en una sola llamada. Para multi-tarea, usar plan() + execute_next().
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
            # v2.0: Métricas del planificador
            result.planning_provider = planner_response.get("provider", "")
            result.planning_tokens_input = planner_response.get("tokens_input", 0)
            result.planning_tokens_output = planner_response.get("tokens_output", 0)
            result.planning_latency_ms = planner_response.get("latency_ms", 0)
            result.planning_cost_usd = planner_response.get("cost_usd", 0.0)
            result.planning_arena_score = planner_response.get("arena_score")
            # v2.0: Guardar metadata del planificador para pasar al ensamblador
            planner_llm_metadata = _extract_llm_metadata(planner_response, "planning")
            result.log.append(f"Planificador OK (modelo: {result.model_used_planner})")

            if self._cancelled:
                result.error = "Cancelado por el usuario"
                return result

            # ─── ETAPA 1.5: Parsear output del Planificador ───
            parsed = PlannerOutputParser.parse(planner_output)
            if parsed.get("errores"):
                result.error = f"Error de parseo del Planificador: {'; '.join(parsed['errores'])}"
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
            # v2.0: Métricas del codificador
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

            self._report(on_progress, "codificador", "Código generado, ensamblando...")

            # ─── ETAPA 3: Ensamblar ───
            self._report(on_progress, "ensamblador", "Ensamblando código...")

            # v2.0: Construir llm_metadata con métricas de planning + coding
            run_llm_metadata = _build_llm_metadata(
                planner_metadata=planner_llm_metadata,
                coder_response=coder_response,
            )

            assembly_result = self.assembler.run_full(
                planner_text=planner_output,
                coder_text=coder_output,
                original_content=original_content,
                script_name=target_file,
                duplicate_action="replace",
                validation_override="new",
                project_id=self._project_id,
                llm_metadata=run_llm_metadata,
            )

            result.assembled_content = assembly_result.assembled_content
            result.validation_result = assembly_result.validation_result
            result.success = assembly_result.success
            result.log.append(f"Ensamblaje {'OK' if assembly_result.success else 'CON ERRORES'}")

            if hasattr(assembly_result, 'log') and assembly_result.log:
                result.log.extend(assembly_result.log)

            self._report(
                on_progress,
                "ensamblador",
                "Ensamblaje completado" if assembly_result.success else "Ensamblaje con errores"
            )

            return result

        except Exception as e:
            result.error = f"Error inesperado: {e}"
            result.log.append(f"EXCEPCIÓN: {e}")
            logger.error(f"SemiAutoAgent error: {e}", exc_info=True)
            return result

    def run_multi_task(
        self,
        user_prompt: str,
        target_file: str = "",
        original_content: str = "",
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> List[SemiAutoResult]:
        """
        Ejecuta el pipeline para tareas múltiples.
        El Planificador puede generar múltiples TAREA DE ENSAMBLAJE,
        y se ejecutan secuencialmente.
        
        Nota: Para control paso a paso desde la GUI, usar plan() + execute_next().
        Este método ejecuta todo de forma automática sin intervención.
        """
        plan_result = self.plan(user_prompt, target_file, on_progress)
        if not plan_result.success:
            result = SemiAutoResult(success=False, error=plan_result.error)
            return [result]
        
        results = []
        while self.state == AgentState.PLANNED:
            # Ejecutar siguiente tarea (síncrono para este método)
            task = None
            for t in self._plan:
                if t.status == TaskStatus.PENDING:
                    task = t
                    break
            if not task:
                break
            
            single_result = self._execute_single_task(task, on_progress)
            results.append(single_result)
            
            if single_result.success:
                # Auto-aprobar (este método es sin intervención)
                task.status = TaskStatus.APPROVED
                task.assembled_content = single_result.assembled_content
                task.coder_output = single_result.coder_output
                task.validation_result = single_result.validation_result
                # Guardar en disco
                if task.script and task.assembled_content and self.project_root:
                    file_path = self._resolve_file(task.script)
                    if file_path:
                        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else ".", exist_ok=True)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(task.assembled_content)
                        self._original_contents[task.script] = task.assembled_content
                self._log.append(f"Tarea {task.task_id} auto-aprobada")
            else:
                task.status = TaskStatus.FAILED
                task.error = single_result.error
                self._log.append(f"Tarea {task.task_id} falló: {single_result.error}")
        
        self._state = AgentState.COMPLETED
        return results

    # ─── Helpers ───

    def _build_planner_prompt(
        self,
        user_instruction: str,
        target_file: str,
        existing_content: str,
    ) -> str:
        """Construye el prompt de usuario para el Planificador."""
        prompt_parts = [f"INSTRUCCIÓN DEL DIRECTOR:\n{user_instruction}"]

        if target_file:
            prompt_parts.append(f"\nSCRIPT OBJETIVO: {target_file}")

        if existing_content:
            # Incluir estructura del archivo existente para contexto
            # Limitar tamaño para no exceder tokens del modelo
            max_content = 4000
            content_to_include = existing_content
            if len(content_to_include) > max_content:
                content_to_include = content_to_include[:max_content] + "\n# ... (truncado)"
            prompt_parts.append(f"\nCONTENIDO ACTUAL DEL ARCHIVO:\n```python\n{content_to_include}\n```")

        # Si es un archivo nuevo, indicarlo
        if not existing_content and target_file:
            prompt_parts.append("\nNOTA: Este es un ARCHIVO NUEVO. Usa ANCLA: ARCHIVO_NUEVO.")

        return "\n".join(prompt_parts)

    def _build_coder_prompt(
        self,
        planner_output: str,
        existing_content: str,
        correction_feedback: str = "",
    ) -> str:
        """Construye el prompt de usuario para el Codificador."""
        prompt_parts = [planner_output]

        if existing_content:
            # Incluir contexto del archivo existente (truncado)
            max_content = 3000
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
