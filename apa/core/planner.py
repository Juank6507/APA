# apa/core/planner.py
import sys
import os
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
from core.router import select_model, escalate_model, call_llm
from core.spec_parser import parse_multi_file_spec
from core.language_detector import LanguageDetector

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

def _clean_llm_response(response_text: str) -> str:
    cleaned = response_text.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def _slugify(text: str) -> str:
    """Convierte una ruta de archivo en un slug válido para ID de tarea."""
    slug = re.sub(r'[\\/]', '_', text)
    slug = re.sub(r'\.py$', '', slug, flags=re.IGNORECASE)
    slug = re.sub(r'[^a-zA-Z0-9_]', '_', slug)
    slug = re.sub(r'_+', '_', slug)
    return slug.strip('_').lower() or "task"

def parse_spec(spec_path: str) -> dict:
    logger.info(f"Parsing spec: {spec_path}")

    # T12/A2: Intentar parseo multi-archivo primero
    try:
        multi_spec = parse_multi_file_spec(spec_path)
        if multi_spec.get("files") and len(multi_spec["files"]) > 0:
            logger.info(f"Spec detected as multi-file: {len(multi_spec['files'])} files")
            multi_spec["multi_file"] = True
            multi_spec["spec_path"] = spec_path
            return multi_spec
    except Exception as e:
        logger.warning(f"Multi-file parse failed, falling back to LLM: {e}")

    # Fallback: método original con LLM
    try:
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_content = f.read()
    except Exception as e:
        logger.error(f"Failed to read spec file: {e}")
        return {
            "error": f"No se pudo leer el archivo: {e}",
            "spec_path": spec_path,
            "raw_spec": "",
            "objetivo": None,
            "restricciones": [],
            "inputs_disponibles": [],
            "output_esperado": None,
            "criterio_exito": None,
            "multi_file": False
        }

    system_prompt = (
        "Eres un analizador de especificaciones de software.  "
        "Extraes información estructurada de specs escritas  "
        "en lenguaje natural. Respondes ÚNICAMENTE con JSON  "
        "válido, sin texto adicional, sin bloques markdown,  "
        "sin explicaciones."
    )

    user_prompt = (
        f"Analiza esta especificación de software y extrae  "
        f"la siguiente información en JSON:\n"
        f"{{\n"
        f'    "objetivo": string o null,\n'
        f'    "restricciones": array de strings o [],\n'
        f'    "inputs_disponibles": array de strings o [],\n'
        f'    "output_esperado": string o null,\n'
        f'    "criterio_exito": string o null\n'
        f"}}\n"
        f"Reglas:\n"
        f"- Si un campo no está explícito en la spec → null o []\n"
        f"- Nunca inventes información que no esté en la spec\n"
        f"- El JSON debe ser parseable directamente\n"
        f"\n"
        f"Spec a analizar:\n"
        f"{spec_content}"
    )

    result = call_llm(
        task_type="planning",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=1000
    )

    if not result.get("success"):
        logger.error(f"Failed to parse spec: {result.get('error')}")
        return {
            "error": "No se pudo parsear la spec",
            "spec_path": spec_path,
            "raw_spec": spec_content,
            "objetivo": None,
            "restricciones": [],
            "inputs_disponibles": [],
            "output_esperado": None,
            "criterio_exito": None,
            "multi_file": False
        }

    try:
        cleaned = _clean_llm_response(result.get("content", ""))
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        return {
            "error": "No se pudo parsear la spec",
            "spec_path": spec_path,
            "raw_spec": spec_content,
            "objetivo": None,
            "restricciones": [],
            "inputs_disponibles": [],
            "output_esperado": None,
            "criterio_exito": None,
            "multi_file": False
        }

    final_result = {
        "objetivo": parsed.get("objetivo"),
        "restricciones": parsed.get("restricciones", []),
        "inputs_disponibles": parsed.get("inputs_disponibles", []),
        "output_esperado": parsed.get("output_esperado"),
        "criterio_exito": parsed.get("criterio_exito"),
        "spec_path": spec_path,
        "model_used": result.get("model_used"),
        "raw_spec": spec_content,
        "multi_file": False
    }

    logger.info(f"Spec parsed successfully: objetivo={final_result.get('objetivo')}")
    return final_result

