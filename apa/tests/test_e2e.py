# apa/tests/test_e2e.py
import sys
import os
import time
import logging
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.providers import provider_manager
from core.router import select_model, get_all_available_models

def test_end_to_end():
    import logging
    import time
    from pathlib import Path
    from core.orchestrator import Orchestrator

    # ====================== SILENCIAR LOGS ======================
    logging.basicConfig(handlers=[], level=logging.CRITICAL, force=True)
    logging.disable(logging.CRITICAL)
    for lib in ["requests", "urllib3", "paramiko", "core", "agents", "mcp"]:
        logging.getLogger(lib).setLevel(logging.CRITICAL)

    # ====================== MÉTRICAS DE ROUTER ======================
    print("\n" + "=" * 70)
    print("🔎 APA ROUTER DIAGNÓSTICO")
    print("=" * 70)

    # Pool de modelos
    all_models = get_all_available_models()
    total_models = len(all_models)
    provider_counts = defaultdict(int)
    for m in all_models:
        provider_counts[m.get("provider", "unknown")] += 1

    print(f"\n📊 POOL DE MODELOS: {total_models} modelos")
    for prov, count in sorted(provider_counts.items(), key=lambda x: -x[1]):
        print(f"   - {prov}: {count}")

    # Ranking dinámico
    print("\n🎯 RANKING DINÁMICO (mejores modelos por tarea)")
    for task_type in ("planning", "generation", "correction"):
        t0 = time.time()
        model_id = select_model(task_type)
        sel_time = time.time() - t0
        # Buscar proveedor del modelo
        provider = next((m.get("provider") for m in all_models if m["id"] == model_id), "?")
        print(f"   {task_type.capitalize():10} → {model_id} ({provider}) [{sel_time*1000:.0f}ms]")

    # ====================== EJECUCIÓN DEL ORQUESTADOR ======================
    spec_path = Path(__file__).parent.parent / "specs" / "example.md"
    print("\n" + "=" * 70)
    print(f"🚀 EJECUCIÓN DEL PROYECTO")
    print(f"📄 Spec: {spec_path.name}")
    print("=" * 70)

    orchestrator = Orchestrator()
    start_time = time.time()
    stage_times = {}
    last_time = start_time
    task_models = {}  # task_id -> modelo usado
    task_times = {}   # task_id -> duración en segundos

    def on_progress(event):
        nonlocal last_time
        now = time.time()
        elapsed = now - start_time
        stage_elapsed = now - last_time
        etype = event.get("type")
        stage_times[etype] = stage_times.get(etype, 0.0) + stage_elapsed
        last_time = now

        if etype in ("health_check", "spec_parsed", "plan_generated",
                     "task_completed", "task_failed", "documentation_completed"):
            icon = "✅" if etype != "task_failed" else "❌"
            name = etype.replace("_", " ").title()
            extra = ""
            if etype == "health_check":
                extra = f" | proveedores activos: {len(event.get('providers', []))}"
            elif etype == "spec_parsed":
                extra = f" | objetivo: {event.get('objetivo', '')[:30]}..."
            elif etype == "plan_generated":
                extra = f" | tareas: {event.get('tasks_count', 0)}"
            elif etype in ("task_completed", "task_failed"):
                tid = event.get("task_id")
                tname = event.get("task_name", "")
                model = event.get("model_used", "?")
                provider = event.get("provider_used", "?")
                task_models[tid] = f"{model} ({provider})"
                extra = f" | {tid}: {tname[:30]} | modelo: {model}"
            elif etype == "documentation_completed":
                extra = f" | archivos: {event.get('files_documented', 0)}"

            print(f"{icon} {name:22} | +{stage_elapsed:5.1f}s (total {elapsed:5.1f}s){extra}")

    result = orchestrator.run(str(spec_path), on_progress=on_progress)
    total_elapsed = time.time() - start_time

    # ====================== INFORME DE TAREAS Y MODELOS ======================
    print("\n" + "=" * 70)
    print("📋 DETALLE DE TAREAS EJECUTADAS")
    print("=" * 70)
    if "tasks_summary" in result:
        for task in result["tasks_summary"]:
            if task["status"] == "completed":
                tid = task["id"]
                name = task["name"]
                model_info = task_models.get(tid, task.get("model_used", "?"))
                attempts = task.get("attempts_used", 1)
                print(f"   {tid}: {name}")
                print(f"       Modelo: {model_info} | Intentos: {attempts}")
    else:
        print("   No hay información detallada de tareas.")

    # ====================== RESUMEN FINAL ======================
    print("\n" + "=" * 70)
    print("📊 RESUMEN FINAL")
    print("=" * 70)
    success = result.get("success", False)
    status = "✅ ÉXITO" if success else "❌ FALLÓ"
    print(f"Estado global: {status}")
    print(f"Tareas completadas: {result.get('completed', 0)} / {result.get('completed', 0) + result.get('failed', 0)}")
    print(f"Documentación generada: {result.get('documentation', {}).get('success', False)}")
    print(f"Tiempo total: {total_elapsed:.1f} segundos")

    # ====================== VALIDACIONES ======================
    if not success:
        raise AssertionError(f"El proyecto falló: {result.get('error', 'desconocido')}")
    assert result.get("failed", 0) == 0, f"Fallaron {result['failed']} tareas"
    assert result.get("documentation", {}).get("success") is True, "No se generó documentación"
    plan_path = Path(result["plan_path"])
    assert plan_path.exists(), "No se guardó el plan.json"

    # ====================== REACTIVAR LOGS ======================
    logging.disable(logging.NOTSET)

    print("\n✅ T6 - Integración end‑to‑end: TODAS LAS PRUEBAS PASARON.")
    return True

if __name__ == "__main__":
    try:
        test_end_to_end()
    except Exception as e:
        print(f"❌ FALLIDA: {e}")
        import traceback
        traceback.print_exc()