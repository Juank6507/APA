#!/usr/bin/env python3
# test_F5_F6_F7_F8.py — Validación de fixes F5, F6, F7, F8
#
# Orden de validación (por dependencia):
#   1. F5 — settings.py: Búsqueda inteligente del .env
#   2. F7 — normalizer.py: Nombres canónicos y alias
#   3. F6+F8 — providers.py: Prefijos PROVEEDOR:modelo + Ollama soft
#   4. F7 — arena_fetcher.py: canonical_name lookup
#   5. F6 — router.py: Integración de prefixed_ids
#
# USO:
#   cd APA/apa
#   python test_F5_F6_F7_F8.py
#
# Basado en el patrón de validate_all.py (Sprint 1)

import sys
import os
import time
import logging

# Asegurar directorio correcto
_base_dir = os.path.dirname(os.path.abspath(__file__))
# Si se ejecuta desde download/, ajustar path al repo
_repo_apa = os.path.join(os.path.dirname(_base_dir), "APA", "apa")
if os.path.isdir(_repo_apa):
    sys.path.insert(0, _repo_apa)
    os.chdir(_repo_apa)
else:
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
# 1. F5 — settings.py: Búsqueda inteligente del .env
# ============================================================================
def _test_F5_settings():
    from config.settings import settings, _find_env_file
    results = []

    # F5-T1: _find_env_file existe y es callable
    try:
        assert callable(_find_env_file), "_find_env_file no es callable"
        results.append(("F5: _find_env_file existe", True))
    except:
        results.append(("F5: _find_env_file existe", False))

    # F5-T2: _find_env_file retorna str o None
    try:
        env_result = _find_env_file()
        assert env_result is None or isinstance(env_result, str), \
            f"Tipo inesperado: {type(env_result)}"
        results.append(("F5: _find_env_file retorna str|None", True))
    except:
        results.append(("F5: _find_env_file retorna str|None", False))

    # F5-T3: settings.env_file_found es bool
    try:
        assert hasattr(settings, 'env_file_found'), "env_file_found no definido"
        assert isinstance(settings.env_file_found, bool), \
            f"env_file_found no es bool: {type(settings.env_file_found)}"
        results.append(("F5: env_file_found es bool", True))
    except:
        results.append(("F5: env_file_found es bool", False))

    # F5-T4: validate_at_least_one_provider existe
    try:
        # Si settings se instanció, la validación pasó (o lanzó ValueError)
        # Verificar que el método existe en la clase
        from config.settings import Settings
        assert hasattr(Settings, 'validate_at_least_one_provider'), \
            "validate_at_least_one_provider no definido"
        results.append(("F5: validate_at_least_one_provider existe", True))
    except:
        results.append(("F5: validate_at_least_one_provider existe", False))

    # F5-T5: Si no hay .env, el mensaje guía al usuario
    try:
        import inspect
        from config.settings import Settings
        src = inspect.getsource(Settings.validate_at_least_one_provider)
        # Verificar que el mensaje guía menciona .env y solución
        has_env_mention = ".env" in src
        has_solution = "Coloque" in src or "configure" in src or "Solución" in src
        assert has_env_mention, "Mensaje no menciona .env"
        assert has_solution, "Mensaje no guía al usuario"
        results.append(("F5: Mensaje guía si no hay .env", True))
    except:
        results.append(("F5: Mensaje guía si no hay .env", False))

    return results


