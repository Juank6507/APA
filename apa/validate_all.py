# apa/validate_all.py
# v1.0 — Sprint 1: Validación maestra de todos los módulos
#
# Ejecuta las validaciones autocontenidas de cada módulo de Sprint 1:
#   1. pool.py          (8 tests — P-1, P-2, P-3, D-1/D-2, D-3/D-4, D-5)
#   2. providers.py     (4 tests — P-2 confidence_score)
#   3. model_health.py  (9 tests — D-3/D-4/D-5 response-code scheduling)
#   4. arena_fetcher.py (5 tests — D-8/D-10 cache-first non-blocking)
#   5. router.py        (5 tests — select_model_entry, D-1/D-2)
#   6. settings.py      (4 tests — configuración)
#
# Uso: python -m validate_all   (desde apa/)
#      python validate_all.py   (desde apa/)

import sys
import os
import time
import logging

# Asegurar que estamos en el directorio correcto
_base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base_dir)
os.chdir(_base_dir)

logging.basicConfig(level=logging.WARNING)

# ============================================================================
# Resultados globales
# ============================================================================
_all_results = []


def _record(module: str, name: str, passed: bool) -> None:
    _all_results.append((module, name, passed))


def _run_module(module_name: str, test_fn) -> int:
    """Ejecuta los tests de un módulo y retorna el número de FAILs."""
    fails = 0
    try:
        results = test_fn()
        for name, passed in results:
            _record(module_name, name, passed)
            if not passed:
                fails += 1
    except Exception as e:
        _record(module_name, f"MODULE_LOAD_ERROR: {e}", False)
        fails += 1
    return fails


# ============================================================================
# 1. pool.py — 8 tests
# ============================================================================
def _test_pool():
    from core.pool import Pool, PoolEntry
    results = []
    test_pool = Pool()

    # T1: Composite key (P-1)
    try:
        e1 = PoolEntry(provider="openrouter", model_id="anthropic/claude-opus-4-6")
        e2 = PoolEntry(provider="anthropic", model_id="claude-opus-4-6")
        assert e1.composite_key != e2.composite_key
        results.append(("P1: Composite key (provider, model_id)", True))
    except:
        results.append(("P1: Composite key (provider, model_id)", False))

    # T2: 3-Layer Ranking (P-3)
    try:
        e = PoolEntry(provider="openrouter", model_id="test", arena_score=80.0, provider_confidence=60.0)
        assert e.composite_score == 72.0
        e.apa_score = 95.0
        assert e.composite_score == 95.0
        results.append(("P3: 3-Layer Ranking", True))
    except:
        results.append(("P3: 3-Layer Ranking", False))

    # T3: Health ops — available no overwrite (D-3/D-4)
    try:
        test_pool.add_entry(PoolEntry(provider="groq", model_id="llama3"))
        test_pool.mark_available("groq", "llama3")
        test_pool.mark_rate_limited("groq", "llama3")
        e = test_pool.get_entry("groq", "llama3")
        assert e.health_status == "available"
        results.append(("D3/D4: available no overwrite", True))
    except:
        results.append(("D3/D4: available no overwrite", False))

    # T4: payment_required (D-5)
    try:
        test_pool.add_entry(PoolEntry(provider="or", model_id="paid"))
        test_pool.mark_payment_required("or", "paid")
        assert test_pool.get_entry("or", "paid").health_status == "payment_required"
        results.append(("D5: payment_required status", True))
    except:
        results.append(("D5: payment_required status", False))

    # T5: No free_first bias (D-1/D-2)
    try:
        p = Pool()
        p.add_entry(PoolEntry(provider="or", model_id="free", is_free=True, arena_score=50.0))
        p.add_entry(PoolEntry(provider="or", model_id="paid", is_free=False, arena_score=90.0))
        ranked = p.get_ranked_entries()
        assert ranked[0].model_id == "paid"
        results.append(("D1/D2: No free_first bias", True))
    except:
        results.append(("D1/D2: No free_first bias", False))

    # T6: Provider Confidence (P-2)
    try:
        p = Pool()
        p.add_entry(PoolEntry(provider="groq", model_id="a", provider_confidence=50.0))
        p.add_entry(PoolEntry(provider="groq", model_id="b", provider_confidence=50.0))
        p.add_entry(PoolEntry(provider="or", model_id="c", provider_confidence=50.0))
        p.set_provider_confidence("groq", 85.0)
        assert p.get_entry("groq", "a").provider_confidence == 85.0
        assert p.get_entry("or", "c").provider_confidence == 50.0
        results.append(("P2: Provider Confidence", True))
    except:
        results.append(("P2: Provider Confidence", False))

    # T7: Ranking con filtros
    try:
        p = Pool()
        p.add_entry(PoolEntry(provider="or", model_id="small", context_length=4000, arena_score=90.0))
        p.add_entry(PoolEntry(provider="or", model_id="big", context_length=128000, arena_score=80.0))
        ranked = p.get_ranked_entries(min_context=8000)
        assert len(ranked) == 1 and ranked[0].model_id == "big"
        results.append(("Ranking con filtros", True))
    except:
        results.append(("Ranking con filtros", False))

    # T8: health_summary
    try:
        p = Pool()
        p.add_entry(PoolEntry(provider="p", model_id="a", health_status="available"))
        p.add_entry(PoolEntry(provider="p", model_id="b", health_status="rate_limited"))
        s = p.health_summary()
        assert s.get("available") == 1 and s.get("rate_limited") == 1
        results.append(("health_summary", True))
    except:
        results.append(("health_summary", False))

    return results


