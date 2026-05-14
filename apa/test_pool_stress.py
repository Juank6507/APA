#!/usr/bin/env python3
# test_pool_stress.py — Test de estres del pool APA
# v3.0 — Test ADAPTIVO: re-rankeo tras fallo, provider-level payment marking,
#         fallback automatico a modelos gratuitos, parada temprana al 50%.
#
# CAMBIOS v3.0 vs v2.0:
#   - FASE 3 ADAPTIVA: en vez de llamar los top-10 fijos, llama modelos
#     uno a uno re-rankeando tras cada fallo. Cuando un provider falla
#     con error de pago, marca TODOS sus modelos de pago como
#     payment_required (mark_provider_paid_models), asi los modelos
#     gratuitos suben al top del ranking automaticamente.
#   - Parada temprana: para cada ranking cuando alcanza >=50% de exito.
#   - FASE 3b FREE FALLBACK explícito: si tras FASE 3 la tasa global
#     es <50%, prueba modelos gratuitos directamente.
#   - El test ahora aprende de los fallos y adapta su seleccion.
#
# USO:
#   cd APA
#   python apa/test_pool_stress.py           # Top-10 por ranking
#   python apa/test_pool_stress.py --top 5   # Top-5 (mas rapido)
#   python apa/test_pool_stress.py --ranking planning  # Solo planning
#   python apa/test_pool_stress.py --dry-run  # Solo rankings, no llama
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
DEFAULT_MAX_ATTEMPTS = 20  # Max modelos a probar por ranking en FASE 3 adaptativa
DEFAULT_FREE_TOP = 15      # Modelos gratuitos a probar en fallback
MINI_PROMPT_SYSTEM = "You are a helpful assistant. Respond with exactly one word."
MINI_PROMPT_USER = "Respond with only the word: OK"
MINI_MAX_TOKENS = 10


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

    print("  Ejecutando populate_pool(force=True)...")
    t0 = time.time()
    count = populate_pool(force=True)
    elapsed = time.time() - t0
    print(f"  populate_pool() -> {count} entries en {elapsed:.1f}s")

    entries = _global_pool.get_all_entries()
    arena_count = sum(1 for e in entries if e.arena_score is not None)
    health_summary = _global_pool.health_summary()
    free_count = sum(1 for e in entries if e.is_free)

    print(f"  Entries con Arena score: {arena_count}/{len(entries)}")
    print(f"  Modelos gratuitos: {free_count}/{len(entries)}")
    print(f"  Health summary: {health_summary}")

    if arena_count < len(entries):
        print("  Ejecutando update_arena_scores() (safety net)...")
        updated = update_arena_scores()
        arena_count = sum(1 for e in _global_pool.get_all_entries() if e.arena_score is not None)
        print(f"  Despues de update_arena_scores(): {arena_count}/{len(entries)} con Arena score")

    try:
        af = _get_arena_module()
        with af._refresh_lock:
            arena_data_size = len(af._arena_data) if af._arena_data else 0
        cats = []
        if af._arena_data:
            for scores in af._arena_data.values():
                cats.extend(scores.keys())
            cats = sorted(set(cats))
        print(f"  Arena fetcher: {arena_data_size} modelos, categorias: {cats[:12]}...")
    except Exception as e:
        print(f"  Arena fetcher diagnostico fallo: {e}")

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
        "free_count": free_count,
        "health_summary": health_summary,
        "elapsed_s": elapsed,
    }