# ============================================================================
# 2. F7 — normalizer.py: Nombres canónicos y alias
# ============================================================================
def _test_F7_normalizer():
    from core.normalizer import normalize_model_id, canonical_name, models_match, ALIAS_TABLE
    results = []

    # F7-T1: Normalización básica
    try:
        assert normalize_model_id("qwen/qwen3-coder:free") == "qwen3coder"
        assert normalize_model_id("anthropic/claude-opus-4-5") == "claudeopus45"
        assert normalize_model_id("openai/gpt-4o") == "gpt4o"
        results.append(("F7: Normalización básica", True))
    except:
        results.append(("F7: Normalización básica", False))

    # F7-T2: F6 - Prefijos de proveedor se eliminan
    try:
        assert normalize_model_id("OPR:anthropic/claude-opus-4-6") == "claudeopus46"
        assert normalize_model_id("ANT:claude-opus-4-6") == "claudeopus46"
        assert normalize_model_id("OAI:gpt-4o") == "gpt4o"
        results.append(("F7: Prefijos proveedor eliminados", True))
    except:
        results.append(("F7: Prefijos proveedor eliminados", False))

    # F7-T3: ALIAS_TABLE tiene entradas
    try:
        assert len(ALIAS_TABLE) >= 30, f"ALIAS_TABLE tiene solo {len(ALIAS_TABLE)} entradas"
        results.append(("F7: ALIAS_TABLE >= 30 entradas", True))
    except:
        results.append(("F7: ALIAS_TABLE >= 30 entradas", False))

    # F7-T4: canonical_name resuelve aliases
    try:
        assert canonical_name("OPR:anthropic/claude-opus-4-6") == "claude-opus-4-6"
        assert canonical_name("ANT:claude-opus-4.6") == "claude-opus-4-6"
        assert canonical_name("openai/gpt-4o") == "gpt-4o"
        results.append(("F7: canonical_name resuelve aliases", True))
    except:
        results.append(("F7: canonical_name resuelve aliases", False))

    # F7-T5: models_match empareja modelos de distintos proveedores
    try:
        assert models_match("OPR:anthropic/claude-opus-4-6", "ANT:claude-opus-4.6") == True
        assert models_match("openai/gpt-4o", "OAI:gpt-4o") == True
        assert models_match("gpt-4o", "gpt-4o-mini") == False
        results.append(("F7: models_match cross-provider", True))
    except:
        results.append(("F7: models_match cross-provider", False))

    # F7-T6: Casos borde
    try:
        assert normalize_model_id("") == ""
        assert normalize_model_id(None) == ""
        assert canonical_name("") == ""
        assert canonical_name(None) == ""
        results.append(("F7: Casos borde (None, vacío)", True))
    except:
        results.append(("F7: Casos borde (None, vacío)", False))

    return results


# ============================================================================
# 3. F6+F8 — providers.py: Prefijos y Ollama soft
# ============================================================================
def _test_F6_F8_providers():
    from core.providers import (provider_manager, ModelProvider,
                                 OpenRouterProvider, AnthropicProvider,
                                 OpenAIProvider, OllamaProvider, GroqProvider)
    results = []

    # F6-T1: PROVIDER_PREFIXES completo
    try:
        expected = {"openrouter": "OPR", "anthropic": "ANT", "openai": "OAI",
                    "groq": "GRQ", "github": "GTH", "together": "TGT",
                    "fireworks": "FWR", "ollama": "OLL"}
        assert provider_manager.PROVIDER_PREFIXES == expected
        results.append(("F6: PROVIDER_PREFIXES completo", True))
    except:
        results.append(("F6: PROVIDER_PREFIXES completo", False))

    # F6-T2: make_prefixed_id
    try:
        pid = provider_manager.make_prefixed_id("openrouter", "anthropic/claude-opus-4-6")
        assert pid == "OPR:anthropic/claude-opus-4-6"
        pid2 = provider_manager.make_prefixed_id("anthropic", "claude-opus-4-6")
        assert pid2 == "ANT:claude-opus-4-6"
        results.append(("F6: make_prefixed_id", True))
    except:
        results.append(("F6: make_prefixed_id", False))

    # F6-T3: parse_prefixed_id
    try:
        prov, base = provider_manager.parse_prefixed_id("OPR:anthropic/claude-opus-4-6")
        assert prov == "openrouter" and base == "anthropic/claude-opus-4-6"
        prov2, base2 = provider_manager.parse_prefixed_id("ANT:claude-opus-4-6")
        assert prov2 == "anthropic" and base2 == "claude-opus-4-6"
        prov3, base3 = provider_manager.parse_prefixed_id("gpt-4o")
        assert prov3 is None and base3 == "gpt-4o"
        results.append(("F6: parse_prefixed_id", True))
    except:
        results.append(("F6: parse_prefixed_id", False))

    # F6-T4: get_all_models_with_provider incluye prefixed_id
    try:
        models_wp = provider_manager.get_all_models_with_provider()
        if models_wp:
            m = models_wp[0]
            assert "prefixed_id" in m, "Falta campo prefixed_id"
            assert "base_id" in m, "Falta campo base_id"
            assert ":" in m["prefixed_id"], f"prefixed_id sin ':': {m['prefixed_id']}"
        results.append(("F6: get_all_models_with_provider prefixed_id", True))
    except AssertionError as e:
        _all_results.append(("providers.py", f"F6: get_all_models_with_provider: {e}", False))
        results.append(("F6: get_all_models_with_provider prefixed_id", False))

    # F6-T5: PREFIX_TO_PROVIDER reverse map
    try:
        assert provider_manager.PREFIX_TO_PROVIDER["OPR"] == "openrouter"
        assert provider_manager.PREFIX_TO_PROVIDER["ANT"] == "anthropic"
        assert provider_manager.PREFIX_TO_PROVIDER["OLL"] == "ollama"
        results.append(("F6: PREFIX_TO_PROVIDER reverse map", True))
    except:
        results.append(("F6: PREFIX_TO_PROVIDER reverse map", False))

    # F8-T1: OllamaProvider._PING_TIMEOUT = 2
    try:
        ollama = provider_manager.providers.get("ollama")
        if ollama:
            assert hasattr(ollama, '_PING_TIMEOUT'), "_PING_TIMEOUT no definido"
            assert ollama._PING_TIMEOUT == 2, f"Esperado 2, got {ollama._PING_TIMEOUT}"
        results.append(("F8: Ollama _PING_TIMEOUT=2", True))
    except:
        results.append(("F8: Ollama _PING_TIMEOUT=2", False))

    # F8-T2: Ollama is_available no crashea
    try:
        ollama = provider_manager.providers.get("ollama")
        if ollama:
            avail = ollama.is_available()
            assert isinstance(avail, bool)
        results.append(("F8: Ollama is_available no crashea", True))
    except:
        results.append(("F8: Ollama is_available no crashea", False))

    # F8-T3: Ollama call retorna error claro
    try:
        ollama = provider_manager.providers.get("ollama")
        if ollama and not ollama.is_available():
            result = ollama.call("llama3", [{"role": "user", "content": "test"}])
            assert result["success"] == False
            assert "servidor" in result["error"].lower() or "no disponible" in result["error"].lower()
        results.append(("F8: Ollama call error claro", True))
    except:
        results.append(("F8: Ollama call error claro", False))

    # F8-T4: Ollama confidence_score = 60 (local)
    try:
        assert OllamaProvider._DEFAULT_CONFIDENCE_SCORE == 60.0
        results.append(("F8: Ollama confidence=60", True))
    except:
        results.append(("F8: Ollama confidence=60", False))

    return results


