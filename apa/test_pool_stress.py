#!/usr/bin/env python3
# test_pool_stress.py — Test de estres del pool APA
#
# FUERZA el pipeline completo:
#   1. populate_pool(force=True) con espera de Arena data
#   2. Para cada ranking (planning, coding, evaluation, generation, correction):
#      - Obtiene top-N modelos del pool (get_ranked_entries)
#      - Llama cada uno con call_llm() prompt minimo ("Responde solo: OK")
#      - Registra: success, provider, arena_score, tokens, cost, latency, error
#   3. Reporte final con tasa de exito por ranking y modelo
#
# USO:
#   cd APA                          # Desde la raiz del proyecto APA
#   python apa/test_pool_stress.py           # Top-10 por ranking
#   python apa/test_pool_stress.py --top 5   # Top-5 (mas rapido, mas barato)
#   python apa/test_pool_stress.py --ranking planning  # Solo planning
#   python apa/test_pool_stress.py --dry-run  # Solo muestra rankings, no llama
#
# REQUIERE: API keys configuradas en .env o settings

import sys
import os
import time
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

# Anadir raiz del proyecto al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================================
# Configuracion
# ============================================================================
RANKINGS = ["planning", "coding", "evaluation", "generation", "correction"]
DEFAULT_TOP = 10
MINI_PROMPT_SYSTEM = "You are a helpful assistant. Respond with exactly one word."
MINI_PROMPT_USER = "Respond with only the word: OK"
MINI_MAX_TOKENS = 10  # Minimo para respuesta corta


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def format_usd(cost):
    if cost == 0:
        return "$0.0000"
    return f"${cost:.6f}"


# ============================================================================
# Fase 1: Inicializar pool con Arena data
# ============================================================================
def force_populate_pool():
    """Fuerza populate_pool con Arena data y retorna diagnostico."""
    print_header("FASE 1: Forzar populate_pool() con Arena data")

    from core.router import populate_pool, _global_pool, update_arena_scores, _get_arena_module

    # Forzar populate (espera Arena data hasta 15s por fix F1)
    print("  Ejecutando populate_pool(force=True)...")
    t0 = time.time()
    count = populate_pool(force=True)
    elapsed = time.time() - t0
    print(f"  populate_pool() -> {count} entries en {elapsed:.1f}s")

    # Diagnostico del pool
    entries = _global_pool.get_all_entries()
    arena_count = sum(1 for e in entries if e.arena_score is not None)
    health_summary = _global_pool.health_summary()

    print(f"  Entries con Arena score: {arena_count}/{len(entries)}")
    print(f"  Health summary: {health_summary}")

    # F4: Safety net -- intentar llenar scores faltantes
    if arena_count < len(entries):
        print("  Ejecutando update_arena_scores() (safety net)...")
        updated = update_arena_scores()
        arena_count = sum(1 for e in _global_pool.get_all_entries() if e.arena_score is not None)
        print(f"  Despues de update_arena_scores(): {arena_count}/{len(entries)} con Arena score")

    # Diagnostico Arena fetcher
    try:
        af = _get_arena_module()
        with af._refresh_lock:
            arena_data_size = len(af._arena_data) if af._arena_data else 0
        cats = []
        if af._arena_data:
            for scores in af._arena_data.values():
                cats.extend(scores.keys())
            cats = sorted(set(cats))
        print(f"  Arena fetcher: {arena_data_size} modelos, categorias: {cats[:8]}...")
    except Exception as e:
        print(f"  Arena fetcher diagnostico fallo: {e}")

    # Providers disponibles
    try:
        from core.providers import provider_manager
        avail_providers = provider_manager.get_available_providers()
        print(f"  Providers disponibles: {avail_providers}")
        for pname in provider_manager.providers:
            p = provider_manager.providers[pname]
            models_count = len(p.get_models()) if p.is_available() else 0
            print(f"    {pname}: available={p.is_available()}, models={models_count}, confidence={p.confidence_score}")
    except Exception as e:
        print(f"  Provider diagnostico fallo: {e}")

    return {
        "total_entries": count,
        "arena_scored": arena_count,
        "health_summary": health_summary,
        "elapsed_s": elapsed,
    }


