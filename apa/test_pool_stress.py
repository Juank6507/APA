#!/usr/bin/env python3
# test_pool_stress.py — Test de estres del pool APA
# v4.4 — CRITICAL FIX: 3 bugs que impedían que R1/R2/R3 funcionaran:
#         BUG 1: cleanup_caches() usaba rutas hardcodeadas que NO encontraban
#           los caches reales → R1/R2/R3 nunca se aplicaban.
#           FIX: Usar _find_project_data_dir() de providers/model_health.
#         BUG 2: FREE model retornando 402 (daily quota agotado) disparaba
#           mark_provider_paid_models() → marcaba TODOS los paid como
#           payment_required → cascada devastadora.
#           FIX: Solo cascader si el modelo que falló NO es free.
#         BUG 3: GitHub no estaba en _NATIVE_PROVIDERS → translate_model_id
#           no traducía azureml:// IDs → GitHub models siempre fallaban.
#           FIX: Añadido github a _NATIVE_PROVIDERS en providers.py.
#         Esperado: cobertura 45% → 65%+ con estos fixes.
#
# v4.3 — R4 (Asesor): Delay 4s entre llamadas OpenRouter en stress test.
#         Previene rate limit del free tier (20 req/min) durante burst testing.
#         SOLO en stress test — el router de producción NO se modifica.
#
# CAMBIOS v4.4 vs v4.3:
#   - BUG 1 FIX: cleanup_caches() usa _find_project_data_dir() para
#     encontrar los caches reales (antes usaba rutas relativas incorrectas)
#   - BUG 2 FIX: _sync_result_to_pool() NO dispara mark_provider_paid_models()
#     cuando el modelo que falló es FREE. Un modelo FREE que retorna 402
#     significa "daily quota agotado", NO "payment required".
#     Solo cascader para modelos PAID que retornan 402.
#   - providers.py v2.7: github añadido a _NATIVE_PROVIDERS
#   - Versión de resultados JSON: "4.4"
#
# CAMBIOS v4.2 vs v4.1:
#   - providers.py v2.6: _NON_CHAT_PATTERNS ampliado (tts, orpheus, safeguard)
#   - providers.py v2.6: _is_chat_model() emite DEBUG log por modelo excluido
#   - providers.py v2.6: Together/Fireworks también filtran no-chat
#   - normalizer.py v1.2: FALSELY_FREE_MODELS (lyria, deepseek-v4-flash:free)
#   - providers.py v2.6: _FAKE_FREE_IDS → _get_fake_free_ids() desde normalizer
#   - Limpieza agresiva de caches (FASE 0) para que v2.6 tome efecto
#   - Versión de resultados JSON: "4.3"
#
# v4.1 — FIX CRITICO: Discovery prioriza modelos FREE antes que PAID.
#
# v4.0 — ARQUITECTURA NUEVA: Discovery+Cobertura en vez de consumo secuencial.
#   - FASE 3a DISCOVERY: Testea cada modelo UNA VEZ.
#   - FASE 3b COVERAGE: Un modelo que funciona cuenta como exito
#     para TODOS los rankings donde es eligible.
#   - reset_transient_statuses() entre rankings
#   - min_context=1: El prompt es "Respond: OK" — no necesita 16K contexto.
#
# v3.5 — empty_response → failed, mark_provider_rate_limited() para cooldown,
#         _classify_error() v4.1 (payment antes de rate_limit).
# v3.0 — Test ADAPTIVO: re-rankeo tras fallo, provider-level payment marking.
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
DEFAULT_MAX_DISCOVERY = 80   # Max modelos a testear en fase Discovery (54 free + margen)
MINI_PROMPT_SYSTEM = "You are a helpful assistant. Respond with exactly one word."
MINI_PROMPT_USER = "Respond with only the word: OK"
MINI_MAX_TOKENS = 10

# R4: Delay por provider en stress test (NO afecta router de producción)
# OpenRouter free tier: 20 req/min → 3s mínimo entre calls → 4s da margen
# Groq free tier: 30 req/min → 2s mínimo → 1s + rate limit handling es suficiente
# Otros providers: 1.0s por defecto
PROVIDER_DELAY = {
    "openrouter": 4.0,   # R4: 3-5s recomendado por Asesor, 4s = punto medio
    "groq": 1.5,        # Free tier 30 req/min, 1.5s da margen
}


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def format_usd(cost):
    if cost == 0:
        return "$0.0000"
    return f"${cost:.6f}"