# ============================================================================
# 4. F7 — arena_fetcher.py: canonical_name lookup
# ============================================================================
def _test_F7_arena_fetcher():
    from core import arena_fetcher
    from core.normalizer import canonical_name
    results = []

    # F7-T1: get_score_for_model existe
    try:
        assert callable(arena_fetcher.get_score_for_model)
        results.append(("F7: get_score_for_model existe", True))
    except:
        results.append(("F7: get_score_for_model existe", False))

    # F7-T2: get_score_for_model acepta prefixed_ids
    try:
        # No debe crashear con un prefixed_id
        score = arena_fetcher.get_score_for_model("OPR:anthropic/claude-opus-4-6", None)
        # Puede ser None si no hay datos, pero no debe crashear
        assert score is None or isinstance(score, (int, float))
        results.append(("F7: get_score_for_model acepta prefixed_id", True))
    except:
        results.append(("F7: get_score_for_model acepta prefixed_id", False))

    # F7-T3: canonical_name se usa en arena_fetcher
    try:
        import inspect
        src = inspect.getsource(arena_fetcher.get_score_for_model)
        assert "canonical_name" in src or "canonical" in src, \
            "arena_fetcher no usa canonical_name"
        results.append(("F7: arena_fetcher usa canonical_name", True))
    except:
        results.append(("F7: arena_fetcher usa canonical_name", False))

    # F7-T4: Búsqueda por canónico funciona (si hay datos)
    try:
        # Si Arena data está cargada, buscar por nombre canónico
        # debe encontrar el mismo score que por nombre normalizado
        has_data = bool(arena_fetcher._arena_data)
        if has_data:
            # Probar con un modelo conocido
            score_exact = arena_fetcher.get_score_for_model("anthropic/claude-opus-4-6", None)
            score_canonical = arena_fetcher.get_score_for_model("ANT:claude-opus-4.6", None)
            # Si ambos existen, deben ser iguales (mismo modelo)
            if score_exact is not None and score_canonical is not None:
                assert score_exact == score_canonical, \
                    f"Scores difieren: exact={score_exact}, canonical={score_canonical}"
        results.append(("F7: canonical lookup consistente", True))
    except:
        results.append(("F7: canonical lookup consistente", False))

    # F7-T5: is_arena_ranking_available retorna bool
    try:
        avail = arena_fetcher.is_arena_ranking_available()
        assert isinstance(avail, bool)
        results.append(("F7: is_arena_ranking_available bool", True))
    except:
        results.append(("F7: is_arena_ranking_available bool", False))

    return results