# ============================================================================
# 2. providers.py — 4 tests
# ============================================================================
def _test_providers():
    from core.providers import (provider_manager, ModelProvider,
                                 OpenRouterProvider, AnthropicProvider,
                                 OpenAIProvider, OllamaProvider, GroqProvider)
    results = []

    # T1: confidence_score exists
    try:
        assert hasattr(ModelProvider, 'confidence_score')
        results.append(("P2: confidence_score property", True))
    except:
        results.append(("P2: confidence_score property", False))

    # T2: Valid confidence
    try:
        for _, p in provider_manager.providers.items():
            assert 0 <= p.confidence_score <= 100
        results.append(("P2: Valid confidence values", True))
    except:
        results.append(("P2: Valid confidence values", False))

    # T3: get_all_models_with_provider
    try:
        assert hasattr(provider_manager, 'get_all_models_with_provider')
        models = provider_manager.get_all_models_with_provider()
        if models:
            assert 'provider' in models[0] and 'provider_confidence' in models[0]
        results.append(("P1: get_all_models_with_provider", True))
    except:
        results.append(("P1: get_all_models_with_provider", False))

    # T4: Confidence values correct
    try:
        assert OpenRouterProvider().confidence_score == 70.0
        assert AnthropicProvider().confidence_score == 90.0
        assert OpenAIProvider().confidence_score == 90.0
        assert OllamaProvider().confidence_score == 60.0
        assert GroqProvider().confidence_score == 70.0
        results.append(("P2: Confidence values (90/70/60)", True))
    except:
        results.append(("P2: Confidence values (90/70/60)", False))

    return results


