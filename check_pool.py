#!/usr/bin/env python3
# check_pool.py — Script de diagnóstico del Pool APA
# Ubicación: C:\Python\Proyectos\APA\check_pool.py  (raíz del proyecto)
# Ejecución:  cd C:\Python\Proyectos\APA && python check_pool.py

import sys
import os

_project_root = os.path.dirname(os.path.abspath(__file__))
_apa_dir = os.path.join(_project_root, "apa")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _apa_dir not in sys.path:
    sys.path.insert(0, _apa_dir)

print("=" * 60)
print("APA Pool Diagnostic")
print("=" * 60)

try:
    os.chdir(_apa_dir)
    from core.pool import PoolEntry, pool
    from core.providers import provider_manager
    print("[OK] Imports exitosos")
except ImportError as e:
    print(f"[ERROR] Import fallido: {e}")
    print("Asegúrate de ejecutar desde la raíz del proyecto APA")
    sys.exit(1)

print("\n--- Poblando pool desde providers ---")
try:
    from core import router
    count = router.populate_pool(force=True)
    print(f"[OK] Pool poblado: {count} entradas")
except Exception as e:
    print(f"[WARN] router.populate_pool falló: {e}")
    print("Intentando poblar manualmente...")
    try:
        all_models = provider_manager.get_all_models_with_provider()
        added = 0
        for item in all_models:
            provider_name = item.get("provider", "unknown")
            model = item.get("model", item)
            if isinstance(model, dict):
                mid = model.get("id", model.get("model_id", "unknown"))
                ctx = model.get("context_length", 8192)
                free = model.get("is_free", False)
                arena = model.get("arena_score")
                conf = model.get("provider_confidence", 50.0)
            else:
                mid = str(model)
                ctx = 8192
                free = False
                arena = None
                conf = 50.0
            entry = PoolEntry(
                provider=provider_name,
                model_id=mid,
                context_length=ctx,
                is_free=free,
                arena_score=arena,
                provider_confidence=conf,
            )
            pool.add_entry(entry)
            added += 1
        print(f"[OK] Pool poblado manualmente: {added} entradas")
    except Exception as e2:
        print(f"[ERROR] Poblado manual también falló: {e2}")

print("\n" + "=" * 60)
print("RESULTADOS DEL DIAGNÓSTICO")
print("=" * 60)

all_entries = pool.get_all_entries()
print(f"\nTotal entradas en pool: {len(all_entries)}")

free_entries = [e for e in all_entries if e.is_free]
paid_entries = [e for e in all_entries if not e.is_free]
print(f"Modelos gratuitos: {len(free_entries)}")
print(f"Modelos de pago:   {len(paid_entries)}")

print("\n--- Top 5 modelos GRATUITOS (por composite_score) ---")
top5_free = sorted(free_entries, key=lambda x: x.composite_score, reverse=True)[:5]
if top5_free:
    for m in top5_free:
        print(f"  {m.model_id:<45s} score={m.composite_score:6.1f}  health={m.health_status}  provider={m.provider}")
else:
    print("  (no hay modelos gratuitos en el pool)")

print("\n--- Top 5 modelos DE PAGO (por composite_score) ---")
top5_paid = sorted(paid_entries, key=lambda x: x.composite_score, reverse=True)[:5]
if top5_paid:
    for m in top5_paid:
        print(f"  {m.model_id:<45s} score={m.composite_score:6.1f}  health={m.health_status}  provider={m.provider}")
else:
    print("  (no hay modelos de pago en el pool)")

print("\n--- Resumen de salud del pool ---")
summary = pool.health_summary()
for status, count in sorted(summary.items(), key=lambda x: -x[1]):
    print(f"  {status:<25s}: {count}")

available = [e for e in all_entries if e.health_status == "available"]
free_available = [e for e in available if e.is_free]
paid_available = [e for e in available if not e.is_free]
print(f"\nModelos disponibles (health=available): {len(available)}")
print(f"  Gratuitos disponibles: {len(free_available)}")
print(f"  De pago disponibles:   {len(paid_available)}")

print("\n--- Mejor modelo gratuito por tipo de tarea ---")
task_types = ["planning", "coding", "evaluation", "generation", "correction"]
for tt in task_types:
    ranked = pool.get_ranked_entries(task_type=tt, only_available=True)
    best_free = None
    for e in ranked:
        if e.is_free:
            best_free = e
            break
    if best_free:
        print(f"  {tt:<14s}: {best_free.model_id:<40s} score={best_free.task_score(tt):6.1f}  provider={best_free.provider}")
    else:
        if ranked:
            best_paid = ranked[0]
            print(f"  {tt:<14s}: (solo pago) {best_paid.model_id:<32s} score={best_paid.task_score(tt):6.1f}")
        else:
            print(f"  {tt:<14s}: (sin modelos disponibles)")

print("\n" + "=" * 60)
print("Diagnóstico completado")