# ============================================================================
# Fase 2: Mostrar top-N por ranking
# ============================================================================
def show_rankings(top_n, rankings_list=None):
    """Muestra top-N modelos por ranking y retorna los datos."""
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header(f"FASE 2: Top-{top_n} modelos por ranking")

    from core.router import _global_pool

    rankings_data = {}

    for ranking in rankings_list:
        entries = _global_pool.get_ranked_entries(
            task_type=ranking,
            exclude_statuses=["payment_required", "failed"],
        )

        print(f"\n  RANKING {ranking.upper()} -- Top {min(top_n, len(entries))} de {len(entries)} candidatos")
        print(f"  {'#':>3} {'Modelo':<45} {'Provider':<12} {'Arena':>6} {'Score':>6} {'Health':<12}")
        print(f"  {'---':>3} {'-'*45} {'-'*12} {'-'*6} {'-'*6} {'-'*12}")

        top_entries = entries[:top_n]
        rankings_data[ranking] = []

        for i, e in enumerate(top_entries, 1):
            arena_str = f"{e.arena_score:.1f}" if e.arena_score is not None else "---"
            score_str = f"{e.composite_score:.1f}"
            health_str = e.health_status or "unknown"
            model_str = e.model_id[:45]
            provider_str = e.provider[:12]

            print(f"  {i:>3} {model_str:<45} {provider_str:<12} {arena_str:>6} {score_str:>6} {health_str:<12}")

            rankings_data[ranking].append({
                "rank": i,
                "model_id": e.model_id,
                "provider": e.provider,
                "arena_score": e.arena_score,
                "composite_score": e.composite_score,
                "health_status": e.health_status,
                "context_length": e.context_length,
                "is_free": e.is_free,
            })

    return rankings_data


# ============================================================================
# Fase 3: Llamar LLMs reales -- test de estres
# ============================================================================
def stress_test(rankings_data, top_n, rankings_list=None):
    """Llama cada modelo del top-N con prompt minimo y registra resultados."""
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header(f"FASE 3: Stress test -- llamar {top_n} modelos por ranking")

    from core.router import call_llm

    all_results = []
    total_calls = 0
    total_success = 0
    total_cost = 0.0

    for ranking in rankings_list:
        models = rankings_data.get(ranking, [])
        print(f"\n  RANKING {ranking.upper()} -- Llamando {len(models)} modelos...")

        for m in models:
            total_calls += 1
            model_id = m["model_id"]
            provider = m["provider"]
            arena = m["arena_score"]

            print(f"    [{total_calls}] {model_id} via {provider} (Arena: {arena})... ", end="", flush=True)

            t0 = time.time()
            try:
                result = call_llm(
                    task_type=ranking,
                    system_prompt=MINI_PROMPT_SYSTEM,
                    user_prompt=MINI_PROMPT_USER,
                    max_tokens=MINI_MAX_TOKENS,
                    temperature=0.0,
                    project_id=f"stress_test_{ranking}",
                )
                elapsed = time.time() - t0

                success = result.get("success", False)
                tokens_out = result.get("tokens_output", 0)
                latency = result.get("latency_ms", 0)
                cost = result.get("cost_usd", 0.0)
                result_provider = result.get("provider", "unknown")
                result_arena = result.get("arena_score")
                error_type = result.get("error_type", "")
                error_msg = result.get("error", "")
                attempts = result.get("attempts", 1)
                content_preview = result.get("content", "")[:30].replace("\n", " ")

                if success:
                    total_success += 1
                    total_cost += cost
                    status = "OK"
                    detail = f"provider={result_provider} tokens={tokens_out} latency={latency}ms cost={format_usd(cost)} arena={result_arena} content='{content_preview}'"
                else:
                    status = "FAIL"
                    detail = f"provider={result_provider} error={error_type}:{error_msg[:50]} attempts={attempts}"

                print(f"{status} {detail}")

                all_results.append({
                    "ranking": ranking,
                    "model_id": model_id,
                    "pool_provider": provider,
                    "result_provider": result_provider,
                    "arena_score": arena,
                    "result_arena": result_arena,
                    "success": success,
                    "tokens_output": tokens_out,
                    "latency_ms": latency,
                    "cost_usd": cost,
                    "error_type": error_type,
                    "attempts": attempts,
                    "elapsed_s": elapsed,
                })

            except Exception as e:
                elapsed = time.time() - t0
                print(f"EXCEPCION: {e}")
                all_results.append({
                    "ranking": ranking,
                    "model_id": model_id,
                    "pool_provider": provider,
                    "result_provider": "exception",
                    "arena_score": arena,
                    "result_arena": None,
                    "success": False,
                    "tokens_output": 0,
                    "latency_ms": 0,
                    "cost_usd": 0.0,
                    "error_type": "exception",
                    "attempts": 0,
                    "elapsed_s": elapsed,
                })

    return {
        "results": all_results,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_cost": total_cost,
        "success_rate": total_success / max(1, total_calls) * 100,
    }