# ============================================================================
# 3. model_health.py — 9 tests
# ============================================================================
def _test_model_health():
    from core import model_health
    results = []
    model_health._health_data.clear()

    # T1: mark_payment_required exists
    try:
        assert hasattr(model_health, 'mark_payment_required')
        results.append(("D5: mark_payment_required exists", True))
    except:
        results.append(("D5: mark_payment_required exists", False))

    # T2: payment_required status set
    try:
        model_health._health_data['pr-test'] = {'status': 'unknown'}
        model_health.mark_payment_required('pr-test', 'openrouter')
        assert model_health.get_status('pr-test') == 'payment_required'
        results.append(("D5: payment_required status", True))
    except:
        results.append(("D5: payment_required status", False))

    # T3: payment_required no overwrite available
    try:
        model_health._health_data['avail-test'] = {'status': 'available', 'verified_at': 1000.0}
        model_health.mark_payment_required('avail-test', 'openrouter')
        assert model_health.get_status('avail-test') == 'available'
        results.append(("D5: no overwrite available", True))
    except:
        results.append(("D5: no overwrite available", False))

    # T4: report_http_status 429
    try:
        model_health._health_data['http429'] = {'status': 'unknown'}
        model_health.report_http_status('http429', 429, 'openrouter')
        assert model_health.get_status('http429') == 'rate_limited'
        results.append(("D3: HTTP 429 -> rate_limited", True))
    except:
        results.append(("D3: HTTP 429 -> rate_limited", False))

    # T5: report_http_status 402
    try:
        model_health._health_data['http402'] = {'status': 'unknown'}
        model_health.report_http_status('http402', 402, 'openrouter')
        assert model_health.get_status('http402') == 'payment_required'
        results.append(("D5: HTTP 402 -> payment_required", True))
    except:
        results.append(("D5: HTTP 402 -> payment_required", False))

    # T6: report_http_status 5xx
    try:
        model_health._health_data['http500'] = {'status': 'unknown'}
        model_health.report_http_status('http500', 503, 'openrouter')
        assert model_health.get_status('http500') == 'failed'
        results.append(("D4: HTTP 5xx -> failed", True))
    except:
        results.append(("D4: HTTP 5xx -> failed", False))

    # T7: report_http_status 200
    try:
        model_health._health_data['http200'] = {'status': 'unknown'}
        model_health.report_http_status('http200', 200, 'groq')
        assert model_health.get_status('http200') == 'available'
        results.append(("HTTP 200 -> available", True))
    except:
        results.append(("HTTP 200 -> available", False))

    # T8: get_status recognizes payment_required
    try:
        assert model_health.get_status('pr-test') == 'payment_required'
        results.append(("get_status recognizes payment_required", True))
    except:
        results.append(("get_status recognizes payment_required", False))

    # T9: diagnostic_info includes payment_required
    try:
        diag = model_health.get_diagnostic_info()
        assert 'payment_required' in diag
        results.append(("diagnostic_info has payment_required", True))
    except:
        results.append(("diagnostic_info has payment_required", False))

    return results


# ============================================================================
# 4. arena_fetcher.py — 5 tests
# ============================================================================
def _test_arena_fetcher():
    from core import arena_fetcher
    results = []

    # T1: Non-blocking import
    try:
        # Arena fetcher was imported at module level, check it loaded
        assert hasattr(arena_fetcher, 'get_score_for_model')
        results.append(("D8/D10: Module loads non-blocking", True))
    except:
        results.append(("D8/D10: Module loads non-blocking", False))

    # T2: get_score_for_model works
    try:
        result = arena_fetcher.get_score_for_model('nonexistent-model', None)
        assert result is None
        results.append(("get_score_for_model works", True))
    except:
        results.append(("get_score_for_model works", False))

    # T3: is_arena_ranking_available returns bool
    try:
        result = arena_fetcher.is_arena_ranking_available()
        assert isinstance(result, bool)
        results.append(("is_arena_ranking_available bool", True))
    except:
        results.append(("is_arena_ranking_available bool", False))

    # T4: get_available_categories returns list
    try:
        cats = arena_fetcher.get_available_categories()
        assert isinstance(cats, list)
        results.append(("get_available_categories list", True))
    except:
        results.append(("get_available_categories list", False))

    # T5: _phase0_load_cache_only exists
    try:
        assert hasattr(arena_fetcher, '_phase0_load_cache_only')
        results.append(("D8/D10: _phase0_load_cache_only", True))
    except:
        results.append(("D8/D10: _phase0_load_cache_only", False))

    return results