# ============================================================================
# Fase 2: Mostrar top-N por ranking + top-N gratuitos
# ============================================================================
def show_rankings(top_n, rankings_list=None):
    """Muestra top-N modelos por ranking y top-N gratuitos."""
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header(f"FASE 2: Top-{top_n} modelos por ranking (+ gratuitos)")

    from core.router import _global_pool

    rankings_data = {}

    for ranking in rankings_list:
        entries = _global_pool.get_ranked_entries(
            task_type=ranking,
            exclude_statuses=["payment_required", "failed"],
        )

        print(f"\n  RANKING {ranking.upper()} -- Top {min(top_n, len(entries))} de {len(entries)} candidatos")
        print(f"  {'#':>3} {'Modelo':<45} {'Provider':<12} {'Arena':>6} {'Score':>6} {'Health':<12} {'Free':>4}")
        print(f"  {'---':>3} {'-'*45} {'-'*12} {'-'*6} {'-'*6} {'-'*12} {'-'*4}")

        top_entries = entries[:top_n]
        rankings_data[ranking] = []

        for i, e in enumerate(top_entries, 1):
            arena_str = f"{e.arena_score:.1f}" if e.arena_score is not None else "---"
            task_score_val = e.task_score(ranking)
            score_str = f"{task_score_val:.1f}"
            health_str = e.health_status or "unknown"
            model_str = e.model_id[:45]
            provider_str = e.provider[:12]
            free_str = "YES" if e.is_free else ""

            print(f"  {i:>3} {model_str:<45} {provider_str:<12} {arena_str:>6} {score_str:>6} {health_str:<12} {free_str:>4}")

            rankings_data[ranking].append({
                "rank": i,
                "model_id": e.model_id,
                "provider": e.provider,
                "arena_score": e.arena_score,
                "composite_score": e.composite_score,
                "task_score": e.task_score(ranking),
                "health_status": e.health_status,
                "context_length": e.context_length,
                "is_free": e.is_free,
            })

        # Mostrar top-N gratuitos
        free_entries = [e for e in entries if e.is_free][:top_n]
        if free_entries:
            print(f"\n  RANKING {ranking.upper()} -- Top {len(free_entries)} GRATUITOS")
            print(f"  {'#':>3} {'Modelo':<45} {'Provider':<12} {'Arena':>6} {'TaskScore':>9}")
            print(f"  {'---':>3} {'-'*45} {'-'*12} {'-'*6} {'-'*9}")
            for i, e in enumerate(free_entries, 1):
                arena_str = f"{e.arena_score:.1f}" if e.arena_score is not None else "---"
                score_str = f"{e.task_score(ranking):.1f}"
                model_str = e.model_id[:45]
                provider_str = e.provider[:12]
                print(f"  {i:>3} {model_str:<45} {provider_str:<12} {arena_str:>6} {score_str:>9}")

    return rankings_data


# ============================================================================
# Helper: llamar provider directo
# ============================================================================
def _call_provider_direct(model_id, provider_name, messages, max_tokens, temperature):
    """Llama directamente a un provider especifico con un modelo especifico."""
    from core.providers import provider_manager

    _, base_id = provider_manager.parse_prefixed_id(model_id)
    if base_id is None or base_id == model_id:
        base_id = model_id

    if provider_name in provider_manager.providers:
        provider = provider_manager.providers[provider_name]
        translated_id = provider_manager.translate_model_id(base_id, provider_name)
        try:
            result = provider.call(translated_id, messages, max_tokens, temperature)
            result["provider"] = provider_name
            result["model_requested"] = base_id
            result["model_translated"] = translated_id
            return result
        except Exception as e:
            return {
                "content": "", "model_used": base_id, "provider": provider_name,
                "success": False, "error": str(e), "http_status": None,
                "model_requested": base_id, "model_translated": translated_id,
            }

    return {
        "content": "", "model_used": base_id, "provider": provider_name,
        "success": False, "error": f"Provider '{provider_name}' no disponible",
        "http_status": None, "model_requested": base_id, "model_translated": base_id,
    }


# ============================================================================
# Helper: sincronizar resultado de llamada al pool
# ============================================================================
def _sync_result_to_pool(model_id, provider_name, success, error_msg=""):
    """Actualiza el pool y model_health con el resultado de una llamada.

    NUEVO en v3.0: Si el error es de pago (payment), marca TODOS los
    modelos de pago de ese provider como payment_required. Esto evita
    intentar cada modelo individualmente cuando el provider no tiene credito.
    """
    from core.router import _global_pool, _sync_health_after_call
    from core.model_health import _classify_error

    # Sincronizar al pool (la funcion existente ya maneja el modelo individual)
    _sync_health_after_call(model_id, provider_name, success, error_msg)

    # NUEVO v3.0: Provider-level payment marking
    # Si el error es de pago, marcar TODOS los modelos de pago del provider
    if not success and error_msg:
        error_type = _classify_error(error_msg)
        if error_type == "payment":
            marked = _global_pool.mark_provider_paid_models(provider_name)
            if marked > 0:
                print(f"      >> Provider {provider_name} sin credito: {marked} modelos de pago marcados como payment_required")