# ============================================================================
# 5. F6 — router.py: Integración de prefixed_ids
# ============================================================================
def _test_F6_router():
    from core.router import select_model, select_model_entry
    from core.pool import PoolEntry
    results = []

    # F6-T1: populate_pool existe
    try:
        from core.router import populate_pool
        assert callable(populate_pool)
        results.append(("F6: populate_pool existe", True))
    except:
        results.append(("F6: populate_pool existe", False))

    # F6-T2: select_model_entry retorna PoolEntry|None
    try:
        result = select_model_entry('coding')
        assert result is None or isinstance(result, PoolEntry)
        results.append(("F6: select_model_entry PoolEntry|None", True))
    except:
        results.append(("F6: select_model_entry PoolEntry|None", False))

    # F6-T3: PoolEntry.model_id puede ser prefixed_id
    try:
        # Crear un PoolEntry con prefixed_id
        e = PoolEntry(provider="openrouter", model_id="OPR:anthropic/claude-opus-4-6")
        assert e.model_id == "OPR:anthropic/claude-opus-4-6"
        assert e.composite_key == ("openrouter", "OPR:anthropic/claude-opus-4-6")
        results.append(("F6: PoolEntry con prefixed_id", True))
    except:
        results.append(("F6: PoolEntry con prefixed_id", False))

    # F6-T4: _sync_health_after_call maneja prefixed_ids
    try:
        from core.router import _sync_health_after_call
        import inspect
        src = inspect.getsource(_sync_health_after_call)
        assert "parse_prefixed_id" in src or "base_id" in src, \
            "_sync_health_after_call no maneja prefixed_ids"
        results.append(("F6: _sync_health_after_call prefixed_id", True))
    except:
        results.append(("F6: _sync_health_after_call prefixed_id", False))

    # F6-T5: call_llm maneja prefixed_ids
    try:
        from core.router import call_llm
        import inspect
        src = inspect.getsource(call_llm)
        assert "parse_prefixed_id" in src or "base_id" in src, \
            "call_llm no maneja prefixed_ids"
        results.append(("F6: call_llm maneja prefixed_ids", True))
    except:
        results.append(("F6: call_llm maneja prefixed_ids", False))

    # F6-T6: populate_pool usa prefixed_id para PoolEntry
    try:
        from core.router import populate_pool
        import inspect
        src = inspect.getsource(populate_pool)
        assert "prefixed_id" in src, "populate_pool no usa prefixed_id"
        results.append(("F6: populate_pool usa prefixed_id", True))
    except:
        results.append(("F6: populate_pool usa prefixed_id", False))

    return results


# ============================================================================
# MAIN — Ejecutar todos los tests en orden de dependencia
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("APA — VALIDACION F5 / F6 / F7 / F8")
    print("Orden: F5(settings) -> F7(normalizer) -> F6+F8(providers)")
    print("       -> F7(arena_fetcher) -> F6(router)")
    print("=" * 70)

    total_start = time.time()

    # Ejecutar tests en orden de dependencia
    modules = [
        ("F5 - settings.py", _test_F5_settings),
        ("F7 - normalizer.py", _test_F7_normalizer),
        ("F6+F8 - providers.py", _test_F6_F8_providers),
        ("F7 - arena_fetcher.py", _test_F7_arena_fetcher),
        ("F6 - router.py", _test_F6_router),
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
    print(f"RESUMEN — F5/F6/F7/F8")
    print(f"{'=' * 70}")
    for module_name, _ in modules:
        mod_pass = sum(1 for m, _, p in _all_results if m == module_name and p)
        mod_total = sum(1 for m, _, _ in _all_results if m == module_name)
        mod_fail = mod_total - mod_pass
        print(f"  {module_name:30s}: {mod_pass}/{mod_total} PASS, {mod_fail} FAIL")

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