def generate_plan(spec: dict) -> dict:
    logger.info("Generating plan from spec")

    if spec.get("error"):
        logger.warning("Spec has error, cannot generate plan")
        return {
            "error": "Spec inválida, no se puede generar plan",
            "project_id": None
        }

    project_id = str(uuid.uuid4())
    logger.info(f"Generated project_id: {project_id}")

    # T13/A2c: Detectar spec multi-archivo
    if spec.get("multi_file") and spec.get("files"):
        logger.info(f"Generating plan for multi-file spec: {len(spec['files'])} files")
        return _generate_multi_file_plan(spec, project_id)

    # Comportamiento original para specs simples
    return _generate_simple_plan(spec, project_id)

def _generate_multi_file_plan(spec: dict, project_id: str) -> dict:
    """Genera un plan a partir de una especificación multi-archivo."""
    tasks = []
    file_map = {}  # path -> task_id para resolver dependencias

    # Primera pasada: crear tareas y mapear paths a IDs
    for file_spec in spec["files"]:
        file_path = file_spec["path"]
        # A2c: Propagar target_path con fallback a path si no existe
        target_path = file_spec.get("target_path", file_path)

        task_id = _slugify(file_path)
        file_map[file_path] = task_id

        # Mapear dependencias de paths a task_ids
        depends_on = []
        for dep_path in file_spec.get("depends_on", []):
            if dep_path in file_map:
                depends_on.append(file_map[dep_path])

        # Propagar campo language desde spec_parser
        language = file_spec.get("language", "python")
        logger.debug(f"Task {task_id} language: {language}")

        task = {
            "id": task_id,
            "name": f"Crear {file_path}",
            "description": file_spec.get("description", ""),
            "depends_on": depends_on,
            "inputs": file_spec.get("imports", []),
            "expected_output": f"Archivo {file_path} generado y funcional",
            "acceptance_criterion": file_spec.get("acceptance_criteria") or spec.get("global_acceptance", "El archivo se genera sin errores de sintaxis"),
            "task_type": "generation",
            "status": "pending",
            "attempts": 0,
            "result": None,
            "model_used": None,
            # Campos adicionales para trazabilidad multi-archivo
            "file_path": file_path,
            "target_path": target_path, # A2c: Clave requerida por GeneratorAgent
            "imports": file_spec.get("imports", []),
            "language": language  # <-- NUEVO: campo language propagado
        }
        tasks.append(task)

    plan_result = {
        "project_id": project_id,
        "created_at": datetime.utcnow().isoformat(),
        "spec_summary": spec.get("project_name", "Proyecto multi-archivo"),
        "tasks": tasks,
        "model_used": None,  # No se usó LLM para planificación
        "multi_file": True,
        "files_count": len(tasks)
    }

    # Guardar plan en disco
    specs_dir = Path(__file__).parents[1] / "specs"
    project_dir = specs_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    plan_path = project_dir / "plan.json"

    with open(plan_path, 'w', encoding='utf-8') as f:
        json.dump(plan_result, f, indent=2, ensure_ascii=False)

    logger.info(f"Multi-file plan saved to {plan_path} with {len(tasks)} tasks")
    return plan_result