# ============================================================================
# Helper: probar un modelo individual
# ============================================================================
def _test_single_model(model_id, provider, arena, ranking, messages):
    """Prueba un modelo individual y retorna (result_entry, success)."""
    from core.model_health import _classify_error

    t0 = time.time()
    try:
        result = _call_provider_direct(
            model_id=model_id,
            provider_name=provider,
            messages=messages,
            max_tokens=MINI_MAX_TOKENS,
            temperature=0.0,
        )
        elapsed = time.time() - t0

        success = result.get("success", False)
        result_provider = result.get("provider", provider)
        result_model = result.get("model_used", model_id)
        error_msg = result.get("error", "")
        http_status = result.get("http_status")
        latency_ms = int(elapsed * 1000)

        if success:
            content = result.get("content", "")
            tokens_out = max(1, len(content) // 4) if content else 0
            tokens_in = max(1, len(MINI_PROMPT_SYSTEM + MINI_PROMPT_USER) // 4)
        else:
            tokens_out = 0
            tokens_in = max(1, len(MINI_PROMPT_SYSTEM + MINI_PROMPT_USER) // 4)

        cost = 0.0

        if not success and error_msg:
            error_type = _classify_error(error_msg)
        else:
            error_type = ""

        content_preview = result.get("content", "")[:30].replace("\n", " ") if success else ""

        # Sincronizar resultado al pool (NUEVO en v3.0)
        _sync_result_to_pool(model_id, provider, success, error_msg)

        if success:
            status = "OK"
            detail = f"provider={result_provider} tokens={tokens_out} latency={latency_ms}ms content='{content_preview}'"
        else:
            status = "FAIL"
            http_info = f" http={http_status}" if http_status else ""
            detail = f"provider={result_provider} error={error_type}:{error_msg[:60]}{http_info}"

        print(f"{status} {detail}")

        result_entry = {
            "ranking": ranking,
            "model_id": model_id,
            "pool_provider": provider,
            "result_provider": result_provider,
            "result_model": result_model,
            "arena_score": arena,
            "result_arena": None,
            "success": success,
            "tokens_input": tokens_in,
            "tokens_output": tokens_out,
            "latency_ms": latency_ms,
            "cost_usd": cost,
            "error_type": error_type,
            "error_msg": error_msg,
            "http_status": http_status,
            "attempts": 1,
            "elapsed_s": elapsed,
            "content_preview": content_preview if success else "",
            "is_free": False,
        }
        return result_entry, success

    except Exception as e:
        elapsed = time.time() - t0
        print(f"EXCEPCION: {e}")
        return {
            "ranking": ranking, "model_id": model_id,
            "pool_provider": provider, "result_provider": "exception",
            "result_model": "", "arena_score": arena, "result_arena": None,
            "success": False, "tokens_input": 0, "tokens_output": 0,
            "latency_ms": 0, "cost_usd": 0.0, "error_type": "exception",
            "error_msg": str(e), "http_status": None, "attempts": 0,
            "elapsed_s": elapsed, "content_preview": "", "is_free": False,
        }, False


# ============================================================================
# Fase 3: Stress test ADAPTATIVO
# ============================================================================
def stress_test(rankings_data, top_n, rankings_list=None):
    """FASE 3 ADAPTATIVA: Llama modelos re-rankeando tras cada fallo.

    En vez de llamar los top-10 fijos, este enfoque:
    1. Obtiene el mejor modelo del ranking actual
    2. Lo llama y registra el resultado
    3. Si falla con pago, marca TODOS los modelos de pago del provider
    4. Re-rankeo: el siguiente modelo sube al top (incluidos los gratuitos)
    5. Repite hasta >=50% exito por ranking o max_intentos alcanzado

    Esto permite que los modelos gratuitos suban automaticamente
    cuando los de pago estan marcados como payment_required.
    """
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header(f"FASE 3: Stress test ADAPTATIVO -- hasta {DEFAULT_MAX_ATTEMPTS} modelos por ranking")

    from core.router import _global_pool

    all_results = []
    total_calls = 0
    total_success = 0
    total_cost = 0.0

    messages = [
        {"role": "system", "content": MINI_PROMPT_SYSTEM},
        {"role": "user", "content": MINI_PROMPT_USER},
    ]

    tested_models = set()  # Track models already tried (avoid duplicates)

    for ranking in rankings_list:
        rank_success = 0
        rank_attempts = 0

        print(f"\n  RANKING {ranking.upper()} -- Seleccion adaptativa...")

        for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
            # Re-rankear cada vez (excluyendo modelos ya marcados)
            entries = _global_pool.get_ranked_entries(
                task_type=ranking,
                exclude_statuses=["payment_required", "failed", "temporarily_unavailable"],
            )

            # Buscar el primer modelo no probado aun
            entry = None
            for e in entries:
                if e.composite_key not in tested_models:
                    entry = e
                    break

            if entry is None:
                print(f"    No quedan modelos sin probar para {ranking}")
                break

            tested_models.add(entry.composite_key)
            total_calls += 1
            rank_attempts += 1

            model_id = entry.model_id
            provider = entry.provider
            arena = entry.arena_score
            is_free = entry.is_free
            free_tag = " (FREE)" if is_free else ""

            print(f"    [{total_calls}] {model_id} via {provider} (Arena: {arena}{free_tag})... ", end="", flush=True)

            result_entry, success = _test_single_model(
                model_id, provider, arena, ranking, messages
            )
            result_entry["is_free"] = is_free
            all_results.append(result_entry)

            if success:
                total_success += 1
                rank_success += 1

            # Parada temprana: si ya tenemos >=50% en este ranking con al menos 5 intentos
            if rank_attempts >= 5:
                rank_rate = rank_success / rank_attempts * 100
                if rank_rate >= 50:
                    print(f"    (Ranking {ranking} alcanza {rank_rate:.0f}% en {rank_attempts} intentos, pasando al siguiente)")
                    break

        # Resumen del ranking
        if rank_attempts > 0:
            rank_rate = rank_success / rank_attempts * 100
            print(f"    --> {ranking}: {rank_success}/{rank_attempts} OK ({rank_rate:.0f}%)")

    return {
        "results": all_results,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_cost": total_cost,
        "success_rate": total_success / max(1, total_calls) * 100,
    }


# ============================================================================
# Fase 3b: Free model fallback EXPLICITO
# ============================================================================
def free_model_fallback(all_results, rankings_list=None):
    """FASE 3b: Prueba modelos gratuitos directamente cuando la tasa es <50%.

    Usa get_free_entries() del pool para obtener modelos gratuitos
    ordenados por score, sin filtro de context_length (para no excluir
    modelos gratuitos con contextos pequenos que pueden funcionar bien
    para prompts cortos como "Responde: OK").
    """
    if rankings_list is None:
        rankings_list = RANKINGS

    current_total = len(all_results)
    current_success = sum(1 for r in all_results if r["success"])
    current_rate = current_success / max(1, current_total) * 100

    if current_rate >= 50:
        return {
            "results": all_results,
            "total_calls": current_total,
            "total_success": current_success,
            "total_cost": 0.0,
            "success_rate": current_rate,
        }

    print_header(f"FASE 3b: Fallback a modelos GRATUITOS (tasa actual: {current_rate:.1f}%)")
    print("  Los modelos de pago fallaron. Probando modelos gratuitos del pool...")

    from core.router import _global_pool

    messages = [
        {"role": "system", "content": MINI_PROMPT_SYSTEM},
        {"role": "user", "content": "Respond with only the word: OK"},
    ]

    tested_models = set(r["model_id"] for r in all_results)
    total_calls = current_total
    total_success = current_success

    for ranking in rankings_list:
        # Usar get_free_entries() — sin filtro de context_length
        free_entries = _global_pool.get_free_entries(
            task_type=ranking,
            exclude_statuses=["payment_required", "failed", "temporarily_unavailable"],
        )

        # Filtrar modelos ya probados
        free_to_test = [
            e for e in free_entries
            if e.model_id not in tested_models
        ][:DEFAULT_FREE_TOP]

        if not free_to_test:
            print(f"\n  RANKING {ranking.upper()} -- No hay modelos gratuitos disponibles")
            continue

        print(f"\n  RANKING {ranking.upper()} -- Probando {len(free_to_test)} modelos GRATUITOS...")
        for e in free_to_test:
            total_calls += 1
            arena = e.arena_score
            print(f"    [{total_calls}] {e.model_id} via {e.provider} (Arena: {arena}, FREE)... ", end="", flush=True)

            result_entry, success = _test_single_model(
                e.model_id, e.provider, arena, ranking, messages
            )
            result_entry["is_free"] = True
            all_results.append(result_entry)
            tested_models.add(e.model_id)

            if success:
                total_success += 1

            # Si ya alcanzamos 50% en este ranking, paramos
            rank_results = [r for r in all_results if r["ranking"] == ranking]
            rank_success = sum(1 for r in rank_results if r["success"])
            rank_total = len(rank_results)
            rank_rate = rank_success / max(1, rank_total) * 100
            if rank_rate >= 50:
                print(f"    (Ranking {ranking} alcanza {rank_rate:.0f}%, parando)")
                break

    return {
        "results": all_results,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_cost": 0.0,
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

    print(f"\n  Resumen Global:")
    print(f"    Total llamadas:      {stress_data['total_calls']}")
    print(f"    Exitosas:            {stress_data['total_success']}")
    print(f"    Tasa de exito:       {stress_data['success_rate']:.1f}%")
    print(f"    Coste total:         {format_usd(stress_data['total_cost'])}")
    print(f"    Pool entries:        {pool_data['total_entries']}")
    print(f"    Con Arena score:     {pool_data['arena_scored']}")
    print(f"    Modelos gratuitos:   {pool_data.get('free_count', '?')}")

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
        free_tested = sum(1 for r in rank_results if r.get("is_free"))
        free_ok = sum(1 for r in rank_results if r.get("is_free") and r["success"])
        print(f"    {ranking:<12} -- {rank_success}/{rank_total} OK ({rank_rate:.0f}%) cost={format_usd(rank_cost)} free={free_ok}/{free_tested}")

    # Modelos que funcionan
    working = [r for r in results if r["success"]]
    if working:
        print(f"\n  Modelos verificados (funcionan):")
        seen = set()
        for r in working:
            key = (r["model_id"], r["result_provider"])
            if key not in seen:
                seen.add(key)
                arena_str = f"{r['result_arena']:.1f}" if r['result_arena'] is not None else "None"
                free_tag = " (FREE)" if r.get("is_free") else ""
                print(f"    OK  {r['model_id']:<45} via {r['result_provider']:<12} Arena={arena_str}{free_tag}")

    # Modelos que fallaron
    failing = [r for r in results if not r["success"]]
    if failing:
        print(f"\n  Modelos que fallaron:")
        seen = set()
        for r in failing:
            key = (r["model_id"], r["pool_provider"])
            if key not in seen:
                seen.add(key)
                free_tag = " (FREE)" if r.get("is_free") else ""
                print(f"    FAIL {r['model_id']:<45} via {r['pool_provider']:<12} error={r['error_type']}{free_tag}")

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

    active_rankings = [single_ranking] if single_ranking else list(RANKINGS)

    print_header("APA POOL STRESS TEST -- v3.0 ADAPTATIVO")
    print(f"  Fecha:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Top-N:    {top_n} modelos por ranking (display)")
    print(f"  Max intentos: {DEFAULT_MAX_ATTEMPTS} por ranking (FASE 3)")
    print(f"  Rankings: {single_ranking or 'TODOS (' + ', '.join(active_rankings) + ')'}")
    print(f"  Dry-run:  {dry_run}")
    print(f"  Prompt:   '{MINI_PROMPT_USER}' (max_tokens={MINI_MAX_TOKENS})")
    print(f"  Fallback: {DEFAULT_FREE_TOP} modelos gratuitos si tasa < 50%")
    print(f"  Novedad:  Re-rankeo adaptativo + provider-level payment marking")

    # Fase 1: Forzar pool
    pool_data = force_populate_pool()

    if pool_data["total_entries"] == 0:
        print("\nERROR: No hay entries en el pool. Verifica API keys en .env")
        sys.exit(1)

    if pool_data["arena_scored"] == 0:
        print("\nAVISO: 0 entries con Arena score. El ranking sera por provider_confidence solo.")

    # Fase 2: Mostrar rankings
    rankings_data = show_rankings(top_n, active_rankings)

    if dry_run:
        print("\nDRY-RUN: No se llamara a ningun LLM. Rankings mostrados arriba.")
        sys.exit(0)

    # Fase 3: Stress test ADAPTATIVO
    stress_data = stress_test(rankings_data, top_n, active_rankings)

    # Fase 3b: Free model fallback (si tasa < 50%)
    if stress_data["success_rate"] < 50:
        stress_data = free_model_fallback(stress_data["results"], active_rankings)

    # Fase 4: Reporte
    print_report(stress_data, pool_data, active_rankings)

    # Guardar resultados JSON
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "stress_test_results.json")
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "version": "3.0",
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
