# apa/core/orchestrator.py
import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
from core.planner import parse_spec, generate_plan, split_task_into_subtasks
from core.providers import provider_manager
from agents.generator import GeneratorAgent
from agents.corrector import CorrectorAgent
from agents.documenter import DocumenterAgent
from core.checkpoint import CheckpointManager
from core.parallel_executor import ParallelExecutor
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.WARNING))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

class Orchestrator:
    def __init__(self):
        self.generator = GeneratorAgent()
        self.corrector = CorrectorAgent()
        self.documenter = DocumenterAgent()
        self.current_plan = None
        self.project_id = None
        self.checkpoint_mgr: CheckpointManager | None = None

    def _emit(self, on_progress, event: dict):
        event["timestamp"] = datetime.utcnow().isoformat()
        if on_progress:
            try:
                on_progress(event)
            except Exception as e:
                logger.warning(f"on_progress callback error: {e}")

    def _persist_plan(self, plan: dict) -> None:
        try:
            if not self.project_id:
                return
            specs_dir = Path(__file__).parents[1] / "specs"
            project_dir = specs_dir / self.project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            plan_path = project_dir / "plan.json"
            with open(plan_path, 'w', encoding='utf-8') as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist plan: {e}")

    def _generate_documentation(self, plan: dict, on_progress=None) -> dict:
        try:
            self._emit(on_progress, {
                "type": "documentation_started",
                "message": "Generando documentación del proyecto..."
            })

            files = []
            for task in plan.get("tasks", []):
                if task.get("status") == "completed" and task.get("result"):
                    result = task["result"]
                    if result.get("code") and result.get("filename"):
                        files.append({
                            "filename": result["filename"],
                            "code": result["code"],
                            "task_name": task["name"],
                            "acceptance_criterion": task.get("acceptance_criterion", "")
                        })

            if not files:
                return {"success": True, "skipped": True}

            doc_result = self.documenter.document_generated_files(
                project_id=self.project_id,
                files=files
            )

            self._emit(on_progress, {
                "type": "documentation_completed",
                "success": doc_result["success"],
                "doc_path": doc_result.get("doc_path", ""),
                "files_documented": doc_result.get("files_documented", 0),
                "message": f"Documentación generada: {doc_result.get('files_documented', 0)} archivos documentados"
            })

            return doc_result

        except Exception as e:
            logger.error(f"Documentation failed: {e}")
            self._emit(on_progress, {
                "type": "documentation_failed",
                "error": str(e)
            })
            return {"success": False, "error": str(e)}

    def _run_task(self, task: dict) -> dict:
        try:
            # A8: Preparar contexto de dependencias ANTES de generar y corregir
            dependency_codes = {}
            for dep_id in task.get("depends_on", []):
                dep_task = next((t for t in self.current_plan["tasks"] 
                               if t["id"] == dep_id and t["status"] == "completed"), None)
                if dep_task and dep_task.get("result", {}).get("code"):
                    dep_path = dep_task.get("target_path", dep_task.get("file_path", dep_id))
                    dependency_codes[dep_path] = dep_task["result"]["code"]
            
            if dependency_codes:
                task["dependency_codes"] = dependency_codes
                logger.info(f"Injected {len(dependency_codes)} dependency codes for task {task.get('id')}: {list(dependency_codes.keys())}")
            
            # PROPAGACIÓN DE project_id A GENERATOR Y CORRECTOR
            task["project_id"] = self.project_id
            
            gen_result = self.generator.generate_and_test(task)
            
            # FASE 2: Detectar señal split_task y propagarla
            if not gen_result.get("success") and gen_result.get("action_required") == "split_task":
                logger.info(f"Tarea {task['id']} requiere división por contexto excedido")
                return {
                    "success": False,
                    "code": "",
                    "filename": "",
                    "criterion_passed": False,
                    "attempts_used": 0,  # No consume intento real
                    "model_used": gen_result.get("model_used"),
                    "diagnosis": gen_result.get("split_message", "Contexto excedido, requiere división"),
                    "action_required": "split_task",
                    "error_type": gen_result.get("error_type", "context_exceeded_no_fallback"),
                    "tokens_needed": gen_result.get("tokens_needed", 0),
                    "max_available_context": gen_result.get("max_available_context", 0)
                }
            
            if not gen_result.get("success"):
                return {
                    "success": False,
                    "code": "",
                    "filename": "",
                    "criterion_passed": False,
                    "attempts_used": 1,
                    "model_used": None,
                    "diagnosis": "El generador no pudo producir código"
                }
            
            execution = gen_result.get("execution", {})
            criterion_passed = execution.get("criterion_passed", False)
            
            if criterion_passed:
                save_result = self.generator.save_to_sandbox(gen_result["code"], gen_result["filename"])
                return {
                    "success": True,
                    "code": gen_result["code"],
                    "filename": gen_result["filename"],
                    "criterion_passed": True,
                    "attempts_used": 1,
                    "model_used": gen_result.get("model_used"),
                    "diagnosis": "Generado y verificado en primer intento"
                }
            
            # dependency_codes ya está en task, el corrector lo usará
            correction_result = self.corrector.correction_loop(
                task=task,
                initial_code=gen_result["code"],
                initial_execution=gen_result["execution"],
                max_attempts=3
            )
            
            if correction_result.get("success"):
                save_result = self.generator.save_to_sandbox(
                    correction_result["code"], correction_result["filename"])
                attempts = correction_result.get("attempts_used", 0) + 1
                return {
                    "success": True,
                    "code": correction_result["code"],
                    "filename": correction_result["filename"],
                    "criterion_passed": True,
                    "attempts_used": attempts,
                    "model_used": correction_result.get("model_used"),
                    "diagnosis": f"Corregido en {attempts} intentos"
                }
            
            return {
                "success": False,
                "code": correction_result.get("code", ""),
                "filename": correction_result.get("filename", ""),
                "criterion_passed": False,
                "attempts_used": correction_result.get("attempts_used", 0) + 1,
                "model_used": correction_result.get("model_used"),
                "diagnosis": correction_result.get("diagnosis", "Corrección fallida")
            }
            
        except Exception as e:
            logger.error(f"Error in _run_task: {e}")
            return {
                "success": False,
                "code": "",
                "filename": "",
                "criterion_passed": False,
                "attempts_used": 1,
                "model_used": None,
                "diagnosis": f"Excepción en ejecución: {str(e)}"
            }

    def _handle_task_split(self, task: dict, result: dict, plan: dict,
                           completed_tasks: dict, on_progress=None) -> bool:
        """Gestiona la división de una tarea por contexto excedido.

        Llama al planificador para dividir la tarea en subtareas,
        las inserta en el plan actual y actualiza las dependencias
        de las demás tareas que dependían de la original.

        Returns:
            True si la división fue exitosa, False si falló.
        """
        original_task_id = task["id"]
        tokens_needed = result.get("tokens_needed", 0)
        max_context = result.get("max_available_context", 0)

        logger.info(
            f"Iniciando división de tarea {original_task_id}: "
            f"tokens_needed={tokens_needed}, max_context={max_context}"
        )

        # Llamar al planificador para dividir la tarea
        split_result = split_task_into_subtasks(
            task=task,
            plan=plan,
            tokens_needed=tokens_needed,
            max_available_context=max_context
        )

        if not split_result.get("success"):
            logger.error(
                f"No se pudo dividir la tarea {original_task_id}: "
                f"{split_result.get('error', 'Error desconocido')}"
            )
            return False

        subtasks = split_result["subtasks"]
        if not subtasks:
            logger.error(f"División de tarea {original_task_id} no produjo subtareas")
            return False

        # Marcar la tarea original como dividida (no como fallida ni completada)
        task["status"] = "split"
        task["result"] = {
            "success": False,
            "action_required": "split_task",
            "diagnosis": result.get("diagnosis", "Tarea dividida por contexto excedido"),
            "split_into": [st["id"] for st in subtasks],
            "model_used": split_result.get("model_used")
        }

        # Reemplazar referencias a la tarea original en las dependencias
        # Si otra tarea dependía de la original, ahora depende de la última subtarea
        last_subtask_id = subtasks[-1]["id"]
        for t in plan.get("tasks", []):
            if t["id"] == original_task_id:
                continue
            deps = t.get("depends_on", [])
            if original_task_id in deps:
                t["depends_on"] = [last_subtask_id if d == original_task_id else d for d in deps]
                logger.info(
                    f"Tarea {t['id']} actualizada: depende de {last_subtask_id} "
                    f"(era {original_task_id})"
                )

        # Insertar las subtareas en el plan
        plan["tasks"].extend(subtasks)

        # Notificar via evento de progreso (Cambio 4)
        self._emit(on_progress, {
            "type": "task_split",
            "original_task_id": original_task_id,
            "original_task_name": task.get("name", ""),
            "subtask_ids": [st["id"] for st in subtasks],
            "subtask_count": len(subtasks),
            "tokens_needed": tokens_needed,
            "max_available_context": max_context,
            "model_used": split_result.get("model_used"),
            "message": (
                f"Tarea '{task.get('name', original_task_id)}' dividida en "
                f"{len(subtasks)} subtareas por contexto excedido "
                f"(necesitaba ~{tokens_needed} tokens, máximo {max_context})"
            )
        })

        logger.info(
            f"Tarea {original_task_id} dividida exitosamente en "
            f"{len(subtasks)} subtareas: {[st['id'] for st in subtasks]}"
        )
        return True

    def _execute_tasks(self, plan: dict, on_progress=None) -> dict:
        try:
            completed_tasks = {}
            failed_tasks = {}
            tasks = plan.get("tasks", [])
            max_iterations = len(tasks) * 3
            
            for iteration in range(max_iterations):
                pending = [t for t in tasks if t["status"] in ("pending", "running")]
                
                if not pending:
                    break
                
                executable = []
                split_task_ids = {t["id"] for t in tasks if t["status"] == "split"}
                for task in pending:
                    if task["status"] != "pending":
                        continue
                    deps = task.get("depends_on", [])
                    if all(dep_id in completed_tasks or dep_id in split_task_ids for dep_id in deps):
                        executable.append(task)
                
                if not executable:
                    if pending:
                        for task in pending:
                            task["status"] = "failed"
                            failed_tasks[task["id"]] = {
                                "diagnosis": "Bloqueo de dependencias",
                                "attempts_used": 0
                            }
                        self._persist_plan(plan)
                    break
                
                if len(executable) == 1:
                    task = executable[0]
                    task["status"] = "running"
                    self._persist_plan(plan)
                    if hasattr(self, 'checkpoint_mgr') and self.checkpoint_mgr:
                        self.checkpoint_mgr.save(self.current_plan)
                        n_completed = sum(1 for t in self.current_plan["tasks"] if t["status"] == "completed")
                        n_total = len(self.current_plan["tasks"])
                        self._emit(on_progress, {
                            "type": "checkpoint_saved",
                            "project_id": self.project_id,
                            "tasks_completed": n_completed,
                            "tasks_total": n_total
                        })
                    
                    self._emit(on_progress, {
                        "type": "task_started",
                        "task_id": task["id"],
                        "task_name": task["name"],
                        "task_type": task["task_type"]
                    })
                    
                    result = self._run_task(task)
                    
                    # FASE 2: Si la tarea requiere división, dividirla y continuar
                    if result.get("action_required") == "split_task":
                        split_ok = self._handle_task_split(
                            task, result, plan, completed_tasks, on_progress
                        )
                        if not split_ok:
                            # Si la división falló, marcar como fallida
                            task["status"] = "failed"
                            task["result"] = result
                            failed_tasks[task["id"]] = {
                                "diagnosis": result.get("diagnosis", "No se pudo dividir la tarea"),
                                "attempts_used": 0
                            }
                            self._emit(on_progress, {
                                "type": "task_failed",
                                "task_id": task["id"],
                                "task_name": task["name"],
                                "diagnosis": result.get("diagnosis", "No se pudo dividir la tarea"),
                                "attempts_used": 0
                            })
                        self._persist_plan(plan)
                        if hasattr(self, 'checkpoint_mgr') and self.checkpoint_mgr:
                            self.checkpoint_mgr.save(self.current_plan)
                        continue
                    
                    if result.get("success"):
                        task["status"] = "completed"
                        task["result"] = result
                        task["model_used"] = result.get("model_used")
                        completed_tasks[task["id"]] = result
                        self._emit(on_progress, {
                            "type": "task_completed",
                            "task_id": task["id"],
                            "task_name": task["name"],
                            "criterion_passed": result.get("criterion_passed", False),
                            "attempts_used": result.get("attempts_used", 0),
                            "model_used": result.get("model_used"),
                            "filename": result.get("filename")
                        })
                    else:
                        task["status"] = "failed"
                        task["result"] = result
                        failed_tasks[task["id"]] = {
                            "diagnosis": result.get("diagnosis", "Fallo desconocido"),
                            "attempts_used": result.get("attempts_used", 0)
                        }
                        self._emit(on_progress, {
                            "type": "task_failed",
                            "task_id": task["id"],
                            "task_name": task["name"],
                            "diagnosis": result.get("diagnosis", "Fallo desconocido"),
                            "attempts_used": result.get("attempts_used", 0)
                        })
                    
                    self._persist_plan(plan)
                    if hasattr(self, 'checkpoint_mgr') and self.checkpoint_mgr:
                        self.checkpoint_mgr.save(self.current_plan)
                        n_completed = sum(1 for t in self.current_plan["tasks"] if t["status"] == "completed")
                        n_total = len(self.current_plan["tasks"])
                        self._emit(on_progress, {
                            "type": "checkpoint_saved",
                            "project_id": self.project_id,
                            "tasks_completed": n_completed,
                            "tasks_total": n_total
                        })
                else:
                    for task in executable:
                        task["status"] = "running"
                    self._persist_plan(plan)
                    if hasattr(self, 'checkpoint_mgr') and self.checkpoint_mgr:
                        self.checkpoint_mgr.save(self.current_plan)
                        n_completed = sum(1 for t in self.current_plan["tasks"] if t["status"] == "completed")
                        n_total = len(self.current_plan["tasks"])
                        self._emit(on_progress, {
                            "type": "checkpoint_saved",
                            "project_id": self.project_id,
                            "tasks_completed": n_completed,
                            "tasks_total": n_total
                        })
                    
                    for task in executable:
                        self._emit(on_progress, {
                            "type": "task_started",
                            "task_id": task["id"],
                            "task_name": task["name"],
                            "task_type": task["task_type"]
                        })
                    
                    executor = ParallelExecutor(max_workers=min(3, len(executable)))
                    parallel_results = executor.run(executable, self._run_task)
                    
                    for task in executable:
                        result = parallel_results["results"].get(task["id"])
                        if result is None:
                            error_msg = parallel_results["errors"].get(task["id"], "Error desconocido en ejecución paralela")
                            task["status"] = "failed"
                            task["result"] = {"diagnosis": error_msg}
                            failed_tasks[task["id"]] = {"diagnosis": error_msg, "attempts_used": 0}
                            self._emit(on_progress, {
                                "type": "task_failed",
                                "task_id": task["id"],
                                "task_name": task["name"],
                                "diagnosis": error_msg,
                                "attempts_used": 0
                            })
                            continue
                        
                        if result.get("success"):
                            task["status"] = "completed"
                            task["result"] = result
                            task["model_used"] = result.get("model_used")
                            completed_tasks[task["id"]] = result
                            self._emit(on_progress, {
                                "type": "task_completed",
                                "task_id": task["id"],
                                "task_name": task["name"],
                                "criterion_passed": result.get("criterion_passed", False),
                                "attempts_used": result.get("attempts_used", 0),
                                "model_used": result.get("model_used"),
                                "filename": result.get("filename")
                            })
                        else:
                            task["status"] = "failed"
                            task["result"] = result
                            failed_tasks[task["id"]] = {
                                "diagnosis": result.get("diagnosis", "Fallo desconocido"),
                                "attempts_used": result.get("attempts_used", 0)
                            }
                            self._emit(on_progress, {
                                "type": "task_failed",
                                "task_id": task["id"],
                                "task_name": task["name"],
                                "diagnosis": result.get("diagnosis", "Fallo desconocido"),
                                "attempts_used": result.get("attempts_used", 0)
                            })
                    
                    self._persist_plan(plan)
                    if hasattr(self, 'checkpoint_mgr') and self.checkpoint_mgr:
                        self.checkpoint_mgr.save(self.current_plan)
                        n_completed = sum(1 for t in self.current_plan["tasks"] if t["status"] == "completed")
                        n_total = len(self.current_plan["tasks"])
                        self._emit(on_progress, {
                            "type": "checkpoint_saved",
                            "project_id": self.project_id,
                            "tasks_completed": n_completed,
                            "tasks_total": n_total
                        })
            
            tasks_summary = []
            for task in tasks:
                result = task.get("result") or {}
                tasks_summary.append({
                    "id": task["id"],
                    "name": task["name"],
                    "status": task["status"],
                    "criterion_passed": result.get("criterion_passed", False),
                    "attempts_used": result.get("attempts_used", 0),
                    "filename": result.get("filename") if result.get("success") else None,
                    "model_used": task.get("model_used") or result.get("model_used"),
                    "diagnosis": result.get("diagnosis") if not result.get("success") else None
                })
            
            all_completed = all(t["status"] in ("completed", "split") for t in tasks)
            
            return {
                "project_id": plan.get("project_id"),
                "success": all_completed,
                "completed": len(completed_tasks),
                "failed": len(failed_tasks),
                "tasks_summary": tasks_summary,
                "plan_path": str(Path(__file__).parents[1] / "specs" / plan.get("project_id") / "plan.json")
            }
            
        except Exception as e:
            logger.error(f"Error in _execute_tasks: {e}")
            return {
                "project_id": plan.get("project_id"),
                "success": False,
                "completed": 0,
                "failed": len(plan.get("tasks", [])),
                "tasks_summary": [],
                "plan_path": "",
                "error": str(e)
            }

    def run(self, spec_path: str, on_progress=None) -> dict:
        try:
            # A5: Reducir verbosidad de logs de módulos secundarios
            logging.getLogger('agents.generator').setLevel(logging.WARNING)
            logging.getLogger('mcp.server').setLevel(logging.WARNING)
            logging.getLogger('core.validator').setLevel(logging.WARNING)
            logging.getLogger('core.llm_cache').setLevel(logging.WARNING)
            
            health = provider_manager.health_check()
            self._emit(on_progress, {
                "type": "health_check",
                "providers": [
                    name for name, info in health.get("providers", {}).items()
                    if info.get("available")
                ],
                "total_models": health.get("total_models", 0)
            })
            
            self._emit(on_progress, {"type": "parsing_spec", "path": spec_path})
            spec = parse_spec(spec_path)
            
            if spec.get("error"):
                return {
                    "success": False,
                    "error": f"Error parseando spec: {spec.get('error')}",
                    "project_id": None
                }
            
            self._emit(on_progress, {
                "type": "spec_parsed",
                "objetivo": spec.get("objetivo"),
                "model_used": spec.get("model_used")
            })
            
            self._emit(on_progress, {"type": "generating_plan"})
            plan = generate_plan(spec)
            
            if plan.get("error"):
                return {
                    "success": False,
                    "error": f"Error generando plan: {plan.get('error')}",
                    "project_id": None
                }
            
            self.current_plan = plan
            self.project_id = plan["project_id"]
            self.checkpoint_mgr = CheckpointManager(self.project_id)

            if self.checkpoint_mgr.exists():
                restored_plan = self.checkpoint_mgr.restore()
                if restored_plan:
                    self.current_plan = restored_plan
                    self._emit(on_progress, {
                        "type": "checkpoint_restored",
                        "project_id": self.project_id,
                        "tasks_completed": sum(1 for t in restored_plan["tasks"] if t["status"] == "completed")
                    })
                    result = self._execute_tasks(self.current_plan, on_progress)
                    self.checkpoint_mgr.clear()
                    doc_result = self._generate_documentation(self.current_plan, on_progress)
                    result["documentation"] = doc_result
                    return result

            task_summaries = [
                {"id": t["id"], "name": t["name"], "status": t["status"]}
                for t in plan.get("tasks", [])
            ]
            
            self._emit(on_progress, {
                "type": "plan_generated",
                "project_id": plan["project_id"],
                "tasks_count": len(plan.get("tasks", [])),
                "tasks": task_summaries
            })
            
            result = self._execute_tasks(plan, on_progress)

            if hasattr(self, 'checkpoint_mgr'):
                self.checkpoint_mgr.clear()
      
            doc_result = self._generate_documentation(self.current_plan, on_progress)
            result["documentation"] = doc_result
            
            return result
            
        except Exception as e:
            logger.error(f"Error in run: {e}")
            return {
                "success": False,
                "error": f"Excepción en orquestación: {str(e)}",
                "project_id": self.project_id
            }

    def get_status(self) -> dict:
        if not self.project_id or not self.current_plan:
            return {"status": "idle", "project_id": None}
        return {
            "status": "running",
            "project_id": self.project_id,
            "plan": self.current_plan
        }

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)
    for logger_name in ["__main__", "core.orchestrator", "core.planner", "core.checkpoint", "agents.generator", "core.router", "mcp.server", "agents.documenter"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    print("=== PRUEBA 1: run completo con spec de ejemplo ===")
    from pathlib import Path
    spec_path = str(Path(__file__).parents[1] / "specs" / "example.md")
    events = []
    def on_progress(event):
        events.append(event)
        tipo = event["type"]
        if tipo == "health_check":
            print(f"[{tipo}] proveedores: {event.get('providers', [])}")
        elif tipo == "spec_parsed":
            print(f"[{tipo}] objetivo: {event.get('objetivo')}")
        elif tipo == "plan_generated":
            print(f"[{tipo}] tareas: {event.get('tasks_count')}")
        elif tipo == "task_started":
            print(f"[{tipo}] {event.get('task_id')}: {event.get('task_name')}")
        elif tipo == "task_completed":
            print(f"[{tipo}] {event.get('task_id')} "
                  f"passed={event.get('criterion_passed')} "
                  f"attempts={event.get('attempts_used')}")
        elif tipo == "task_failed":
            print(f"[{tipo}] {event.get('task_id')}: {event.get('diagnosis')}")
        elif tipo == "documentation_started":
            print(f"[{tipo}] {event.get('message')}")
        elif tipo == "documentation_completed":
            print(f"[{tipo}] {event.get('message')}")
        elif tipo == "documentation_failed":
            print(f"[{tipo}] {event.get('error')}")
        elif tipo == "checkpoint_restored":
            print(f"[{tipo}] proyecto {event.get('project_id')} reanudado con {event.get('tasks_completed')} tareas completadas")
        elif tipo == "checkpoint_saved":
            print(f"[{tipo}] {event.get('tasks_completed')}/{event.get('tasks_total')} tareas")
    orchestrator = Orchestrator()
    result = orchestrator.run(spec_path, on_progress)

    print(f"\n=== RESULTADO FINAL ===")
    print(f"success: {result['success']}")
    print(f"project_id: {result['project_id']}")
    print(f"completed: {result['completed']}")
    print(f"failed: {result['failed']}")
    print(f"plan_path: {result['plan_path']}")
    if result.get("documentation"):
        doc = result["documentation"]
        print(f"documentation: success={doc.get('success')}, files={doc.get('files_documented', 0)}")
    print(f"\nResumen de tareas:")
    for t in result['tasks_summary']:
        print(f"  [{t['status']}] {t['id']}: {t['name']}")
        print(f"    criterion_passed={t['criterion_passed']} "
              f"attempts={t['attempts_used']}")
        if t['filename']:
            print(f"    archivo: {t['filename']}")
        if t['diagnosis']:
            print(f"    diagnosis: {t['diagnosis']}")

    print("\nORCHESTRATOR OK" if result['success']
          else f"ORCHESTRATOR FALLÓ: {result.get('error')}")

    # PRUEBA ADICIONAL: Verificar propagación de project_id
    print("\n=== PRUEBA ADICIONAL: Propagación de project_id ===")
    orchestrator2 = Orchestrator()
    # Simulamos una ejecución mínima sin llegar a llamar LLMs reales
    orchestrator2.project_id = "test-proj-123"
    task_mock = {
        "id": "T1",
        "name": "mock task",
        "description": "mock",
        "acceptance_criterion": "mock",
        "depends_on": [],
        "status": "pending"
    }
    # Parcheamos generate_and_test para no ejecutar realmente
    original_generate = orchestrator2.generator.generate_and_test
    def mock_generate_and_test(task):
        # Verificar que task contiene project_id
        assert task.get("project_id") == "test-proj-123", "project_id no se propagó a la tarea"
        return {"success": True, "code": "print('ok')", "filename": "mock.py", "execution": {"criterion_passed": True}}
    orchestrator2.generator.generate_and_test = mock_generate_and_test
    
    try:
        result2 = orchestrator2._run_task(task_mock)
        assert result2.get("success") == True
        print("✅ project_id propagado correctamente en _run_task")
    finally:
        orchestrator2.generator.generate_and_test = original_generate