def replan_task(task: dict, plan: dict, error_context: dict) -> dict:
    """Replantea una tarea que falló tras agotar los intentos de corrección.

    Recibe una tarea fallida junto con toda la información de los errores
    y se la pasa al planificador para que decida cómo proceder:

    - Dividirla en subtareas más simples
    - Simplificarla con un enfoque menos ambicioso
    - Sustituirla por una tarea diferente que logre el mismo objetivo
    - Eliminarla si el planificador decide que no es necesaria

    La decisión la toma el planificador (LLM), no el orquestador.

    Args:
        task: La tarea fallida, con su estado y resultado.
        plan: El plan completo actual (para conocer el contexto del proyecto).
        error_context: Diccionario con información del fracaso:
            - diagnosis: motivo del fallo
            - attempts_used: intentos consumidos
            - last_code: último código generado (si existe)
            - last_filename: último nombre de archivo (si existe)

    Returns:
        Diccionario con:
        - success: bool
        - replacement_tasks: lista de tareas nuevas (vacía si se eliminó)
        - action: "replaced" | "removed" | "none"
        - reasoning: explicación del planificador
        - error: string (vacío si éxito)
        - model_used: modelo usado
    """
    logger.info(
        f"Replanificando tarea {task['id']} ({task.get('name', '')}): "
        f"{error_context.get('diagnosis', 'Error desconocido')} "
        f"tras {error_context.get('attempts_used', 0)} intentos"
    )

    # Contexto del proyecto para que el planificador entienda el objetivo general
    project_goal = plan.get("spec_summary", "Objetivo no disponible")
    other_tasks = [
        {"id": t["id"], "name": t.get("name", ""), "status": t.get("status")}
        for t in plan.get("tasks", [])
        if t["id"] != task["id"]
    ]

    system_prompt = (
        "Eres un planificador experto de proyectos de software. "
        "Una tarea ha fallado tras múltiples intentos de generación "
        "y corrección. Tu trabajo es analizar por qué falló y decidir "
        "cómo proceder. Tienes libertad total para:\n"
        "  1. Dividir la tarea en subtareas más simples\n"
        "  2. Simplificarla cambiando el enfoque\n"
        "  3. Sustituirla por una tarea diferente con el mismo objetivo\n"
        "  4. Eliminarla si no es necesaria\n\n"
        "Respondes ÚNICAMENTE con JSON válido, sin texto adicional, "
        "sin bloques markdown."
    )

    # Construir resumen del error para el prompt
    diagnosis = error_context.get("diagnosis", "Error desconocido")
    last_code_preview = ""
    if error_context.get("last_code"):
        code = error_context["last_code"]
        last_code_preview = code[:500] if len(code) > 500 else code

    user_prompt = (
        f"La siguiente tarea ha fallado y necesita ser replanteada.\n\n"
        f"CONTEXTO DEL PROYECTO:\n"
        f"- Objetivo general: {project_goal}\n"
        f"- Otras tareas en el plan: {json.dumps(other_tasks, ensure_ascii=False)}\n\n"
        f"TAREA FALLIDA:\n"
        f"- ID: {task['id']}\n"
        f"- Nombre: {task.get('name', '')}\n"
        f"- Descripción: {task.get('description', '')}\n"
        f"- Inputs: {task.get('inputs', [])}\n"
        f"- Output esperado: {task.get('expected_output', '')}\n"
        f"- Criterio de aceptación: {task.get('acceptance_criterion', '')}\n"
        f"- Tipo: {task.get('task_type', 'generation')}\n"
        f"- Dependencias originales: {task.get('depends_on', [])}\n"
        f"- Lenguaje: {task.get('language', 'python')}\n\n"
        f"INFORMACIÓN DEL FRACASO:\n"
        f"- Motivo: {diagnosis}\n"
        f"- Intentos consumidos: {error_context.get('attempts_used', 0)}\n"
        f"- Último código generado (primeros 500 chars):\n"
        f"{last_code_preview if last_code_preview else '(No se generó código)'}\n\n"
        f"INSTRUCCIONES:\n"
        f"Analiza por qué falló esta tarea y decide cómo proceder. "
        f"Si decides dividirla, las subtareas deben ser secuenciales. "
        f"La primera subtarea hereda las dependencias de la tarea original. "
        f"Los IDs de nuevas tareas deben ser {task['id']}_r1, {task['id']}_r2, etc.\n\n"
        f"Responde con este JSON exacto:\n"
        f"{{\n"
        f'    "action": "replaced" o "removed",\n'
        f'    "reasoning": "explicación de por qué tomaste esta decisión",\n'
        f'    "replacement_tasks": [\n'
        f'    {{\n'
        f'        "id": "{task["id"]}_r1",\n'
        f'        "name": string,\n'
        f'        "description": string,\n'
        f'        "depends_on": array de ids,\n'
        f'        "inputs": array de strings,\n'
        f'        "expected_output": string,\n'
        f'        "acceptance_criterion": string,\n'
        f'        "task_type": "{task.get("task_type", "generation")}"\n'
        f'    }}\n'
        f'  ]\n'
        f"}}\n\n"
        f"Reglas:\n"
        f"- Si action es 'removed', replacement_tasks debe ser []\n"
        f"- Si action es 'replaced', debe haber al menos 1 tarea de reemplazo\n"
        f"- Máximo 5 tareas de reemplazo\n"
        f"- Cada tarea debe tener su propio criterio de aceptación verificable"
    )

    result = call_llm(
        task_type="planning",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=3000
    )

    if not result.get("success"):
        error_msg = result.get("error", "Error desconocido")
        logger.error(f"Error al replanificar tarea {task['id']}: {error_msg}")
        return {
            "success": False,
            "replacement_tasks": [],
            "action": "none",
            "reasoning": "",
            "error": error_msg,
            "model_used": result.get("model_used")
        }

    # Parsear la respuesta del modelo
    try:
        cleaned = _clean_llm_response(result.get("content", ""))
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido al replanificar tarea {task['id']}: {e}")
        return {
            "success": False,
            "replacement_tasks": [],
            "action": "none",
            "reasoning": "",
            "error": f"Respuesta inválida del planificador: {e}",
            "model_used": result.get("model_used")
        }

    action = parsed.get("action", "none")
    reasoning = parsed.get("reasoning", "")
    raw_tasks = parsed.get("replacement_tasks", [])

    # Validar la acción
    if action not in ("replaced", "removed"):
        logger.warning(
            f"Acción desconocida '{action}' para tarea {task['id']}, "
            f"tratando como 'none'"
        )
        return {
            "success": False,
            "replacement_tasks": [],
            "action": "none",
            "reasoning": reasoning,
            "error": f"Acción no reconocida: {action}",
            "model_used": result.get("model_used")
        }

    # Si la acción es 'removed', no hay tareas de reemplazo
    if action == "removed":
        logger.info(
            f"Tarea {task['id']} eliminada por el planificador: {reasoning}"
        )
        return {
            "success": True,
            "replacement_tasks": [],
            "action": "removed",
            "reasoning": reasoning,
            "error": "",
            "model_used": result.get("model_used")
        }

    # Construir las tareas de reemplazo con el formato completo del sistema
    if not raw_tasks:
        logger.error(
            f"Acción 'replaced' pero sin tareas para {task['id']}"
        )
        return {
            "success": False,
            "replacement_tasks": [],
            "action": "none",
            "reasoning": reasoning,
            "error": "Acción 'replaced' pero no se proporcionaron tareas",
            "model_used": result.get("model_used")
        }

    original_deps = task.get("depends_on", [])
    language = task.get("language", "python")
    replacement_tasks = []

    for i, rt_data in enumerate(raw_tasks):
        rt_id = rt_data.get("id", f"{task['id']}_r{i + 1}")
        provided_deps = rt_data.get("depends_on", [])

        # Si no tiene dependencias, la primera hereda las de la original
        # y las demás dependen de la anterior (secuenciales)
        if not provided_deps and i == 0:
            deps = list(original_deps)
        elif not provided_deps and i > 0:
            deps = [replacement_tasks[i - 1]["id"]]
        else:
            deps = provided_deps

        replacement_task = {
            "id": rt_id,
            "name": rt_data.get("name", f"Tarea reemplazo {rt_id}"),
            "description": rt_data.get("description", ""),
            "depends_on": deps,
            "inputs": rt_data.get("inputs", []),
            "expected_output": rt_data.get("expected_output", ""),
            "acceptance_criterion": rt_data.get("acceptance_criterion", ""),
            "task_type": rt_data.get("task_type", task.get("task_type", "generation")),
            "status": "pending",
            "attempts": 0,
            "result": None,
            "model_used": None,
            "language": language,
            "parent_task_id": task["id"],
            "replan_reason": "failed_after_retries"
        }
        replacement_tasks.append(replacement_task)

    logger.info(
        f"Tarea {task['id']} replanificada como '{action}': "
        f"{len(replacement_tasks)} tareas de reemplazo — {reasoning}"
    )

    return {
        "success": True,
        "replacement_tasks": replacement_tasks,
        "action": action,
        "reasoning": reasoning,
        "error": "",
        "model_used": result.get("model_used")
    }