# ============================================================================
# Fase 4: Reporte final
# ============================================================================
def print_report(stress_data, pool_data, rankings_list=None):
    """Imprime reporte final del test de estres."""
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header("FASE 4: REPORTE FINAL")

    results = stress_data["results"]

    # Resumen global
    print(f"\n  Resumen Global:")
    print(f"    Total llamadas:      {stress_data['total_calls']}")
    print(f"    Exitosas:            {stress_data['total_success']}")
    print(f"    Tasa de exito:       {stress_data['success_rate']:.1f}%")
    print(f"    Coste total:         {format_usd(stress_data['total_cost'])}")
    print(f"    Pool entries:        {pool_data['total_entries']}")
    print(f"    Con Arena score:     {pool_data['arena_scored']}")

    # Por ranking
    print(f"\n  Por Ranking:")
    for ranking in rankings_list:
        rank_results = [r for r in results if r["ranking"] == ranking]
        if not rank_results:
            print(f"    {ranking:<12} -- sin datos")
            continue
        rank_success = sum(1 for r in rank_results if r["success"])
        rank_total = len(rank_results)
        rank_cost = sum(r["cost_usd"] for r in rank_results)
        rank_rate = rank_success / max(1, rank_total) * 100
        print(f"    {ranking:<12} -- {rank_success}/{rank_total} OK ({rank_rate:.0f}%) cost={format_usd(rank_cost)}")

    # Modelos que funcionan (primera vez verificados)
    working = [r for r in results if r["success"]]
    if working:
        print(f"\n  Modelos verificados (funcionan):")
        seen = set()
        for r in working:
            key = (r["model_id"], r["result_provider"])
            if key not in seen:
                seen.add(key)
                arena_str = f"{r['result_arena']:.1f}" if r['result_arena'] is not None else "None"
                print(f"    OK  {r['model_id']:<45} via {r['result_provider']:<12} Arena={arena_str}")

    # Modelos que fallaron
    failing = [r for r in results if not r["success"]]
    if failing:
        print(f"\n  Modelos que fallaron:")
        seen = set()
        for r in failing:
            key = (r["model_id"], r["pool_provider"])
            if key not in seen:
                seen.add(key)
                print(f"    FAIL {r['model_id']:<45} via {r['pool_provider']:<12} error={r['error_type']}")

    # Arena scores confirmados vs pool
    print(f"\n  Arena Scores -- Pool vs Resultado:")
    arena_confirmed = 0
    arena_mismatch = 0
    arena_missing_result = 0
    for r in results:
        if r["success"]:
            if r["result_arena"] is not None:
                if r["arena_score"] is not None and abs(r["result_arena"] - r["arena_score"]) < 0.1:
                    arena_confirmed += 1
                elif r["arena_score"] is not None:
                    arena_mismatch += 1
            else:
                arena_missing_result += 1

    print(f"    Confirmados (pool == resultado):  {arena_confirmed}")
    print(f"    Discrepancia (pool != resultado):  {arena_mismatch}")
    print(f"    Sin Arena en resultado:            {arena_missing_result}")

    # Providers verificados
    print(f"\n  Providers verificados en llamadas reales:")
    provider_stats = {}
    for r in results:
        prov = r["result_provider"]
        if prov not in provider_stats:
            provider_stats[prov] = {"ok": 0, "fail": 0}
        if r["success"]:
            provider_stats[prov]["ok"] += 1
        else:
            provider_stats[prov]["fail"] += 1

    for prov, stats in sorted(provider_stats.items()):
        total = stats["ok"] + stats["fail"]
        rate = stats["ok"] / max(1, total) * 100
        print(f"    {prov:<15} -- {stats['ok']}/{total} OK ({rate:.0f}%)")