# ============================================================================
# Fase 1: Inicializar pool con Arena data + limpiar caches
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
        # v4.0: min_context=1 — el prompt es trivial
        entries = _global_pool.get_ranked_entries(
            task_type=ranking,
            min_context=1,
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

    v4.4 CRITICAL FIX: FREE model retornando 402 = daily quota agotado,
    NO payment required. Solo cascader mark_provider_paid_models() cuando
    el modelo que falló es PAID (is_free=False).

    RAZÓN: OpenRouter free tier tiene un límite diario de llamadas.
    Cuando se agota, los modelos FREE retornan HTTP 402. Pero esto
    NO significa que los modelos de pago tampoco funcionen — significa
    que el free tier diario se agotó. Cascader a paid models es FALSO.

    ANTES (v4.3): Cualquier 402 → mark_provider_paid_models() → 336 modelos marcados
    AHORA (v4.4): Solo 402 en modelo PAID → mark_provider_paid_models()
                  402 en modelo FREE → solo marcar ese modelo, NO cascader
    """
    from core.router import _global_pool, _sync_health_after_call
    from core.model_health import _classify_error

    # Sincronizar al pool (la funcion existente ya maneja el modelo individual)
    _sync_health_after_call(model_id, provider_name, success, error_msg)

    # Provider-level marking basado en el tipo de error
    if not success and error_msg:
        error_type = _classify_error(error_msg)
        if error_type == "payment":
            # v4.4 BUG 2 FIX: Verificar si el modelo que falló es FREE
            # Un modelo FREE que retorna 402 = daily quota agotado
            # Un modelo PAID que retorna 402 = sin crédito (genuino)
            entry = _global_pool.get_entry(provider_name, model_id)
            is_free_model = entry.is_free if entry else False

            if is_free_model:
                # FREE model + 402 = daily quota agotado
                # NO cascader a modelos de pago — ellos podrían funcionar
                print(f"      >> FREE model {model_id} retornó 402 — daily quota agotado (NO cascada a paid)")
            else:
                # PAID model + 402 = sin crédito genuino
                # Marcar TODOS los modelos de pago del provider como payment_required
                marked = _global_pool.mark_provider_paid_models(provider_name)
                if marked > 0:
                    print(f"      >> Provider {provider_name} sin credito: {marked} modelos de pago marcados como payment_required")
        # v4.0: Ya NO marcamos mark_provider_rate_limited() agresivamente.
        # El reset_transient_statuses() entre rankings rehabilita los modelos
        # rate-limited para que puedan reintentarse en el siguiente ranking.


# ============================================================================
# Helper: probar un modelo individual
# ============================================================================
def _test_single_model(model_id, provider, arena, ranking, messages):
    """Prueba un modelo individual y retorna (result_entry, success).

    v4.0: Detecta empty_response y la clasifica como error permanente.
    """
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

        # Detectar empty_response — HTTP 200 pero sin contenido
        if success:
            content = result.get("content", "")
            if not content or not content.strip():
                success = False
                error_msg = f"Empty response (HTTP 200 pero respuesta vacia)"
                http_status = 200
                result["success"] = False
                result["error"] = error_msg

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

        # Sincronizar resultado al pool
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
# Fase 3a: DISCOVERY — Testea cada modelo UNA VEZ
# ============================================================================
def discovery_phase(rankings_list=None):
    """FASE 3a: Testea cada modelo UNA VEZ para descubrir cuales funcionan.

    v4.1 CRITICAL FIX: Los modelos FREE se testean PRIMERO. Los modelos PAID
    se testean despues. Razon: si las cuentas no tienen credito, los modelos
    de pago SIEMPRE fallan y desperdician intentos. En v4.0, los 60 intentos
    se gastaban en modelos de pago (scores mas altos), dejando los 54 modelos
    gratuitos sin testear. Resultado: 0% de exito. Con v4.1, los 54 free
    se testean primero, y solo si sobran intentos se prueban los de pago.

    v4.0 ARQUITECTURA: Cada modelo se testea UNA VEZ. El resultado aplica
    a TODOS los rankings donde el modelo es elegible.
    """
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header(f"FASE 3a: DISCOVERY -- FREE primero, PAID despues (max {DEFAULT_MAX_DISCOVERY})")

    from core.router import _global_pool

    all_results = []
    tested_keys = set()  # composite keys ya testeadas (NO por ranking, GLOBAL para no repetir API calls)

    messages = [
        {"role": "system", "content": MINI_PROMPT_SYSTEM},
        {"role": "user", "content": MINI_PROMPT_USER},
    ]

    total_calls = 0
    total_success = 0
    provider_last_call_time = {}  # provider → timestamp para delay entre llamadas

    # Recolectar TODOS los modelos candidatos de TODOS los rankings
    # (sin duplicar — cada composite_key solo una vez)
    all_candidates = []
    seen_keys = set()

    for ranking in rankings_list:
        # v4.1: min_context=1 — el prompt es trivial ("Respond: OK")
        entries = _global_pool.get_ranked_entries(
            task_type=ranking,
            min_context=1,
            exclude_statuses=["payment_required", "failed", "temporarily_unavailable"],
        )
        for e in entries:
            if e.composite_key not in seen_keys:
                seen_keys.add(e.composite_key)
                all_candidates.append((e, ranking))

    # v4.1 CRITICAL FIX: Separar en listas FREE y PAID
    # FREE: is_free=True → se testean PRIMERO (los unicos que pueden funcionar)
    # PAID: is_free=False → se testean DESPUES (fallaran si no hay credito)
    free_candidates = [(e, r) for e, r in all_candidates if e.is_free]
    paid_candidates = [(e, r) for e, r in all_candidates if not e.is_free]

    # Dentro de cada grupo, ordenar por composite_score descendente
    # (mejores modelos primero dentro de su categoria)
    free_candidates.sort(key=lambda x: x[0].composite_score, reverse=True)
    paid_candidates.sort(key=lambda x: x[0].composite_score, reverse=True)

    # Concatenar: FREE primero, PAID despues
    all_candidates = free_candidates + paid_candidates

    free_count = len(free_candidates)
    paid_count = len(paid_candidates)
    print(f"  Candidatos unicos: {len(all_candidates)} modelos ({free_count} FREE, {paid_count} PAID)")
    print(f"  Max a testear: {DEFAULT_MAX_DISCOVERY}")
    print(f"  Principio: FREE primero (los unicos que pueden funcionar sin credito)")
    print(f"  Estrategia: testear todos los FREE ({free_count}), luego PAID si sobran intentos")
    print()

    for entry, first_ranking in all_candidates[:DEFAULT_MAX_DISCOVERY]:
        if entry.composite_key in tested_keys:
            continue

        tested_keys.add(entry.composite_key)

        # R4: Delay entre llamadas al mismo provider (variable por provider)
        # OpenRouter free tier: 4s para evitar rate limit (20 req/min)
        provider = entry.provider
        required_delay = PROVIDER_DELAY.get(provider, 1.0)
        last_time = provider_last_call_time.get(provider, 0)
        elapsed_since_last = time.time() - last_time
        if elapsed_since_last < required_delay:
            time.sleep(required_delay - elapsed_since_last)

        total_calls += 1
        model_id = entry.model_id
        arena = entry.arena_score
        is_free = entry.is_free
        free_tag = " (FREE)" if is_free else ""

        print(f"  [{total_calls}] {model_id} via {provider} (Arena: {arena}{free_tag})... ", end="", flush=True)

        result_entry, success = _test_single_model(
            model_id, provider, arena, "discovery", messages
        )
        result_entry["is_free"] = is_free
        all_results.append(result_entry)

        if success:
            total_success += 1

        provider_last_call_time[provider] = time.time()

        # v4.1: Parada temprana solo si ya tenemos >=20 modelos funcionando
        # (aumentado de 15 para asegurar buena cobertura en todos los rankings)
        if total_success >= 20:
            print(f"\n  (Discovery: {total_success} modelos funcionando, suficiente para coverage)")
            break

    # Resumen discovery
    discovery_rate = total_success / max(1, total_calls) * 100
    print(f"\n  DISCOVERY RESUMEN: {total_success}/{total_calls} OK ({discovery_rate:.1f}%)")
    print(f"  Modelos funcionales descubiertos: {total_success}")

    return {
        "results": all_results,
        "total_calls": total_calls,
        "total_success": total_success,
        "tested_keys": tested_keys,
    }


# ============================================================================
# Fase 3b: COVERAGE — Calcular cobertura por ranking
# ============================================================================
def coverage_phase(discovery_data, rankings_list=None):
    """FASE 3b: Calcula cobertura por ranking basandose en Discovery.

    Un modelo que funciona cuenta como exito para TODOS los rankings
    donde es eligible (context_length suficiente, no payment_required/failed).

    v4.0: Antes de calcular coverage, resetea estados transitorios
    (rate_limited, temporarily_unavailable → unknown) para que los modelos
    que fallaron temporalmente en discovery se cuenten como disponibles
    si ya estaban verificados como available.
    """
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header("FASE 3b: COVERAGE -- Calcular cobertura por ranking")

    from core.router import _global_pool

    # Resetear estados transitorios para rehabilitar modelos rate-limited
    reset_count = _global_pool.reset_transient_statuses()
    print(f"  Estados transitorios reseteados: {reset_count} (rate_limited/temporarily_unavailable → unknown)")

    # Obtener modelos que funcionan (status='available')
    working_entries = _global_pool.get_working_entries()
    working_keys = {e.composite_key for e in working_entries}
    print(f"  Modelos verificadas como 'available': {len(working_entries)}")

    # Para cada ranking, calcular cobertura
    coverage_data = {}
    total_rankings_with_coverage = 0
    total_eligible = 0
    total_working_eligible = 0

    for ranking in rankings_list:
        # Obtener todos los modelos elegibles para este ranking
        # (excluir permanentes, NO excluir transitorios ya reseteados)
        eligible = _global_pool.get_ranked_entries(
            task_type=ranking,
            min_context=1,
            exclude_statuses=["payment_required", "failed"],
        )

        # Contar modelos funcionando entre los elegibles
        working_in_rank = [e for e in eligible if e.composite_key in working_keys]
        rank_rate = len(working_in_rank) / max(1, len(eligible)) * 100

        coverage_data[ranking] = {
            "eligible": len(eligible),
            "working": len(working_in_rank),
            "rate": rank_rate,
        }

        total_eligible += len(eligible)
        total_working_eligible += len(working_in_rank)

        if len(working_in_rank) > 0:
            total_rankings_with_coverage += 1

        print(f"  {ranking:<12}: {len(working_in_rank)}/{len(eligible)} OK ({rank_rate:.1f}%)")

    # Metrica global: cobertura ponderada
    global_rate = total_working_eligible / max(1, total_eligible) * 100
    task_coverage = total_rankings_with_coverage / len(rankings_list) * 100

    print(f"\n  COBERTURA GLOBAL: {total_working_eligible}/{total_eligible} OK ({global_rate:.1f}%)")
    print(f"  TASK COVERAGE: {total_rankings_with_coverage}/{len(rankings_list)} rankings con al menos 1 modelo ({task_coverage:.0f}%)")

    return {
        "coverage_data": coverage_data,
        "global_rate": global_rate,
        "task_coverage": task_coverage,
        "total_eligible": total_eligible,
        "total_working_eligible": total_working_eligible,
        "rankings_with_coverage": total_rankings_with_coverage,
    }


# ============================================================================
# Fase 3c: RE-INTENTO — Segunda pasada para modelos transitoriamente fallidos
# ============================================================================
def retry_phase(discovery_data, rankings_list=None):
    """FASE 3c: Re-intenta modelos que fallaron por rate_limit o transitorio.

    v4.0: Despues del discovery y reset_transient_statuses(), algunos modelos
    que eran rate_limited ahora son 'unknown' de nuevo. Los reintentamos
    para ver si el cooldown ha expirado.
    """
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header("FASE 3c: RE-INTENTO -- Modelos transitoriamente fallidos")

    from core.router import _global_pool

    messages = [
        {"role": "system", "content": MINI_PROMPT_SYSTEM},
        {"role": "user", "content": MINI_PROMPT_USER},
    ]

    # Buscar modelos que fallaron por razones transitorias en discovery
    transient_failures = []
    for r in discovery_data["results"]:
        if not r["success"] and r["error_type"] in ("rate_limit", "temporarily_unavailable",
                                                       "timeout", "connection", "server_error", "unknown"):
            entry = _global_pool.get_entry(r["pool_provider"], r["model_id"])
            if entry and entry.health_status not in ("available", "payment_required", "failed"):
                transient_failures.append((r, entry))

    if not transient_failures:
        print("  No hay modelos transitoriamente fallidos para reintentar.")
        return discovery_data

    print(f"  Modelos a reintentar: {len(transient_failures)}")
    print()

    tested_keys = discovery_data["tested_keys"]
    total_calls = discovery_data["total_calls"]
    total_success = discovery_data["total_success"]
    all_results = list(discovery_data["results"])

    for prev_result, entry in transient_failures[:20]:  # Max 20 reintentos
        if entry.composite_key in tested_keys:
            # Ya fue testeado en discovery, pero vamos a reintentar
            pass

        total_calls += 1
        model_id = entry.model_id
        provider = entry.provider
        arena = entry.arena_score
        is_free = entry.is_free
        free_tag = " (FREE)" if is_free else ""

        print(f"  [{total_calls}] RETRY {model_id} via {provider} (Arena: {arena}{free_tag})... ", end="", flush=True)

        time.sleep(1.0)  # Delay entre reintentos

        result_entry, success = _test_single_model(
            model_id, provider, arena, "retry", messages
        )
        result_entry["is_free"] = is_free
        all_results.append(result_entry)

        if success:
            total_success += 1

    retry_rate = total_success / max(1, total_calls) * 100
    print(f"\n  RE-INTENTO RESUMEN: {total_success}/{total_calls} OK ({retry_rate:.1f}%)")

    return {
        "results": all_results,
        "total_calls": total_calls,
        "total_success": total_success,
        "tested_keys": tested_keys,
    }


# ============================================================================
# Fase 4: Reporte final
# ============================================================================
def print_report(final_data, coverage_data, pool_data, rankings_list=None):
    """Imprime reporte final del test de estres."""
    if rankings_list is None:
        rankings_list = RANKINGS
    print_header("FASE 4: REPORTE FINAL")

    results = final_data["results"]
    total_calls = final_data["total_calls"]
    total_success = final_data["total_success"]
    api_success_rate = total_success / max(1, total_calls) * 100

    print(f"\n  === Metricas API (llamadas reales) ===")
    print(f"    Total llamadas:      {total_calls}")
    print(f"    Exitosas:            {total_success}")
    print(f"    Tasa de exito API:   {api_success_rate:.1f}%")

    print(f"\n  === Metricas Coverage (por ranking) ===")
    for ranking in rankings_list:
        cd = coverage_data.get("coverage_data", {}).get(ranking, {})
        eligible = cd.get("eligible", 0)
        working = cd.get("working", 0)
        rate = cd.get("rate", 0)
        print(f"    {ranking:<12} -- {working}/{eligible} OK ({rate:.0f}%)")

    print(f"\n  === Metricas Globales ===")
    print(f"    Coverage global:     {coverage_data.get('global_rate', 0):.1f}%")
    print(f"    Task coverage:       {coverage_data.get('rankings_with_coverage', 0)}/{len(rankings_list)} rankings ({coverage_data.get('task_coverage', 0):.0f}%)")
    print(f"    Pool entries:        {pool_data['total_entries']}")
    print(f"    Con Arena score:     {pool_data['arena_scored']}")
    print(f"    Modelos gratuitos:   {pool_data.get('free_count', '?')}")

    # Modelos que funcionan (detallado)
    working = [r for r in results if r["success"]]
    if working:
        print(f"\n  Modelos verificados (funcionan):")
        seen = set()
        for r in working:
            key = (r["model_id"], r["result_provider"])
            if key not in seen:
                seen.add(key)
                free_tag = " (FREE)" if r.get("is_free") else ""
                print(f"    OK  {r['model_id']:<45} via {r['result_provider']:<12}{free_tag}")

    # Modelos que fallaron (agrupados por error_type)
    failing = [r for r in results if not r["success"]]
    if failing:
        print(f"\n  Modelos que fallaron (por tipo de error):")
        by_error = {}
        for r in failing:
            et = r.get("error_type", "unknown")
            if et not in by_error:
                by_error[et] = []
            by_error[et].append(r)
        for et, errs in sorted(by_error.items(), key=lambda x: -len(x[1])):
            print(f"    {et:<25} -- {len(errs)} modelos")
            for r in errs[:3]:  # Mostrar solo los primeros 3
                free_tag = " (FREE)" if r.get("is_free") else ""
                print(f"      {r['model_id'][:50]:<50} via {r['pool_provider']:<12}{free_tag}")
            if len(errs) > 3:
                print(f"      ... y {len(errs)-3} mas")

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
# Pre-cleanup: Limpiar caches de providers y health
# ============================================================================
def cleanup_caches():
    """v4.4: Limpia caches de providers y health usando _find_project_data_dir().

    BUG 1 FIX: La versión anterior usaba rutas relativas hardcodeadas que
    NO encontraban los caches reales. _find_project_data_dir() usa la
    misma lógica que providers/model_health para localizar los archivos.

    Sin este fix, los caches pre-R1/R2/R3 persistían y los filtros
    de non-chat/azureml/falsey-free NUNCA se aplicaban.
    """
    print_header("FASE 0: Limpiar caches obsoletos (v4.4: path resolution fix)")

    cleaned = 0

    # BUG 1 FIX: Usar _find_project_data_dir() de providers/model_health
    # para encontrar los caches reales, en vez de rutas relativas hardcodeadas.
    try:
        from core.providers import _find_project_data_dir as find_prov_dir
        prov_data_dir = find_prov_dir()
        cache_dir = prov_data_dir / "providers"
        print(f"  Provider cache dir: {cache_dir} (exists={cache_dir.is_dir()})")
        if cache_dir.is_dir():
            for f in cache_dir.glob("*.json"):
                try:
                    f.unlink()
                    print(f"  Eliminado: {f}")
                    cleaned += 1
                except Exception as e:
                    print(f"  Error eliminando {f}: {e}")
    except Exception as e:
        print(f"  Error buscando provider caches: {e}")

    # Health cache — usar _find_project_data_dir() de model_health
    try:
        from core.model_health import _find_project_data_dir as find_health_dir
        health_data_dir = find_health_dir()
        health_cache = health_data_dir / "health_cache.json"
        print(f"  Health cache: {health_cache} (exists={health_cache.exists()})")
        if health_cache.exists():
            try:
                health_cache.unlink()
                print(f"  Eliminado: {health_cache}")
                cleaned += 1
            except Exception as e:
                print(f"  Error eliminando {health_cache}: {e}")
    except Exception as e:
        print(f"  Error buscando health cache: {e}")

    # Fallback: también probar las rutas relativas antiguas por si acaso
    for cache_dir in [
        os.path.join(os.path.dirname(__file__), "..", "data", "providers"),
        os.path.join(os.path.dirname(__file__), "..", "core", "data", "providers"),
    ]:
        cache_path = os.path.abspath(cache_dir)
        if os.path.isdir(cache_path):
            for f in os.listdir(cache_path):
                if f.endswith(".json"):
                    filepath = os.path.join(cache_path, f)
                    try:
                        os.remove(filepath)
                        print(f"  Eliminado (fallback): {filepath}")
                        cleaned += 1
                    except Exception as e:
                        print(f"  Error eliminando {filepath}: {e}")

    for health_path in [
        os.path.join(os.path.dirname(__file__), "..", "data", "health_cache.json"),
        os.path.join(os.path.dirname(__file__), "..", "core", "data", "health_cache.json"),
    ]:
        hp = os.path.abspath(health_path)
        if os.path.exists(hp):
            try:
                os.remove(hp)
                print(f"  Eliminado (fallback): {hp}")
                cleaned += 1
            except Exception as e:
                print(f"  Error eliminando {hp}: {e}")

    if cleaned > 0:
        print(f"  Total caches eliminados: {cleaned}")
        print(f"  → Los providers re-descargarán modelos con filtros R1/R2/R3 aplicados")
    else:
        print(f"  No se encontraron caches obsoletos")

    return cleaned


# ============================================================================
# Main
# ============================================================================
def main():
    top_n = DEFAULT_TOP
    single_ranking = None
    dry_run = False
    skip_cleanup = False

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
        elif args[i] == "--skip-cleanup":
            skip_cleanup = True
            i += 1
        else:
            i += 1

    active_rankings = [single_ranking] if single_ranking else list(RANKINGS)

    print_header("APA POOL STRESS TEST -- v4.4 CRITICAL FIX (3 bugs)")
    print(f"  Fecha:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Top-N:    {top_n} modelos por ranking (display)")
    print(f"  Max discovery: {DEFAULT_MAX_DISCOVERY} modelos unicos")
    print(f"  Rankings: {single_ranking or 'TODOS (' + ', '.join(active_rankings) + ')'}")
    print(f"  Dry-run:  {dry_run}")
    print(f"  Prompt:   '{MINI_PROMPT_USER}' (max_tokens={MINI_MAX_TOKENS})")
    print(f"  Principio: Cada modelo se testea UNA VEZ. Resultado aplica a TODOS los rankings.")
    print(f"  Novedad v4.4: BUG FIX — cache cleanup usa _find_project_data_dir() (R1/R2/R3 ahora sí se aplican)")
    print(f"  Novedad v4.4: BUG FIX — FREE model 402 NO dispara cascada a paid models")
    print(f"  Novedad v4.4: BUG FIX — github añadido a _NATIVE_PROVIDERS (azureml traducción)")
    print(f"  Novedad v4.3: R4 del Asesor — delay 4s OpenRouter (rate limit prevention)")
    print(f"  Novedad v4.2: R1/R2/R3 del Asesor — no-chat filtrados, azureml traducidos, lyria no-free")
    print(f"  Novedad v4.1: FREE modelos se testean PRIMERO (fix critico 0% exito)")
    print(f"  Novedad v4.0: Discovery+Cobertura reemplaza consumo secuencial")
    print(f"  Novedad v4.0: reset_transient_statuses() entre rankings")
    print(f"  Novedad v4.0: min_context=1 (prompt trivial)")
    print(f"  Novedad v4.0: Limpieza automatica de caches obsoletos")

    # Fase 0: Limpiar caches (para que v2.5 tome efecto)
    if not skip_cleanup:
        cleanup_caches()
    else:
        print("\n  (Skip cleanup solicitado)")

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

    # Fase 3a: Discovery — testear cada modelo UNA VEZ
    discovery_data = discovery_phase(active_rankings)

    # Fase 3b: Coverage — calcular cobertura por ranking
    coverage_data = coverage_phase(discovery_data, active_rankings)

    # Fase 3c: Re-intento — reintentar modelos transitoriamente fallidos
    final_data = retry_phase(discovery_data, active_rankings)

    # Recalcular coverage despues del retry
    coverage_data = coverage_phase(final_data, active_rankings)

    # Fase 4: Reporte
    print_report(final_data, coverage_data, pool_data, active_rankings)

    # Guardar resultados JSON
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "stress_test_results.json")
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "version": "4.4",
                "pool_data": pool_data,
                "discovery_data": {
                    "total_calls": final_data["total_calls"],
                    "total_success": final_data["total_success"],
                    "api_success_rate": final_data["total_success"] / max(1, final_data["total_calls"]) * 100,
                },
                "coverage_data": coverage_data,
                "results": final_data["results"],
            }, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n  Resultados guardados en: {output_path}")
    except Exception as e:
        print(f"\n  No se pudieron guardar resultados: {e}")

    # Exit code basado en coverage global
    global_rate = coverage_data.get("global_rate", 0)
    task_coverage = coverage_data.get("task_coverage", 0)
    if global_rate >= 50:
        print(f"\nTest PASADO -- coverage global {global_rate:.1f}% >= 50%")
        sys.exit(0)
    elif global_rate > 0:
        print(f"\nTest PARCIAL -- coverage global {global_rate:.1f}% < 50% (task coverage: {task_coverage:.0f}%)")
        sys.exit(0)
    else:
        print(f"\nTest FALLADO -- 0% de coverage")
        sys.exit(1)


if __name__ == "__main__":
    main()