# ============================================================================
# 5. router.py — 5 tests
# ============================================================================
def _test_router():
    from core.router import select_model, select_model_entry
    from core.pool import PoolEntry
    results = []

    # T1: select_model_entry exists
    try:
        assert callable(select_model_entry)
        results.append(("select_model_entry exists", True))
    except:
        results.append(("select_model_entry exists", False))

    # T2: select_model_entry returns PoolEntry|None
    try:
        result = select_model_entry('coding')
        assert result is None or isinstance(result, PoolEntry)
        results.append(("select_model_entry returns PoolEntry|None", True))
    except:
        results.append(("select_model_entry returns PoolEntry|None", False))

    # T3: select_model backward compat
    try:
        result = select_model('coding')
        assert result is None or isinstance(result, str)
        results.append(("select_model backward compat", True))
    except:
        results.append(("select_model backward compat", False))

    # T4: No free_first bias in code
    try:
        import inspect
        source = inspect.getsource(select_model)
        probe_section = source.split('_probe_priority')[1].split('probe_candidates')[0]
        assert 'is_free' not in probe_section
        results.append(("D1/D2: No free_first bias", True))
    except:
        results.append(("D1/D2: No free_first bias", False))

    # T5: PoolEntry composite_key
    try:
        from core.pool import Pool
        p = Pool()
        p.add_entry(PoolEntry(provider='groq', model_id='test', arena_score=85.0, health_status='available'))
        entry = p.get_entry('groq', 'test')
        assert entry.composite_key == ('groq', 'test')
        results.append(("P1: composite_key via router", True))
    except:
        results.append(("P1: composite_key via router", False))

    return results


# ============================================================================
# 6. settings.py — 4 tests
# ============================================================================
def _test_settings():
    from config.settings import settings
    results = []

    # T1: settings exists
    try:
        assert settings is not None
        results.append(("settings exists", True))
    except:
        results.append(("settings exists", False))

    # T2: usage_db_path exists
    try:
        assert hasattr(settings, 'usage_db_path')
        results.append(("usage_db_path exists", True))
    except:
        results.append(("usage_db_path exists", False))

    # T3: No hardcoded costs
    try:
        attrs = dir(settings)
        cost_attrs = [a for a in attrs if a.lower() in ['model_cost_per_call', 'default_costs', 'pricing_dict']]
        assert not cost_attrs
        results.append(("No hardcoded costs", True))
    except:
        results.append(("No hardcoded costs", False))

    # T4: arena_task_mapping exists
    try:
        assert hasattr(settings, 'arena_task_mapping')
        mapping = settings.arena_task_mapping
        assert isinstance(mapping, dict) and len(mapping) > 0
        results.append(("arena_task_mapping exists", True))
    except:
        results.append(("arena_task_mapping exists", False))

    return results


# ============================================================================
# MAIN — ejecutar todos los tests
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("APA Sprint 1 — VALIDACIÓN MAESTRA")
    print("=" * 70)

    total_start = time.time()

    # Ejecutar tests de cada módulo
    modules = [
        ("pool.py", _test_pool),
        ("providers.py", _test_providers),
        ("model_health.py", _test_model_health),
        ("arena_fetcher.py", _test_arena_fetcher),
        ("router.py", _test_router),
        ("settings.py", _test_settings),
    ]

    for module_name, test_fn in modules:
        print(f"\n--- {module_name} ---")
        fails = _run_module(module_name, test_fn)
        # Mostrar resultados de este módulo
        for mod, name, passed in _all_results:
            if mod == module_name:
                status = "PASS" if passed else "FAIL"
                print(f"  [{status}] {name}")

    total_elapsed = time.time() - total_start

    # Resumen global
    total_pass = sum(1 for _, _, p in _all_results if p)
    total_fail = sum(1 for _, _, p in _all_results if not p)
    total_tests = len(_all_results)

    print(f"\n{'=' * 70}")
    print(f"RESUMEN GLOBAL — Sprint 1")
    print(f"{'=' * 70}")
    for module_name, _ in modules:
        mod_pass = sum(1 for m, _, p in _all_results if m == module_name and p)
        mod_total = sum(1 for m, _, _ in _all_results if m == module_name)
        mod_fail = mod_total - mod_pass
        print(f"  {module_name:20s}: {mod_pass}/{mod_total} PASS, {mod_fail} FAIL")

    print(f"\n  TOTAL: {total_pass}/{total_tests} PASS, {total_fail} FAIL")
    print(f"  Tiempo: {total_elapsed:.2f}s")
    print(f"{'=' * 70}")

    if total_fail > 0:
        print("\n  FALLARON LOS SIGUIENTES TESTS:")
        for mod, name, passed in _all_results:
            if not passed:
                print(f"    [{mod}] {name}")
        sys.exit(1)
    else:
        print("\n  TODOS LOS TESTS PASARON")
        sys.exit(0)