# ============================================================================
# Main
# ============================================================================
def main():
    # Parsear argumentos simples
    top_n = DEFAULT_TOP
    single_ranking = None
    dry_run = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--top" and i + 1 < len(args):
            top_n = int(args[i + 1])
            i += 2
        elif args[i] == "--ranking" and i + 1 < len(args):
            single_ranking = args[i + 1]
            if single_ranking not in RANKINGS:
                print(f"Ranking '{single_ranking}' no valido. Usar: {RANKINGS}")
                sys.exit(1)
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            i += 1

    # Rankings a testear (variable local, no global)
    active_rankings = [single_ranking] if single_ranking else list(RANKINGS)

    print_header("APA POOL STRESS TEST -- v1.0")
    print(f"  Fecha:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Top-N:    {top_n} modelos por ranking")
    print(f"  Rankings: {single_ranking or 'TODOS (' + ', '.join(active_rankings) + ')'}")
    print(f"  Dry-run:  {dry_run}")
    print(f"  Prompt:   '{MINI_PROMPT_USER}' (max_tokens={MINI_MAX_TOKENS})")

    # Fase 1: Forzar pool
    pool_data = force_populate_pool()

    # Verificar que hay datos
    if pool_data["total_entries"] == 0:
        print("\nERROR: No hay entries en el pool. Verifica API keys en .env")
        sys.exit(1)

    if pool_data["arena_scored"] == 0:
        print("\nAVISO: 0 entries con Arena score. El ranking sera por provider_confidence solo.")
        print("   Esto puede significar que Arena fetcher no pudo obtener datos.")

    # Fase 2: Mostrar rankings
    rankings_data = show_rankings(top_n, active_rankings)

    if dry_run:
        print("\nDRY-RUN: No se llamara a ningun LLM. Rankings mostrados arriba.")
        sys.exit(0)

    # Fase 3: Stress test
    stress_data = stress_test(rankings_data, top_n, active_rankings)

    # Fase 4: Reporte
    print_report(stress_data, pool_data, active_rankings)

    # Guardar resultados JSON
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "stress_test_results.json")
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "pool_data": pool_data,
                "stress_data": {
                    "total_calls": stress_data["total_calls"],
                    "total_success": stress_data["total_success"],
                    "total_cost": stress_data["total_cost"],
                    "success_rate": stress_data["success_rate"],
                    "results": stress_data["results"],
                },
            }, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Resultados guardados en: {output_path}")
    except Exception as e:
        print(f"\n  No se pudieron guardar resultados: {e}")

    # Exit code basado en exito
    if stress_data["success_rate"] >= 50:
        print(f"\nTest PASADO -- tasa de exito {stress_data['success_rate']:.1f}% >= 50%")
        sys.exit(0)
    elif stress_data["success_rate"] > 0:
        print(f"\nTest PARCIAL -- tasa de exito {stress_data['success_rate']:.1f}% < 50%")
        sys.exit(0)
    else:
        print(f"\nTest FALLADO -- 0% de exito en llamadas reales")
        sys.exit(1)


if __name__ == "__main__":
    main()