def split_task_into_subtasks(task: dict, plan: dict, tokens_needed: int,
                              max_available_context: int) -> dict:
    """Divide una tarea demasiado grande en subtareas más pequeñas.

    Recibe una tarea que excedió el contexto de todos los modelos
    y pide a un modelo de planificación que la descomponga en
    subtareas que quepan dentro del límite disponible.

    Args:
        task: La tarea original que hay que dividir.
        plan: El plan completo actual (para conocer el proyecto).
        tokens_needed: Tokens estimados que necesita la tarea original.
        max_available_context: Contexto máximo del modelo más grande.

    Returns:
        Diccionario con:
        - success: bool
        - subtasks: lista de subtareas (vacía si falló)
        - error: string (vacío si éxito)
        - model_used: modelo usado para la división
    """
    logger.info(
        f"Dividiendo tarea {task['id']} ({task.get('name', '')}): "
        f"necesita ~{tokens_needed} tokens, máximo disponible {max_available_context}"
    )

    # Calcular cuántas subtareas se necesitan con margen de seguridad
    if max_available_context > 0:
        ratio = tokens_needed / max_available_context
        n_subtasks = max(2, int(ratio) + 1)
    else:
        n_subtasks = 3  # valor por defecto si no hay contexto disponible

    # Limitar a un máximo razonable para no crear planes infinitos
    n_subtasks = min(n_subtasks, 8)

    # Construir el prompt para que el modelo divida la tarea
    context_limit_tokens = max_available_context * 0.7 if max_available_context > 0 else 4000
    context_limit_tokens = int(context_limit_tokens)

    system_prompt = (
        "Eres un planificador experto. Tu función es dividir una tarea "
        "de software demasiado grande en subtareas más pequeñas que "
        "puedan ser ejecutadas independientemente por un modelo de IA "
        "con contexto limitado. Respondes ÚNICAMENTE con JSON válido, "
        "sin texto adicional, sin bloques markdown."
    )

    # Incluir información de dependencias originales para contexto
    original_deps = task.get("depends_on", [])
    deps_info = f"Dependencias de la tarea original: {original_deps}" if original_deps else "La tarea no tiene dependencias."

    user_prompt = (
        f"Divide la siguiente tarea de software en subtareas más pequeñas.\n\n"
        f"Tarea original:\n"
        f"- ID: {task['id']}\n"
        f"- Nombre: {task.get('name', '')}\n"
        f"- Descripción: {task.get('description', '')}\n"
        f"- Inputs: {task.get('inputs', [])}\n"
        f"- Output esperado: {task.get('expected_output', '')}\n"
        f"- Criterio de aceptación: {task.get('acceptance_criterion', '')}\n"
        f"- Tipo: {task.get('task_type', 'generation')}\n"
        f"- {deps_info}\n\n"
        f"Restricciones de contexto:\n"
        f"- Cada subtarea debe poder completarse dentro de ~{context_limit_tokens} tokens\n"
        f"- Número sugerido de subtareas: {n_subtasks}\n"
        f"- Máximo permitido: 8 subtareas\n\n"
        f"Reglas:\n"
        f"- Las subtareas deben ser secuenciales: cada una depende de la anterior\n"
        f"- La primera subtarea no tiene dependencias (o hereda las de la tarea original)\n"
        f"- La última subtarea debe producir el resultado final de la tarea original\n"
        f"- Cada subtarea debe tener su propio criterio de aceptación verificable\n"
        f"- Los IDs deben ser {task['id']}_1, {task['id']}_2, etc.\n\n"
        f"Responde con este JSON exacto:\n"
        f"{{\n"
        f'    "subtasks": [\n'
        f'    {{\n'
        f'        "id": "{task["id"]}_1",\n'
        f'        "name": string,\n'
        f'        "description": string,\n'
        f'        "depends_on": [],\n'
        f'        "inputs": array de strings,\n'
        f'        "expected_output": string,\n'
        f'        "acceptance_criterion": string,\n'
        f'        "task_type": "{task.get("task_type", "generation")}"\n'
        f'    }}\n'
        f'  ]\n'
        f"}}"
    )

    result = call_llm(
        task_type="planning",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=3000
    )

    if not result.get("success"):
        error_msg = result.get("error", "Error desconocido")
        logger.error(f"Error al dividir tarea {task['id']}: {error_msg}")
        return {
            "success": False,
            "subtasks": [],
            "error": error_msg,
            "model_used": result.get("model_used")
        }

    # Parsear la respuesta del modelo
    try:
        cleaned = _clean_llm_response(result.get("content", ""))
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido al dividir tarea {task['id']}: {e}")
        return {
            "success": False,
            "subtasks": [],
            "error": f"Respuesta inválida del planificador: {e}",
            "model_used": result.get("model_used")
        }

    if "subtasks" not in parsed or not parsed["subtasks"]:
        logger.error(f"El planificador no devolvió subtareas para {task['id']}")
        return {
            "success": False,
            "subtasks": [],
            "error": "El planificador no generó subtareas",
            "model_used": result.get("model_used")
        }

    # Construir las subtareas con el formato completo del sistema
    language = task.get("language", "python")
    subtasks = []
    subtask_ids = []

    for sub_data in parsed["subtasks"]:
        sub_id = sub_data.get("id", f"{task['id']}_{len(subtasks) + 1}")
        subtask_ids.append(sub_id)

        subtask = {
            "id": sub_id,
            "name": sub_data.get("name", f"Subtarea {sub_id}"),
            "description": sub_data.get("description", ""),
            "depends_on": sub_data.get("depends_on", []),
            "inputs": sub_data.get("inputs", []),
            "expected_output": sub_data.get("expected_output", ""),
            "acceptance_criterion": sub_data.get("acceptance_criterion", ""),
            "task_type": sub_data.get("task_type", task.get("task_type", "generation")),
            "status": "pending",
            "attempts": 0,
            "result": None,
            "model_used": None,
            "language": language,
            "parent_task_id": task["id"],  # Referencia a la tarea original
            "split_reason": "context_exceeded"
        }
        subtasks.append(subtask)

    # Garantizar que las dependencias entre subtareas sean secuenciales
    # Si la subtarea N no tiene depends_on, dependen de la subtarea N-1
    # La primera subtarea hereda las dependencias de la tarea original
    for i, subtask in enumerate(subtasks):
        provided_deps = subtask.get("depends_on", [])
        if not provided_deps and i > 0:
            subtask["depends_on"] = [subtasks[i - 1]["id"]]
        elif not provided_deps and i == 0:
            # La primera subtarea hereda las dependencias de la tarea original
            subtask["depends_on"] = list(original_deps)

    logger.info(
        f"Tarea {task['id']} dividida en {len(subtasks)} subtareas: "
        f"{subtask_ids}"
    )

    return {
        "success": True,
        "subtasks": subtasks,
        "error": "",
        "model_used": result.get("model_used")
    }


