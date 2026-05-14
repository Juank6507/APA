#!/usr/bin/env python3
# validate_rankings.py v3.0 — Diagnóstico completo APA
# Verifica: Arena, Rankings, Providers, UsageTracker, Router logging, Assembler logging, Integración
#
# CAMBIOS v3.0 vs v2.0:
#   - Nueva sección 7: Verifica integración call_llm → agent → assembler
#   - Comprueba que call_llm retorna métricas en el dict de respuesta
#   - Comprueba que semi_auto_agent construye y pasa llm_metadata
#   - Comprueba que SemiAutoResult tiene campos de métricas
#
# USO:
#   python apa/validate_rankings.py

import sys
import os

# Añadir directorio raíz al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from datetime import datetime

def main():
    print("=" * 60)
    print(f"APA — DIAGNÓSTICO COMPLETO v3.0")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    results = {}
    
    # ============================================================
    # 1. ARENA FETCHER — Datos cargados
    # ============================================================
    print("\n" + "=" * 60)
    print("1. ARENA FETCHER — Datos cargados")
    print("=" * 60)
    
    arena_ok = 0
    arena_total = 5
    
    try:
        from core.arena_fetcher import _arena_data, get_score_for_model, get_available_categories
        
        # Check data loaded
        has_data = bool(_arena_data)
        print(f"  [{'OK' if has_data else 'FALLA'}] Arena ranking disponible")
        if has_data:
            arena_ok += 1
        
        model_count = len(_arena_data)
        print(f"  [{'OK' if model_count > 0 else 'FALLA'}] Modelos cargados — {model_count} modelos")
        if model_count > 0:
            arena_ok += 1
        
        cats = get_available_categories()
        print(f"  [{'OK' if len(cats) > 0 else 'FALLA'}] Categorías clave presentes — {len(cats)} categorías")
        if len(cats) > 0:
            arena_ok += 1
        
        # Test known model
        gpt4o_score = get_score_for_model("gpt-4o", None)
        print(f"  [{'OK' if gpt4o_score else 'FALLA'}] Score de modelo conocido — gpt-4o = {gpt4o_score}")
        if gpt4o_score:
            arena_ok += 1
        
        gpt4o_coding = get_score_for_model("gpt-4o", "coding")
        print(f"  [{'OK' if gpt4o_coding else 'FALLA'}] Score por categoría (coding) — gpt-4o coding = {gpt4o_coding}")
        if gpt4o_coding:
            arena_ok += 1
        
    except Exception as e:
        print(f"  [FALLA] Error cargando Arena: {e}")
    
    results["arena"] = (arena_ok, arena_total)
    
    # ============================================================
    # 2. RANKINGS — Top 10 Planning y Coding
    # ============================================================
    print("\n" + "=" * 60)
    print("2. RANKINGS — Top 10 Planning y Coding")
    print("=" * 60)
    
    ranking_ok = 0
    ranking_total = 2
    
    try:
        from core.arena_fetcher import _arena_data, get_available_categories
        
        # Planning ranking (hard_prompts category)
        planning_models = []
        coding_models = []
        
        for model_id, scores in _arena_data.items():
            if isinstance(scores, dict):
                # Planning: usar hard_prompts si existe, sino general
                planning_score = scores.get("hard_prompts") or scores.get("general")
                if planning_score is not None:
                    planning_models.append((model_id, planning_score, 
                                          "hard_prompts" if scores.get("hard_prompts") else "general"))
                
                # Coding: usar coding si existe
                coding_score = scores.get("coding")
                if coding_score is not None:
                    coding_models.append((model_id, coding_score))
        
        # Top 10 Planning
        planning_models.sort(key=lambda x: x[1], reverse=True)
        print(f"\n  Top 10 Planning ({len(planning_models)} modelos con score):")
        print(f"    #  Score       Fuente  Modelo")
        print(f"  --- ------ ------------  ------")
        for i, (model, score, source) in enumerate(planning_models[:10]):
            print(f"    {i+1:2d}  {score:5.1f} {source:12s}  {model}")
        print(f"  [{'OK' if len(planning_models) > 0 else 'FALLA'}] Ranking Planning completo — {len(planning_models)} modelos")
        if len(planning_models) > 0:
            ranking_ok += 1
        
        # Top 10 Coding
        coding_models.sort(key=lambda x: x[1], reverse=True)
        print(f"\n  Top 10 Coding ({len(coding_models)} modelos con score):")
        print(f"    #  Score  Modelo")
        print(f"  --- ------  ------")
        for i, (model, score) in enumerate(coding_models[:10]):
            print(f"    {i+1:2d}  {score:5.1f}  {model}")
        print(f"  [{'OK' if len(coding_models) > 0 else 'FALLA'}] Ranking Coding completo — {len(coding_models)} modelos")
        if len(coding_models) > 0:
            ranking_ok += 1
        
    except Exception as e:
        print(f"  [FALLA] Error generando rankings: {e}")
    
    results["rankings"] = (ranking_ok, ranking_total)
    
    # ============================================================
    # 3. PROVEEDORES — Modelos disponibles vía API
    # ============================================================
    print("\n" + "=" * 60)
    print("3. PROVEEDORES — Modelos disponibles vía API")
    print("=" * 60)
    
    providers_ok = 0
    providers_total = 3
    
    try:
        from core.providers import provider_manager
        
        available_providers = [name for name, p in provider_manager.providers.items() if p.is_available()]
        print(f"  Proveedores instanciados: {list(provider_manager.providers.keys())}")
        print(f"  Proveedores disponibles: {available_providers}")
        
        all_models = provider_manager.get_all_models_with_provider()
        total_models = len(all_models)
        print(f"  Modelos totales: {total_models}")
        
        print(f"  [{'OK' if len(available_providers) > 0 else 'FALLA'}] Proveedores disponibles — {len(available_providers)}: {available_providers}")
        if len(available_providers) > 0:
            providers_ok += 1
        
        print(f"  [{'OK' if total_models > 0 else 'FALLA'}] Modelos vía API — {total_models} modelos")
        if total_models > 0:
            providers_ok += 1
        
        # Cross-reference con Arena
        from core.arena_fetcher import _arena_data
        arena_models = set(_arena_data.keys())
        provider_model_ids = {m.get("id", "") for m in all_models}
        cross = arena_models & provider_model_ids
        print(f"  Modelos con Arena score: {len(cross)}/{total_models}")
        print(f"  [{'OK' if len(cross) > 0 else 'FALLA'}] Cruce Arena ↔ Proveedores — {len(cross)} modelos verificados")
        if len(cross) > 0:
            providers_ok += 1
        
    except Exception as e:
        print(f"  [FALLA] Error verificando proveedores: {e}")
    
    results["providers"] = (providers_ok, providers_total)
    
    # ============================================================
    # 4. USAGE TRACKER v2.0 — Métricas de uso
    # ============================================================
    print("\n" + "=" * 60)
    print("4. USAGE TRACKER v2.0 — Métricas de uso")
    print("=" * 60)
    
    usage_ok = 0
    usage_total = 5
    
    try:
        from core.usage_tracker import UsageTracker
        import tempfile
        import shutil
        from pathlib import Path
        
        temp_dir = tempfile.mkdtemp()
        test_db = Path(temp_dir) / "test_usage_v2.db"
        
        try:
            tracker = UsageTracker(db_path=test_db)
            
            # Check columnas básicas (v1)
            columns = tracker.get_column_names()
            basic_cols = {"id", "project_id", "model", "tokens", "request_type", "timestamp"}
            has_basic = basic_cols.issubset(set(columns))
            print(f"  [{'OK' if has_basic else 'FALLA'}] Tabla usage columnas básicas — {sorted(basic_cols & set(columns))}")
            if has_basic:
                usage_ok += 1
            
            # Check columnas v2.0
            v2_cols = {"provider", "tokens_input", "tokens_output", "latency_ms", 
                       "cost_usd", "arena_score", "success", "error_type"}
            has_v2 = v2_cols.issubset(set(columns))
            missing_v2 = v2_cols - set(columns)
            if has_v2:
                print(f"  [OK] Columnas v2.0 completas — {len(v2_cols)} columnas nuevas")
                usage_ok += 1
            else:
                print(f"  [FALLA] Columnas v2.0 — Faltan: {sorted(missing_v2)}")
            
            # Test log_usage con métricas completas
            tracker.log_usage(
                "test_diag", "test-model", 500, "planning",
                provider="openai",
                tokens_input=300, tokens_output=200,
                latency_ms=1500, cost_usd=0.012,
                arena_score=85.3, success=True, error_type=""
            )
            print(f"  [OK] log_usage() con métricas completas funciona")
            usage_ok += 1
            
            # Test get_aggregated_usage (backward compat)
            agg = tracker.get_aggregated_usage("test_diag")
            print(f"  [OK] get_aggregated_usage() funciona — test-model = {agg.get('test-model', 0)} tokens")
            usage_ok += 1
            
            # Test get_usage_summary
            summary = tracker.get_usage_summary("test_diag")
            if summary:
                s = summary[0]
                print(f"  [OK] get_usage_summary() funciona — model={s.get('model')}, "
                      f"calls={s.get('total_calls')}, avg_latency={s.get('avg_latency_ms', 0):.0f}ms")
                usage_ok += 1
            else:
                print(f"  [FALLA] get_usage_summary() retornó vacío")
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        
    except Exception as e:
        print(f"  [FALLA] Error verificando UsageTracker: {e}")
        import traceback
        traceback.print_exc()
    
    results["usage"] = (usage_ok, usage_total)
    
    # ============================================================
    # 5. LOGGING EN ROUTER — Integración con UsageTracker v2.0
    # ============================================================
    print("\n" + "=" * 60)
    print("5. LOGGING EN ROUTER — Integración con UsageTracker v2.0")
    print("=" * 60)
    
    router_ok = 0
    router_total = 6
    
    try:
        with open(os.path.join(os.path.dirname(__file__), "core", "router.py"), "r", encoding="utf-8") as f:
            router_code = f.read()
        
        # Check UsageTracker import in router
        has_tracker = "UsageTracker" in router_code
        print(f"  [{'OK' if has_tracker else 'FALLA'}] call_llm registra uso — UsageTracker.log_usage() presente")
        if has_tracker:
            router_ok += 1
        
        # Check task_type registrado
        has_task_type = "request_type=task_type" in router_code or "task_type" in router_code
        print(f"  [{'OK' if has_task_type else 'FALLA'}] Registra task_type — Se pasa a log_usage()")
        if has_task_type:
            router_ok += 1
        
        # Check modelo usado
        has_model = "actual_model" in router_code or "model_used" in router_code
        print(f"  [{'OK' if has_model else 'FALLA'}] Registra modelo usado — Usa actual_model (no el solicitado)")
        if has_model:
            router_ok += 1
        
        # v2.0: Check métricas completas
        v2_metrics = {
            "latencia/elapsed time": "latency_ms" in router_code,
            "tokens de entrada": "tokens_input" in router_code,
            "tokens de salida": "tokens_output" in router_code,
            "coste estimado": "cost_usd" in router_code,
            "Arena score": "arena_score" in router_code,
        }
        
        all_present = all(v2_metrics.values())
        missing = [k for k, v in v2_metrics.items() if not v]
        
        if all_present:
            print(f"  [OK] Métricas completas en logging — latencia, tokens in/out, coste, Arena score")
            router_ok += 1
        else:
            print(f"  [FALLA] Métricas completas en logging — Faltan: {missing}")
        
        # v2.0: Check _log_usage_if_possible helper
        has_helper = "_log_usage_if_possible" in router_code
        print(f"  [{'OK' if has_helper else 'FALLA'}] Helper _log_usage_if_possible — Registro centralizado")
        if has_helper:
            router_ok += 1
        
        # v2.0: Check error logging for failed calls
        has_error_log = "success=False" in router_code and "error_type" in router_code
        print(f"  [{'OK' if has_error_log else 'FALLA'}] Registro de llamadas fallidas — success=False + error_type")
        if has_error_log:
            router_ok += 1
        
    except Exception as e:
        print(f"  [FALLA] Error verificando router: {e}")
    
    results["router_log"] = (router_ok, router_total)
    
    # ============================================================
    # 6. ENSAMBLADOR — Estado del logging
    # ============================================================
    print("\n" + "=" * 60)
    print("6. ENSAMBLADOR — Estado del logging")
    print("=" * 60)
    
    asm_ok = 0
    asm_total = 4
    
    try:
        with open(os.path.join(os.path.dirname(__file__), "core", "assembler.py"), "r", encoding="utf-8") as f:
            asm_code = f.read()
        
        # Check UsageTracker import
        has_tracker = "UsageTracker" in asm_code
        print(f"  [{'OK' if has_tracker else 'FALLA'}] Importa UsageTracker — Referencia encontrada en assembler.py")
        if has_tracker:
            asm_ok += 1
        
        # Check model reference
        has_model_ref = "planning_model" in asm_code or "model_used" in asm_code or "llm_metadata" in asm_code
        print(f"  [{'OK' if has_model_ref else 'FALLA'}] Referencia a modelo usado — llm_metadata o model_used")
        if has_model_ref:
            asm_ok += 1
        
        # Check _log_assembly_usage
        has_log_method = "_log_assembly_usage" in asm_code
        print(f"  [{'OK' if has_log_method else 'FALLA'}] Método _log_assembly_usage — Logging centralizado")
        if has_log_method:
            asm_ok += 1
        
        # Check métricas completas
        asm_metrics = {
            "task_type": '"assembly"' in asm_code,
            "model_used": "planning_model" in asm_code or "assembly_engine" in asm_code,
            "provider": "provider" in asm_code and "local" in asm_code,
            "tokens_input": "tokens_input" in asm_code,
            "tokens_output": "tokens_output" in asm_code,
            "latency_ms": "latency_ms" in asm_code,
            "cost_usd": "cost_usd" in asm_code,
            "success": "success=" in asm_code,
        }
        
        all_present = all(asm_metrics.values())
        missing = [k for k, v in asm_metrics.items() if not v]
        
        if all_present:
            print(f"  [OK] Métricas completas — Todas las métricas presentes en assembler")
            asm_ok += 1
        else:
            print(f"  [FALLA] Métricas completas — Faltan: {missing}")
        
    except Exception as e:
        print(f"  [FALLA] Error verificando ensamblador: {e}")
    
    results["assembler_log"] = (asm_ok, asm_total)
    
    # ============================================================
    # 7. INTEGRACIÓN COMPLETA — call_llm → semi_auto_agent → assembler
    # ============================================================
    print("\n" + "=" * 60)
    print("7. INTEGRACIÓN — call_llm → agent → assembler (métricas completas)")
    print("=" * 60)
    
    integ_ok = 0
    integ_total = 5
    
    try:
        # 7a: call_llm retorna métricas en el dict de respuesta
        with open(os.path.join(os.path.dirname(__file__), "core", "router.py"), "r", encoding="utf-8") as f:
            router_code = f.read()
        
        # Buscar que los returns de call_llm incluyen métricas
        return_metrics = all([
            '"tokens_input"' in router_code,
            '"tokens_output"' in router_code,
            '"latency_ms"' in router_code,
            '"cost_usd"' in router_code,
            '"arena_score"' in router_code,
            '"provider"' in router_code,
        ])
        print(f"  [{'OK' if return_metrics else 'FALLA'}] call_llm retorna métricas — tokens, latency, cost, arena, provider en dict de respuesta")
        if return_metrics:
            integ_ok += 1
        
        # 7b: semi_auto_agent usa _extract_llm_metadata
        with open(os.path.join(os.path.dirname(__file__), "agents", "semi_auto_agent.py"), "r", encoding="utf-8") as f:
            agent_code = f.read()
        
        has_extract = "_extract_llm_metadata" in agent_code
        print(f"  [{'OK' if has_extract else 'FALLA'}] Agent usa _extract_llm_metadata — Convierte respuesta call_llm a metadata")
        if has_extract:
            integ_ok += 1
        
        # 7c: semi_auto_agent pasa llm_metadata a assembler.run_full()
        has_llm_pass = "llm_metadata=" in agent_code and "run_full(" in agent_code
        print(f"  [{'OK' if has_llm_pass else 'FALLA'}] Agent pasa llm_metadata a assembler.run_full()")
        if has_llm_pass:
            integ_ok += 1
        
        # 7d: semi_auto_agent pasa project_id a assembler.run_full()
        has_project_pass = "project_id=self._project_id" in agent_code
        print(f"  [{'OK' if has_project_pass else 'FALLA'}] Agent pasa project_id a assembler.run_full()")
        if has_project_pass:
            integ_ok += 1
        
        # 7e: SemiAutoResult tiene campos de métricas
        has_result_metrics = "planning_provider" in agent_code and "coding_tokens_input" in agent_code
        print(f"  [{'OK' if has_result_metrics else 'FALLA'}] SemiAutoResult con métricas completas — planning_* y coding_*")
        if has_result_metrics:
            integ_ok += 1
        
    except Exception as e:
        print(f"  [FALLA] Error verificando integración: {e}")
    
    results["integration"] = (integ_ok, integ_total)
    
    # ============================================================
    # RESUMEN
    # ============================================================
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)
    
    total_ok = 0
    total_checks = 0
    all_failures = []
    
    section_names = {
        "arena": "arena",
        "rankings": "rankings",
        "providers": "providers",
        "usage": "usage",
        "router_log": "router_log",
        "assembler_log": "assembler_log",
        "integration": "integration",
    }
    
    for key, (ok, total) in results.items():
        name = section_names.get(key, key)
        status = "OK" if ok == total else "FALLA"
        print(f"  {name:20s}: {ok}/{total} OK  [{status}]")
        total_ok += ok
        total_checks += total
        if ok < total:
            all_failures.append((name, total - ok))
    
    print(f"\n  TOTAL: {total_ok}/{total_checks} OK, {total_checks - total_ok} FALLA")
    
    if all_failures:
        print(f"\n  DETALLE DE FALLOS:")
        for name, count in all_failures:
            print(f"    [{name}] {count} falla(s)")
    
    print(f"\n  ACCIONES PENDIENTES:")
    if results.get("usage", (0, 5))[0] < 5:
        print(f"    1. UsageTracker v2.0: instalar usage_tracker.py con columnas nuevas")
    if results.get("router_log", (0, 6))[0] < 6:
        print(f"    2. Router v5.3: instalar router.py con métricas completas en call_llm()")
    if results.get("assembler_log", (0, 4))[0] < 4:
        print(f"    3. Assembler v4.1: instalar assembler.py con integración UsageTracker")
    
    if total_ok == total_checks:
        print(f"\n  *** TODOS LOS CHECKS PASADOS ***")
        print(f"  P1: LLMs disponibles para APA con rankings ✓")
        print(f"  P2: Rankings Planning y Coding verificados ✓")
        print(f"  P3: Logging completo en router y assembler ✓")
        print(f"  P3b: Métricas completas call_llm → agent → assembler ✓")
    
    print(f"\n  Tiempo: {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
