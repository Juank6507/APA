# apa/tests/test_f1f2_replan_task.py
# F1+F2: Replanificación de tareas fallidas.
# Verifica que:
#   1. replan_task() devuelve tareas de reemplazo con action "replaced"
#   2. replan_task() maneja action "removed" correctamente
#   3. replan_task() devuelve error cuando el LLM falla
#   4. replan_task() rechaza acciones desconocidas
#   5. _handle_task_replan() inserta tareas y redirige dependencias (replaced)
#   6. _handle_task_replan() marca como replanned y redirige deps (removed)
#   7. Tareas con attempts < 3 NO se replanifican
#   8. "replanned" cuenta como completado en el resultado final
#   9. Tareas replanned desbloquean sus dependientes

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import tempfile
from unittest.mock import patch, MagicMock

PASS = 0
FAIL = 0


def report(test_name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {test_name}")
    else:
        FAIL += 1
        print(f"  ✗ {test_name} — {detail}")


def _make_task(task_id="T1", name="tarea test", attempts=0, deps=None):
    """Crea una tarea de prueba con los campos necesarios."""
    return {
        "id": task_id,
        "name": name,
        "description": "Descripción de prueba",
        "inputs": [],
        "expected_output": "output",
        "acceptance_criterion": "criterio",
        "task_type": "generation",
        "depends_on": deps or [],
        "status": "pending",
        "attempts": attempts,
        "result": None,
        "model_used": None,
        "language": "python"
    }


def _make_plan(project_id="test-proj", tasks=None, summary="Objetivo test"):
    """Crea un plan de prueba."""
    return {
        "project_id": project_id,
        "spec_summary": summary,
        "tasks": tasks or []
    }


def _mock_llm_response(content_json: dict):
    """Crea un mock de call_llm que devuelve el JSON dado."""
    def mock_call_llm(*args, **kwargs):
        return {
            "success": True,
            "content": json.dumps(content_json),
            "model_used": "mock-planner"
        }
    return mock_call_llm


def test_replan_task_replaced():
    """replan_task() con acción 'replaced' devuelve tareas nuevas."""
    from core.planner import replan_task

    task = _make_task("T3", "tarea compleja")
    plan = _make_plan(tasks=[task])

    error_context = {
        "diagnosis": "No se pudo generar código válido tras 3 intentos",
        "attempts_used": 3,
        "last_code": "def broken():\n    pass",
        "last_filename": "broken.py"
    }

    mock_response = {
        "action": "replaced",
        "reasoning": "La tarea era demasiado compleja, se divide en 2 partes",
        "replacement_tasks": [
            {
                "id": "T3_r1",
                "name": "Parte 1: estructura base",
                "description": "Crear la estructura base",
                "depends_on": [],
                "inputs": [],
                "expected_output": "Estructura base",
                "acceptance_criterion": "Compila sin errores",
                "task_type": "generation"
            },
            {
                "id": "T3_r2",
                "name": "Parte 2: lógica",
                "description": "Implementar la lógica",
                "depends_on": ["T3_r1"],
                "inputs": [],
                "expected_output": "Lógica completa",
                "acceptance_criterion": "Pasa las pruebas",
                "task_type": "generation"
            }
        ]
    }

    with patch("core.planner.call_llm", _mock_llm_response(mock_response)):
        result = replan_task(task, plan, error_context)

    report("Replan exitoso", result.get("success") is True, str(result))
    report("Acción es 'replaced'",
           result.get("action") == "replaced",
           f"obtenido: {result.get('action')}")
    report("2 tareas de reemplazo",
           len(result.get("replacement_tasks", [])) == 2,
           f"obtenido: {len(result.get('replacement_tasks', []))}")
    report("Primer reemplazo tiene ID correcto",
           result["replacement_tasks"][0]["id"] == "T3_r1",
           f"obtenido: {result['replacement_tasks'][0]['id']}")
    report("Segundo depende del primero",
           "T3_r1" in result["replacement_tasks"][1].get("depends_on", []),
           f"deps: {result['replacement_tasks'][1].get('depends_on')}")
    report("Tiene reasoning",
           len(result.get("reasoning", "")) > 0)
    report("parent_task_id preservado",
           result["replacement_tasks"][0].get("parent_task_id") == "T3")
    report("replan_reason preservado",
           result["replacement_tasks"][0].get("replan_reason") == "failed_after_retries")


def test_replan_task_removed():
    """replan_task() con acción 'removed' devuelve tareas vacías."""
    from core.planner import replan_task

    task = _make_task("T4", "tarea innecesaria")
    plan = _make_plan(tasks=[task])

    error_context = {
        "diagnosis": "Dependencias no disponibles",
        "attempts_used": 3,
        "last_code": "",
        "last_filename": ""
    }

    mock_response = {
        "action": "removed",
        "reasoning": "Esta tarea no es necesaria, su objetivo ya se cubre con T2",
        "replacement_tasks": []
    }

    with patch("core.planner.call_llm", _mock_llm_response(mock_response)):
        result = replan_task(task, plan, error_context)

    report("Replan exitoso", result.get("success") is True)
    report("Acción es 'removed'",
           result.get("action") == "removed",
           f"obtenido: {result.get('action')}")
    report("Sin tareas de reemplazo",
           len(result.get("replacement_tasks", [])) == 0)
    report("Tiene reasoning explicativo",
           "no es necesaria" in result.get("reasoning", ""))


def test_replan_task_llm_fails():
    """replan_task() devuelve error cuando el LLM falla."""
    from core.planner import replan_task

    task = _make_task("T5", "tarea problemática")
    plan = _make_plan(tasks=[task])

    error_context = {
        "diagnosis": "Error del modelo",
        "attempts_used": 3,
        "last_code": "",
        "last_filename": ""
    }

    def mock_call_llm_fail(*args, **kwargs):
        return {"success": False, "error": "Modelo no disponible", "model_used": None}

    with patch("core.planner.call_llm", mock_call_llm_fail):
        result = replan_task(task, plan, error_context)

    report("Replan fallido", result.get("success") is False)
    report("Acción es 'none'",
           result.get("action") == "none",
           f"obtenido: {result.get('action')}")
    report("Sin tareas de reemplazo",
           len(result.get("replacement_tasks", [])) == 0)
    report("Tiene mensaje de error",
           len(result.get("error", "")) > 0)


def test_replan_task_unknown_action():
    """replan_task() rechaza acciones no reconocidas."""
    from core.planner import replan_task

    task = _make_task("T6", "tarea rara")
    plan = _make_plan(tasks=[task])

    error_context = {
        "diagnosis": "Error extraño",
        "attempts_used": 3,
        "last_code": "",
        "last_filename": ""
    }

    mock_response = {
        "action": "rethink",  # Acción inválida
        "reasoning": "No sé qué hacer",
        "replacement_tasks": []
    }

    with patch("core.planner.call_llm", _mock_llm_response(mock_response)):
        result = replan_task(task, plan, error_context)

    report("Replan fallido con acción desconocida",
           result.get("success") is False)
    report("Error menciona acción no reconocida",
           "no reconocida" in result.get("error", ""),
           f"error: {result.get('error')}")


def test_handle_replan_replaced():
    """_handle_task_replan() inserta tareas y redirige dependencias."""
    from core.orchestrator import Orchestrator

    task = _make_task("T2", "tarea que falla", deps=["T1"])
    task["status"] = "failed"
    task["result"] = {
        "success": False,
        "attempts_used": 3,
        "diagnosis": "Corrección fallida 3 veces",
        "code": "bad code",
        "filename": "bad.py"
    }

    t1 = _make_task("T1", "tarea previa")
    t1["status"] = "completed"
    t1["result"] = {"code": "ok", "filename": "t1.py"}

    t3 = _make_task("T3", "tarea dependiente", deps=["T2"])

    plan = _make_plan(tasks=[t1, task, t3])
    completed_tasks = {"T1": t1["result"]}

    mock_response = {
        "action": "replaced",
        "reasoning": "Dividida en 2 subtareas",
        "replacement_tasks": [
            {
                "id": "T2_r1",
                "name": "Parte 1",
                "description": "Primera parte",
                "depends_on": [],
                "inputs": [],
                "expected_output": "Parte 1",
                "acceptance_criterion": "ok",
                "task_type": "generation"
            },
            {
                "id": "T2_r2",
                "name": "Parte 2",
                "description": "Segunda parte",
                "depends_on": ["T2_r1"],
                "inputs": [],
                "expected_output": "Parte 2",
                "acceptance_criterion": "ok",
                "task_type": "generation"
            }
        ]
    }

    orch = Orchestrator()
    events = []

    with patch("core.planner.call_llm", _mock_llm_response(mock_response)):
        ok = orch._handle_task_replan(
            task, task["result"], plan, completed_tasks,
            on_progress=lambda e: events.append(e)
        )

    report("Replan exitoso en orchestrator", ok is True)
    report("Tarea original marcada como 'replanned'",
           task["status"] == "replanned",
           f"obtenido: {task['status']}")
    report("T2_r1 insertada en el plan",
           any(t["id"] == "T2_r1" for t in plan["tasks"]))
    report("T2_r2 insertada en el plan",
           any(t["id"] == "T2_r2" for t in plan["tasks"]))
    report("T3 ahora depende de T2_r2 (última reemplazo)",
           t3.get("depends_on") == ["T2_r2"],
           f"deps: {t3.get('depends_on')}")
    report("T2 en completed_tasks (desbloqueada)",
           "T2" in completed_tasks)
    report("Evento task_replanned emitido",
           any(e.get("type") == "task_replanned" for e in events))
    report("Evento tiene replacement_task_ids",
           any(e.get("type") == "task_replanned" and
               len(e.get("replacement_task_ids", [])) == 2
               for e in events))


def test_handle_replan_removed():
    """_handle_task_replan() con removed redirige dependencias a las de la original."""
    from core.orchestrator import Orchestrator

    task = _make_task("T2", "tarea a eliminar", deps=["T1"])
    task["status"] = "failed"
    task["result"] = {
        "success": False,
        "attempts_used": 3,
        "diagnosis": "No tiene sentido",
        "code": "",
        "filename": ""
    }

    t3 = _make_task("T3", "tarea dependiente", deps=["T2"])

    plan = _make_plan(tasks=[task, t3])
    completed_tasks = {}

    mock_response = {
        "action": "removed",
        "reasoning": "Tarea redundante, T3 puede depender de T1 directamente",
        "replacement_tasks": []
    }

    orch = Orchestrator()
    events = []

    with patch("core.planner.call_llm", _mock_llm_response(mock_response)):
        ok = orch._handle_task_replan(
            task, task["result"], plan, completed_tasks,
            on_progress=lambda e: events.append(e)
        )

    report("Replan removed exitoso", ok is True)
    report("Tarea marcada como 'replanned'",
           task["status"] == "replanned")
    report("T3 hereda dependencias de T2 (o sea T1)",
           "T1" in t3.get("depends_on", []),
           f"deps: {t3.get('depends_on')}")
    report("T2 no está en dependencias de T3",
           "T2" not in t3.get("depends_on", []),
           f"deps: {t3.get('depends_on')}")
    report("Evento action es 'removed'",
           any(e.get("type") == "task_replanned" and
               e.get("action") == "removed"
               for e in events))


def test_no_replan_under_3_attempts():
    """Una tarea con attempts < 3 NO se replanifica (queda como failed)."""
    from core.orchestrator import Orchestrator

    # T1 completada, T2 falla con solo 1 intento
    t1 = _make_task("T1", "previa")
    t1["status"] = "completed"
    t1["result"] = {"code": "ok", "filename": "t1.py"}

    t2 = _make_task("T2", "falla temprano", deps=["T1"])
    t2["status"] = "pending"

    plan = _make_plan(tasks=[t1, t2])

    orch = Orchestrator()
    orch.current_plan = plan
    orch.project_id = "test-no-replan"

    events = []

    # Mock: T2 falla con 1 solo intento (no debe replanificarse)
    def mock_run_task(task):
        return {
            "success": False,
            "code": "",
            "filename": "",
            "criterion_passed": False,
            "attempts_used": 1,  # Solo 1 intento, < 3
            "model_used": None,
            "diagnosis": "Fallo en primer intento"
        }

    # Patchear _run_task y también replan_task para verificar que NO se llama
    replan_called = []

    def mock_replan(*args, **kwargs):
        replan_called.append(True)
        return {"success": True, "action": "removed", "replacement_tasks": [],
                "reasoning": "no debería llegar aquí"}

    with patch.object(orch, "_run_task", mock_run_task):
        with patch("core.planner.replan_task", mock_replan):
            result = orch._execute_tasks(plan, on_progress=lambda e: events.append(e))

    report("replan_task NO fue llamada",
           len(replan_called) == 0,
           f"veces llamada: {len(replan_called)}")
    report("T2 marcada como failed",
           t2["status"] == "failed",
           f"obtenido: {t2['status']}")
    report("Pipeline reporta fallo",
           result.get("success") is False)


def test_replanned_counts_as_completed():
    """Las tareas 'replanned' cuentan como completadas en el resultado final."""
    from core.orchestrator import Orchestrator

    t1 = _make_task("T1", "tarea completada")
    t1["status"] = "completed"
    t1["result"] = {"code": "ok"}

    t2 = _make_task("T2", "tarea replanned")
    t2["status"] = "replanned"
    t2["result"] = {"success": False, "diagnosis": "eliminada"}

    plan = _make_plan(tasks=[t1, t2])

    orch = Orchestrator()
    orch.current_plan = plan
    orch.project_id = "test-replanned-count"

    result = orch._execute_tasks(plan)

    report("Pipeline exitoso con replanned",
           result.get("success") is True,
           f"obtenido: {result.get('success')}")


def test_replanned_unblocks_dependents():
    """Una tarea replanned desbloquea las tareas que dependían de ella."""
    from core.orchestrator import Orchestrator

    t1 = _make_task("T1", "completada")
    t1["status"] = "completed"
    t1["result"] = {"code": "ok", "filename": "t1.py"}

    t2 = _make_task("T2", "fallida y replanned", deps=["T1"])
    t2["status"] = "replanned"
    t2["result"] = {"success": False, "diagnosis": "eliminada"}

    t3 = _make_task("T3", "depende de T2", deps=["T2"])
    t3["status"] = "pending"

    plan = _make_plan(tasks=[t1, t2, t3])

    orch = Orchestrator()
    orch.current_plan = plan
    orch.project_id = "test-unblock"

    def mock_run_task(task):
        if task["id"] == "T3":
            return {
                "success": True,
                "code": "print('t3')",
                "filename": "t3.py",
                "criterion_passed": True,
                "attempts_used": 1,
                "model_used": "mock"
            }
        return {"success": False, "attempts_used": 0, "diagnosis": "no esperada"}

    orch.generator.save_to_sandbox = MagicMock(return_value={"success": True})

    with patch.object(orch, "_run_task", mock_run_task):
        result = orch._execute_tasks(plan)

    report("T3 se ejecutó (desbloqueada por replanned)",
           t3["status"] == "completed",
           f"obtenido: {t3['status']}")
    report("Pipeline exitoso",
           result.get("success") is True)


# === EJECUCIÓN ===
if __name__ == "__main__":
    print("=" * 60)
    print("TEST F1+F2: Replanificación de Tareas Fallidas")
    print("=" * 60)

    tests = [
        ("replan_replaced", test_replan_task_replaced),
        ("replan_removed", test_replan_task_removed),
        ("replan_llm_fails", test_replan_task_llm_fails),
        ("replan_unknown_action", test_replan_task_unknown_action),
        ("handle_replan_replaced", test_handle_replan_replaced),
        ("handle_replan_removed", test_handle_replan_removed),
        ("no_replan_under_3", test_no_replan_under_3_attempts),
        ("replanned_counts_completed", test_replanned_counts_as_completed),
        ("replanned_unblocks_deps", test_replanned_unblocks_dependents),
    ]

    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
        except Exception as e:
            FAIL += 1
            print(f"  ✗ {name} — EXCEPCIÓN: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {PASS} pasaron, {FAIL} fallaron de {PASS + FAIL}")
    print("=" * 60)