def _generate_simple_plan(spec: dict, project_id: str) -> dict:
    """Genera un plan usando LLM para specs simples (comportamiento original)."""
    system_prompt = (
        "Eres un planificador de proyectos de software.  "
        "Descompones objetivos en tareas atómicas ejecutables.  "
        "Respondes ÚNICAMENTE con JSON válido, sin texto  "
        "adicional, sin bloques markdown, sin explicaciones."
    )

    user_prompt = (
        f"Descompón este objetivo de software en tareas  "
        f"atómicas ejecutables. Cada tarea debe ser  "
        f"independiente y verificable.\n"
        f"\n"
        f"Objetivo: {spec.get('objetivo')}\n"
        f"Inputs disponibles: {spec.get('inputs_disponibles', [])}\n"
        f"Output esperado: {spec.get('output_esperado')}\n"
        f"Criterio de éxito global: {spec.get('criterio_exito')}\n"
        f"\n"
        f"Responde con este JSON exacto:\n"
        f"{{\n"
        f'    "tasks": [\n'
        f'    {{\n'
        f'        "id": "T1",\n'
        f'        "name": string,\n'
        f'        "description": string,\n'
        f'        "depends_on": array de ids o [],\n'
        f'        "inputs": array de strings,\n'
        f'        "expected_output": string,\n'
        f'        "acceptance_criterion": string,\n'
        f'        "task_type": "generation" o "correction"\n'
        f'                     o "evaluation" o "planning"\n'
        f'    }}\n'
        f'  ]\n'
        f"}}\n"
        f"Reglas:\n"
        f"- Mínimo 2 tareas, máximo 10\n"
        f"- Las dependencias deben formar un grafo acíclico\n"
        f"- acceptance_criterion debe ser verificable y preciso\n"
        f"- Nunca inventes tareas que no se deriven del objetivo"
    )

    result = call_llm(
        task_type="planning",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=2000
    )

    if not result.get("success"):
        logger.error(f"Failed to generate plan: {result.get('error')}")
        return {
            "error": "No se pudo generar el plan",
            "project_id": None
        }

    try:
        cleaned = _clean_llm_response(result.get("content", ""))
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse plan JSON: {e}")
        return {
            "error": "No se pudo generar el plan",
            "project_id": None
        }

    if "tasks" not in parsed:
        logger.error("Plan response missing 'tasks' field")
        return {
            "error": "No se pudo generar el plan",
            "project_id": None
        }

    # Instanciar detector para inferir lenguaje en tareas simples
    detector = LanguageDetector()

    tasks = []
    for task in parsed["tasks"]:
        # Inferir lenguaje para tarea simple (sin archivo asociado)
        try:
            language = detector.detect(task.get("description", ""), None).name
        except Exception:
            language = "python"  # fallback por defecto
        
        tasks.append({
            "id": task.get("id"),
            "name": task.get("name"),
            "description": task.get("description"),
            "depends_on": task.get("depends_on", []),
            "inputs": task.get("inputs", []),
            "expected_output": task.get("expected_output"),
            "acceptance_criterion": task.get("acceptance_criterion"),
            "task_type": task.get("task_type"),
            "status": "pending",
            "attempts": 0,
            "result": None,
            "model_used": None,
            "language": language  # <-- NUEVO: campo language inferido
        })

    plan_result = {
        "project_id": project_id,
        "created_at": datetime.utcnow().isoformat(),
        "spec_summary": spec.get("objetivo"),
        "tasks": tasks,
        "model_used": result.get("model_used"),
        "multi_file": False
    }

    specs_dir = Path(__file__).parents[1] / "specs"
    project_dir = specs_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    plan_path = project_dir / "plan.json"

    with open(plan_path, 'w', encoding='utf-8') as f:
        json.dump(plan_result, f, indent=2, ensure_ascii=False)

    logger.info(f"Plan saved to {plan_path}")
    return plan_result

