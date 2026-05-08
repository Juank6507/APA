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
    logging.disable(logging.CRITICAL)

    print("\n" + "=" * 60)
    print("🔍 APA - DIAGNÓSTICO DEL PLANNER + T13/A2c MULTI-ARCHIVO")
    print("=" * 60)

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