if __name__ == "__main__":
    import logging
    import time
    from pathlib import Path
    from config.settings import settings
    logging.disable(logging.CRITICAL)

    print("\n" + "=" * 60)
    print("🔍 APA - DIAGNÓSTICO DEL PLANNER + T13/A2c MULTI-ARCHIVO")
    print("=" * 60)

    # Verificar si hay proveedores de IA configurados
    providers_ok = False
    try:
        from core.providers import provider_manager
        available = provider_manager.list_available()
        providers_ok = len(available) > 0
    except Exception:
        pass

    if not providers_ok:
        print("\n⚠️  No hay proveedores de IA configurados.")
        print("   Este diagnóstico necesita al menos un proveedor activo")
        print("   para llamar al LLM. Verifica tu archivo .env y que")
        print("   al menos un API key esté configurado.")
        print("\n" + "=" * 60)
        print("✅ DIAGNÓSTICO COMPLETADO (omitido por falta de proveedor)")
        print("=" * 60)
        logging.disable(logging.NOTSET)
        sys.exit(0)

    spec_path = Path(__file__).parents[1] / "specs" / "example.md"
    print(f"\n📄 Spec: {spec_path}")

    start_time = time.time()

    # 1. Parseo de spec
    print("\n📝 Parseo de spec")
    print("-" * 40)
    try:
        spec = parse_spec(str(spec_path))
        if "error" in spec:
            print(f"❌ Error: {spec['error']}")
        else:
            print(f"✅ Objetivo: {spec.get('objetivo')}")
            print(f"   Multi-file: {spec.get('multi_file', False)}")
            if spec.get('multi_file'):
                print(f"   Archivos detectados: {len(spec.get('files', []))}")
            else:
                print(f"   Modelo usado: {spec.get('model_used')}")
    except Exception as e:
        print(f"❌ Excepción: {e}")

    # 2. Generación de plan
    print("\n📋 Generación de plan")
    print("-" * 40)
    try:
        if "error" not in spec:
            plan = generate_plan(spec)
            if "error" in plan:
                print(f"❌ Error: {plan['error']}")
            else:
                print(f"✅ Project ID: {plan['project_id']}")
                print(f"   Tareas generadas: {len(plan['tasks'])}")
                for t in plan["tasks"]:
                    deps = t.get('depends_on', [])
                    target = t.get('target_path', t.get('file_path', ''))
                    lang = t.get('language', 'python')
                    suffix = f" [target: {target}]" if target else ""
                    print(f"   - {t['id']}: {t['name']}{suffix} (lang: {lang}, deps: {deps})")
                print(f"   Modelo usado: {plan.get('model_used', 'N/A (multi-file)')}")
                print(f"   Plan guardado en: specs/{plan['project_id']}/plan.json")
    except Exception as e:
        print(f"❌ Excepción: {e}")

    elapsed = time.time() - start_time
    print("\n⏱️ Tiempo total")
    print("-" * 40)
    print(f"{elapsed:.2f} segundos")

    logging.disable(logging.NOTSET)
    print("\n" + "=" * 60)
    print("✅ DIAGNÓSTICO COMPLETADO")
    print("=" * 60)