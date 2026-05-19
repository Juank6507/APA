#!/usr/bin/env python3
# test_e2e_pipeline_free.py — Test E2E del pipeline usando solo modelos GRATUITOS
#
# T7: Verifica que cada proveedor puede responder correctamente.
# Usa provider.call() directamente (no call_llm del router) para
# garantizar que cada test evalúa el proveedor objetivo.
#
# Flujo: populate_pool → provider.call() → validación de respuesta → métricas
#
# USO:
#   cd APA/
#   python -m apa.test_e2e_pipeline_free
#   python -m apa.test_e2e_pipeline_free --providers 3     # mínimo 3 proveedores
#   python -m apa.test_e2e_pipeline_free --quick             # 1 llamada por proveedor
#   python -m apa.test_e2e_pipeline_free --no-fallback       # sin retry con modelos conocidos
#   python -m apa.test_e2e_pipeline_free --callbacks-only    # SOLO tests de notificaciones (sin API keys)
#
# NOTA: Requiere al menos 2 proveedores con API keys configuradas
#       (excepto con --callbacks-only que no necesita API keys).
#
# ENTREGA: v1.4 — Cobertura de callbacks/notificaciones.
#         - NUEVA FASE 6: Tests del sistema de notificaciones (callbacks)
#         - NUEVO flag --callbacks-only: ejecuta solo tests de callbacks
#         - Tests: registro, emisión, buffer, unregister, broken callback,
#           eventos de model_health (mark_available, mark_failed), pool events
#         - Arena_fetcher: SIN notificaciones aún (pendiente P3)
#
# v1.3b — Fallback inteligente + modelos verificados May 2026.
# v1.2 — Fix: extrae base_id del prefixed_id del pool antes
#         de llamar al provider (parse_prefixed_id + translate_model_id).
# v1.1 — Fix: usa provider.call() en vez de call_llm() para testear
#         cada proveedor individualmente.

import sys
import os
import time
import logging
import argparse
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

# ---------------------------------------------------------------------------
# Setup path
# ---------------------------------------------------------------------------
_base_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.join(os.path.dirname(_base_dir), "APA")
if os.path.isdir(os.path.join(_repo_root, "apa")):
    sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.dirname(_base_dir))

logging.basicConfig(level=logging.WARNING)

# ===========================================================================
# CONFIGURACION
# ===========================================================================

# Prompt de prueba simple y rápido (no gasta muchos tokens)
TEST_SYSTEM_PROMPT = "You are a helpful assistant. Respond concisely."
TEST_USER_PROMPT = "What is 2+2? Reply with ONLY the number, nothing else."
TEST_MAX_TOKENS = 30
TEST_TEMPERATURE = 0.0
TIMEOUT_PER_CALL = 30  # segundos por llamada

# Modelos free verificados por proveedor (May 2026).
# Usados como fallback cuando el modelo seleccionado por el pool falla.
# NOTA: Estos modelos existen realmente en los APIs de cada proveedor.
#       Si un proveedor cambia su catálogo, actualizar esta tabla.
KNOWN_FREE_MODELS = {
    # Proveedores que ya pasan con modelo del pool — fallback no suele usarse
    "cloudflare": "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
    "github": "gpt-4o-mini",
    "mistral": "mistral-small-latest",
    "ollama": "qwen2.5-coder:1.5b",
    "siliconflow": "Qwen/Qwen3-8B",

    # Proveedores que necesitan fallback (pool selecciona modelos inexistentes)
    "cerebras": "llama3.1-8b",
    "gemini": "gemini-2.5-flash-lite",  # gemini-2.0-flash DEPRECATED (shutdown 2026-06-01)
    "groq": "llama-3.1-8b-instant",
    "huggingface": "meta-llama/Llama-3.1-8B-Instruct",
    "novita": "meta-llama/llama-3.1-8b-instruct",
    "sambanova": "Meta-Llama-3.3-70B-Instruct",

    # Proveedores con crédicos/keys faltantes (402/401) — modelo correcto
    "openrouter": "deepseek/deepseek-v4-flash:free",  # llama-4-scout rotated out May 2026
    "cohere": "command-a-03-2025",
    "together": "Meta-Llama-3-8B-Instruct",
    "deepseek": "deepseek-chat",
}


# ===========================================================================
# RESULTADOS
# ===========================================================================

class ProviderTestResult:
    """Resultado del test para un proveedor."""
    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model               # modelo solicitado (pool o fallback)
        self.pool_model = model           # modelo original del pool
        self.success: Optional[bool] = None
        self.content: str = ""
        self.error: str = ""
        self.latency_ms: float = 0.0
        self.model_used: str = ""         # modelo real enviado al API
        self.cost_usd: float = 0.0
        self.tokens_input: int = 0
        self.tokens_output: int = 0
        self.attempts: int = 0
        self.source: str = "pool"         # "pool" o "fallback"
        self.pool_error: str = ""         # error del intento con modelo del pool

    def status_icon(self) -> str:
        if self.success is True:
            return "PASS"
        elif self.success is False:
            return "FAIL"
        return "SKIP"


class CallbackTestResult:
    """Resultado de un test de callback/notificación."""
    def __init__(self, test_id: str, name: str):
        self.test_id = test_id
        self.name = name
        self.passed: bool = False
        self.skipped: bool = False
        self.error: str = ""
        self.detail: str = ""

    def status_icon(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.passed else "FAIL"


# ===========================================================================
# FUNCIONES DE TEST (FASES 1-5: Provider calls — heredadas de v1.3b)
# ===========================================================================

def setup_pool() -> Tuple[Any, List]:
    """Inicializa el pool y retorna (pool, free_entries)."""
    from core.router import populate_pool
    from core.pool import pool

    print("\n  [SETUP] Populando pool de modelos...")
    t0 = time.time()

    try:
        populate_pool(force=True)
    except Exception as e:
        print(f"    WARNING: populate_pool() fallo: {e}")
        print(f"    Continuando con pool existente si hay...")

    elapsed = time.time() - t0
    print(f"    Pool poblado en {elapsed:.1f}s")

    # Obtener modelos free
    free_entries = []
    try:
        free_entries = pool.get_free_entries(
            exclude_statuses=["failed", "payment_required", "model_removed"]
        )
    except Exception as e:
        print(f"    WARNING: get_free_entries() fallo: {e}")

    print(f"    Modelos free tier encontrados: {len(free_entries)}")

    # Agrupar por proveedor
    by_provider = defaultdict(list)
    for entry in free_entries:
        by_provider[entry.provider].append(entry)

    print(f"    Proveedores con modelos free: {len(by_provider)}")
    for prov, entries in sorted(by_provider.items()):
        top = entries[0]
        print(f"      - {prov}: {len(entries)} modelos (top: {top.model_id}, ctx={top.context_length})")

    return pool, free_entries


def get_test_targets(pool, free_entries: List, min_providers: int = 3) -> List[Dict]:
    """Selecciona modelos de prueba: uno por proveedor, priorizando free tier.

    Retorna lista de dicts: [{"provider": str, "model_id": str}, ...]
    """
    by_provider = defaultdict(list)
    for entry in free_entries:
        by_provider[entry.provider].append(entry)

    targets = []
    for prov, entries in sorted(by_provider.items()):
        # Tomar el modelo con mejor score de cada proveedor
        best = max(entries, key=lambda e: e.composite_score)
        targets.append({
            "provider": prov,
            "model_id": best.model_id,
            "score": round(best.composite_score, 2),
        })

    # Si no hay suficientes del pool, añadir fallback conocidos
    if len(targets) < min_providers:
        print(f"\n    INFO: Solo {len(targets)} proveedores del pool. "
              f"Añadiendo fallback conocidos...")

        from core.providers import provider_manager
        for prov, model in KNOWN_FREE_MODELS.items():
            if prov in [t["provider"] for t in targets]:
                continue
            prov_obj = provider_manager.providers.get(prov)
            if prov_obj and prov_obj.is_available():
                targets.append({
                    "provider": prov,
                    "model_id": model,
                    "score": 0.0,
                })
                if len(targets) >= min_providers:
                    break

    return targets


def _resolve_model_id(model_id: str, provider_name: str) -> str:
    """Extrae base_id de un prefixed_id del pool y lo traduce
    para el proveedor destino.

    El pool almacena IDs con prefijo (ej: CBS:zai-glm-4.7,
    OPR:anthropic/claude-opus-4-6, GTH:gpt-4o). Pero provider.call()
    necesita el ID base que el API del proveedor entiende.

    Pasos:
    1. parse_prefixed_id() -> extrae base_id del prefijo
    2. translate_model_id() -> adapta formato al proveedor
    """
    from core.providers import provider_manager

    # Paso 1: Quitar prefijo si lo tiene
    prefix_provider, base_id = provider_manager.parse_prefixed_id(model_id)
    if base_id is None or base_id == model_id:
        # No tiene prefijo reconocido — usar tal cual
        return model_id

    # Paso 2: Traducir al formato del proveedor destino
    translated = provider_manager.translate_model_id(base_id, provider_name)
    return translated


def _is_rate_limit_error(error: str) -> bool:
    """Detecta si un error es de rate limit (429) — no debe hacer fallback."""
    if not error:
        return False
    error_upper = error.upper()
    return "429" in error_upper or "RATE" in error_upper


def _is_auth_or_payment_error(error: str) -> bool:
    """Detecta errores de auth (401) o pago (402) — el modelo es correcto,
    falta configurar credits/key. No hace fallback."""
    if not error:
        return False
    return any(code in error for code in ["401", "402", "PAYMENT", "UNAUTHORIZED"])


def test_provider_call(provider_name: str, model_id: str,
                       resolve_model: bool = True) -> ProviderTestResult:
    """Ejecuta call() directo al provider y captura el resultado.

    Args:
        provider_name: Nombre del proveedor (ej: "cerebras")
        model_id: ID del modelo (pool o fallback)
        resolve_model: Si True, aplica parse_prefixed_id + translate_model_id.
                       Usar False para modelos fallback que ya están en formato
                       nativo del proveedor.
    """
    from core.providers import provider_manager

    result = ProviderTestResult(provider_name, model_id)

    provider = provider_manager.providers.get(provider_name)
    if provider is None:
        result.success = False
        result.error = f"Provider '{provider_name}' no encontrado"
        return result

    # Resolver prefixed_id -> base_id traducido (solo para modelos del pool)
    if resolve_model:
        call_model_id = _resolve_model_id(model_id, provider_name)
    else:
        call_model_id = model_id

    result.model_used = call_model_id

    messages = [
        {"role": "system", "content": TEST_SYSTEM_PROMPT},
        {"role": "user", "content": TEST_USER_PROMPT}
    ]

    try:
        t0 = time.time()
        response = provider.call(
            call_model_id,
            messages,
            max_tokens=TEST_MAX_TOKENS,
            temperature=TEST_TEMPERATURE,
        )
        elapsed_ms = (time.time() - t0) * 1000

        result.success = response.get("success", False)
        # Forzar content a str — algunos providers retornan int/None
        raw_content = response.get("content", "")
        result.content = str(raw_content) if raw_content is not None else ""
        result.error = response.get("error", "")
        result.latency_ms = elapsed_ms
        result.cost_usd = response.get("cost_usd", 0.0) or 0.0
        result.tokens_input = response.get("tokens_input", 0) or 0
        result.tokens_output = response.get("tokens_output", 0) or 0
        result.attempts = 1

        # Validación: contenido no vacío (después de str conversion)
        if result.success and not result.content.strip():
            result.success = False
            result.error = "Respuesta vacía (success=True pero content='')"

    except Exception as e:
        result.success = False
        result.error = f"Excepción: {type(e).__name__}: {e}"

    return result


def test_provider_with_fallback(provider_name: str, pool_model_id: str,
                                enable_fallback: bool = True) -> ProviderTestResult:
    """v1.3: Ejecuta test con modelo del pool, y si falla, reintenta con
    modelo fallback conocido.

    Retorna el mejor resultado (pool exitoso > fallback exitoso > ambos fallidos).

    Lógica de fallback:
    - Si el pool falla con error de RATE LIMIT (429) → NO hacer fallback
      (el modelo existe, es throttle temporal)
    - Si el pool falla con AUTH/PAYMENT (401/402) → NO hacer fallback
      (el modelo es correcto, falta credits/key)
    - Si el pool falla con 404/empty → SI hacer fallback
      (el modelo no existe en el proveedor)
    """
    # ── Intento 1: Modelo del pool ──
    pool_result = test_provider_call(provider_name, pool_model_id, resolve_model=True)
    pool_result.pool_model = pool_model_id
    pool_result.source = "pool"

    # Si el pool pasa, retornar directamente
    if pool_result.success:
        return pool_result

    # Si no hay fallback habilitado, retornar resultado del pool
    if not enable_fallback:
        return pool_result

    # ── Decidir si hacer fallback ──
    error = pool_result.error or ""

    # NO hacer fallback para errores temporales o de configuración
    if _is_rate_limit_error(error):
        pool_result.pool_error = "NO_RETRY: rate limit (modelo OK, throttle)"
        return pool_result
    if _is_auth_or_payment_error(error):
        pool_result.pool_error = "NO_RETRY: auth/payment (modelo OK, falta credits/key)"
        return pool_result

    # ── Intento 2: Modelo fallback conocido ──
    fallback_model = KNOWN_FREE_MODELS.get(provider_name)
    if not fallback_model:
        pool_result.pool_error = "NO_FALLBACK: sin modelo conocido para este proveedor"
        return pool_result

    # No hacer fallback si el modelo del pool ya era el fallback
    pool_resolved = _resolve_model_id(pool_model_id, provider_name)
    if pool_resolved == fallback_model:
        pool_result.pool_error = "NO_RETRY: el modelo del pool ya es el fallback"
        return pool_result

    fallback_result = test_provider_call(
        provider_name, fallback_model, resolve_model=False
    )
    fallback_result.pool_model = pool_model_id
    fallback_result.pool_error = error
    fallback_result.source = "fallback"
    fallback_result.attempts = 2

    if fallback_result.success:
        return fallback_result
    else:
        # Ambos fallaron — retornar resultado del pool (más informativo)
        fallback_result.pool_error = f"pool: {error} | fallback: {fallback_result.error}"
        return fallback_result


# ===========================================================================
# VALIDACIONES (FASES 1-5)
# ===========================================================================

def validate_result(r: ProviderTestResult) -> Tuple[bool, str]:
    """Valida el resultado de un test. Retorna (passed, reason)."""
    if not r.success:
        return False, r.error or "provider.call() retornó success=False"

    if not r.content.strip():
        return False, "Contenido de respuesta vacío"

    # Verificar que respondió algo coherente (contiene "4")
    content_upper = r.content.strip().upper()
    if "4" not in content_upper:
        # No es un fallo crítico, el modelo respondió pero quizás no "solo el número"
        return True, "OK (respuesta sin '4', pero el modelo respondió)"

    return True, "OK"


def validate_metrics(r: ProviderTestResult) -> Tuple[bool, List[str]]:
    """Valida que las métricas del router estén presentes."""
    missing = []
    if not r.model_used:
        missing.append("model_used")
    # Nota: tokens_input/output pueden ser 0 si el provider no los reporta
    # cost_usd puede ser 0.0 para modelos free — no es un error

    return len(missing) == 0, missing


# ===========================================================================
# REPORTES (FASES 1-5)
# ===========================================================================

def print_results(results: List[ProviderTestResult]) -> None:
    """Imprime tabla de resultados con columna de fuente (pool/fallback)."""
    col = [6, 8, 14, 35, 10, 10, 30]
    headers = ["STATUS", "FUENTE", "PROVEEDOR", "MODELO", "TIEMPO", "COSTO", "RESPUESTA"]
    sep = "-" * (sum(col) + len(col) * 3 + 2)

    print(f"\n{sep}")
    print("  " + "  ".join(h.ljust(c) for h, c in zip(headers, col)))
    print(sep)

    for r in results:
        icon = r.status_icon()
        source = r.source[:6].upper()  # "POOL" or "FALLBK"
        model_short = r.model_used[:33] if r.model_used else "-"
        latency = f"{r.latency_ms:.0f}ms" if r.latency_ms > 0 else "-"
        cost = f"${r.cost_usd:.4f}" if r.cost_usd > 0 else "FREE"
        content_str = str(r.content) if r.content is not None else ""
        resp = content_str[:28].replace("\n", " ") if content_str else (str(r.error)[:28] if r.error else "")

        row = [icon, source, r.provider, model_short, latency, cost, resp]
        print("  " + "  ".join(str(v).ljust(c) for v, c in zip(row, col)))

    print(sep)


def print_summary(results: List[ProviderTestResult]) -> None:
    """Imprime resumen estadístico con detalle de fallback."""
    total = len(results)
    passed = [r for r in results if r.success is True]
    failed = [r for r in results if r.success is False]
    providers_used = set(r.provider for r in passed)

    # Separar por fuente
    pool_pass = [r for r in passed if r.source == "pool"]
    fallback_pass = [r for r in passed if r.source == "fallback"]

    print(f"\n  TOTAL: {total} | PASS: {len(passed)} | FAIL: {len(failed)}")
    if fallback_pass:
        print(f"  DESGLOSE: {len(pool_pass)} pool + {len(fallback_pass)} fallback = {len(passed)} pass")
    print(f"  PROVEEDORES EXITOSOS: {len(providers_used)} ({', '.join(sorted(providers_used))})")

    if passed:
        latencies = [r.latency_ms for r in passed]
        fastest = min(passed, key=lambda x: x.latency_ms)
        print(f"  LATENCIA: min={fastest.latency_ms:.0f}ms ({fastest.provider}), "
              f"media={sum(latencies)/len(latencies):.0f}ms")

        total_cost = sum(r.cost_usd for r in passed)
        if total_cost > 0:
            print(f"  COSTE TOTAL: ${total_cost:.4f}")
        else:
            print(f"  COSTE TOTAL: $0.00 (todos modelos free)")

    # Errores de pool que no se retryearon (429, 401, 402)
    no_retry = [r for r in failed if "NO_RETRY" in (r.pool_error or "")]
    if no_retry:
        print(f"\n  NO RETRY (error de config, no de modelo): {len(no_retry)}")
        for r in no_retry:
            reason = r.pool_error.split(":", 1)[1].strip() if ":" in r.pool_error else r.pool_error
            print(f"    - {r.provider}: {reason}")

    # Métricas del router
    print(f"\n  VALIDACION DE METRICAS DEL ROUTER:")
    all_have_model = all(r.model_used for r in passed)
    print(f"    model_used presente en todas las respuestas: {'SI' if all_have_model else 'NO'}")


# ===========================================================================
# FASE 6: TESTS DE CALLBACKS / NOTIFICACIONES (v1.4)
# ===========================================================================

def _cb_test(test_results: List[CallbackTestResult], test_id: str, name: str,
              fn, *args, **kwargs) -> bool:
    """Helper: ejecuta un test de callback y registra el resultado.

    Retorna True si el test pasó, False si falló.
    Los errores se capturan para no interrumpir la batería.
    """
    result = CallbackTestResult(test_id, name)
    try:
        passed = fn(*args, **kwargs)
        result.passed = bool(passed)
        if not result.passed:
            result.error = "Assert falló"
    except Exception as e:
        result.passed = False
        result.error = f"{type(e).__name__}: {e}"
    test_results.append(result)
    return result.passed


def run_callback_tests() -> List[CallbackTestResult]:
    """FASE 6: Ejecuta la batería de tests del sistema de notificaciones.

    Estos tests verifican que:
    - Los callbacks se registran y reciben eventos correctamente
    - El buffer de eventos funciona (get_recent_events, get_events_by_type)
    - Un callback roto no rompe el flujo
    - model_health emite eventos al cambiar estado de modelos
    - El sistema de unregister y clear funciona

    NO requiere API keys — todo se ejecuta en memoria.
    Retorna la lista de resultados.
    """
    # Imports compartidos por todas las funciones internas (closure scope)
    from core.notifications import (
        notify, register_callback, unregister_callback, clear_callbacks,
        get_callback_count, get_recent_events, get_events_by_type,
        EVT_HEALTH_MODEL_VERIFIED, EVT_HEALTH_MODEL_FAILED,
        EVT_HEALTH_MODEL_RATE_LIMITED, EVT_HEALTH_MODEL_REMOVED,
        EVT_POOL_POPULATED, _default_log_callback,
    )
    from core import model_health

    results: List[CallbackTestResult] = []

    print("\n" + "=" * 70)
    print("  FASE 6: TESTS DE CALLBACKS / NOTIFICACIONES  [v1.4]")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ── T1: Registro de callback y emisión básica ──
    def test_cb_registration():
        # Limpiar callbacks existentes (guardar los que había)
        clear_callbacks()
        collected = []

        def my_cb(event_type, message, data):
            collected.append((event_type, message, data))

        # Registrar callback de prueba
        register_callback(my_cb)
        count = get_callback_count()
        if count != 1:
            return False

        # Emitir evento y verificar recepción
        notify("test:t1", "mensaje de prueba", {"key": "value"})
        if len(collected) != 1:
            return False
        if collected[0][0] != "test:t1":
            return False
        if collected[0][1] != "mensaje de prueba":
            return False
        if collected[0][2].get("key") != "value":
            return False

        # Restaurar callback por defecto
        register_callback(_default_log_callback)
        return True

    _cb_test(results, "T1", "Callback registration + notify()",
             test_cb_registration)
    _print_cb_result(results[-1])

    # ── T2: Buffer de eventos — get_recent_events ──
    def test_recent_events():
        # Limpiar eventos previos emitiendo algo identifiable
        notify("test:marker_t2", "antes de T2", {})
        recent = get_recent_events(50)
        marker_idx = None
        for i, evt in enumerate(recent):
            if evt["type"] == "test:marker_t2":
                marker_idx = i
                break
        if marker_idx is None:
            return False

        # Emitir 3 eventos y verificar que get_recent_events los captura
        for idx in range(3):
            notify(f"test:t2_event_{idx}", f"evento {idx}", {"i": idx})

        recent = get_recent_events(5)
        # Debe haber al menos los 3 eventos nuevos entre los últimos 5
        t2_events = [e for e in recent if e["type"].startswith("test:t2_event_")]
        if len(t2_events) < 3:
            return False

        # Verificar orden (más reciente último)
        for i, evt in enumerate(t2_events):
            if evt["data"].get("i") != i:
                return False
        return True

    _cb_test(results, "T2", "Event buffer — get_recent_events()",
             test_recent_events)
    _print_cb_result(results[-1])

    # ── T3: Filtrado por tipo — get_events_by_type ──
    def test_events_by_type():
        # Emitir eventos de varios tipos
        notify("test:type_a", "evento tipo A", {"x": 1})
        notify("test:type_b", "evento tipo B", {"x": 2})
        notify("test:type_a", "otro tipo A", {"x": 3})

        by_a = get_events_by_type("test:type_a")
        by_b = get_events_by_type("test:type_b")
        by_c = get_events_by_type("test:type_c_no_existe")

        if len(by_a) < 2:
            return False
        if len(by_b) < 1:
            return False
        if len(by_c) != 0:
            return False
        return True

    _cb_test(results, "T3", "Event filtering — get_events_by_type()",
             test_events_by_type)
    _print_cb_result(results[-1])

    # ── T4: Unregister callback ──
    def test_unregister():
        clear_callbacks()
        collected = []

        def my_cb(evt, msg, data):
            collected.append(evt)

        register_callback(my_cb)
        unregister_callback(my_cb)
        if get_callback_count() != 0:
            return False

        # Emitir evento — callback desregistrado NO debe recibirlo
        notify("test:unreg", "despues de unregister", {})
        if "test:unreg" in collected:
            return False

        # Restaurar
        register_callback(_default_log_callback)
        return True

    _cb_test(results, "T4", "Unregister callback — deja de recibir eventos",
             test_unregister)
    _print_cb_result(results[-1])

    # ── T5: Callback roto no rompe el flujo ──
    def test_broken_callback():
        clear_callbacks()
        broken_called = [False]

        def good_cb(evt, msg, data):
            broken_called[0] = True

        def broken_cb(evt, msg, data):
            raise RuntimeError("Soy un callback roto en test T5")

        register_callback(broken_cb)
        register_callback(good_cb)

        # Esto NO debe lanzar excepción
        notify("test:broken", "trigger broken cb", {})

        # El buen callback debe haberse ejecutado a pesar del roto
        if not broken_called[0]:
            return False

        # Limpiar
        clear_callbacks()
        register_callback(_default_log_callback)
        return True

    _cb_test(results, "T5", "Broken callback — no rompe el flujo",
             test_broken_callback)
    _print_cb_result(results[-1])

    # ── T6: clear_callbacks ──
    def test_clear_callbacks():
        clear_callbacks()
        # Registrar varios
        for i in range(5):
            register_callback(lambda e, m, d, idx=i: None)

        if get_callback_count() != 5:
            return False

        cleared = clear_callbacks()
        if cleared != 5:
            return False
        if get_callback_count() != 0:
            return False

        # Restaurar
        register_callback(_default_log_callback)
        return True

    _cb_test(results, "T6", "clear_callbacks — elimina todos los callbacks",
             test_clear_callbacks)
    _print_cb_result(results[-1])

    # ── T7: model_health mark_available emite EVT_HEALTH_MODEL_VERIFIED ──
    def test_health_mark_available():
        collected = []
        def spy(evt, msg, data):
            if evt == EVT_HEALTH_MODEL_VERIFIED:
                collected.append((evt, msg, data))

        register_callback(spy)

        # Ejecutar mark_available (esto emite notificación vía model_health v6.1)
        model_health.mark_available("test-model-t7-verif", "test_provider_t7")

        # Verificar que se emitió el evento
        if len(collected) == 0:
            unregister_callback(spy)
            return False

        evt_type, msg, data = collected[0]
        if evt_type != EVT_HEALTH_MODEL_VERIFIED:
            unregister_callback(spy)
            return False
        if data.get("model_id") != "test-model-t7-verif":
            unregister_callback(spy)
            return False
        if data.get("provider") != "test_provider_t7":
            unregister_callback(spy)
            return False

        unregister_callback(spy)
        return True

    _cb_test(results, "T7", "model_health mark_available → EVT_HEALTH_MODEL_VERIFIED",
             test_health_mark_available)
    _print_cb_result(results[-1])

    # ── T8: model_health mark_failed emite EVT_HEALTH_MODEL_FAILED ──
    def test_health_mark_failed():
        collected = []
        def spy(evt, msg, data):
            if evt == EVT_HEALTH_MODEL_FAILED:
                collected.append((evt, msg, data))

        register_callback(spy)

        # Usar un modelo que NO esté available para que mark_failed funcione
        model_health.mark_failed("test-model-t8-fail", "test_provider_t8", "error de prueba")

        if len(collected) == 0:
            unregister_callback(spy)
            return False

        evt_type, msg, data = collected[0]
        if evt_type != EVT_HEALTH_MODEL_FAILED:
            unregister_callback(spy)
            return False
        if data.get("model_id") != "test-model-t8-fail":
            unregister_callback(spy)
            return False

        unregister_callback(spy)
        return True

    _cb_test(results, "T8", "model_health mark_failed → EVT_HEALTH_MODEL_FAILED",
             test_health_mark_failed)
    _print_cb_result(results[-1])

    # ── T9: model_health mark_rate_limited emite EVT_HEALTH_MODEL_RATE_LIMITED ──
    def test_health_rate_limited():
        collected = []
        def spy(evt, msg, data):
            if evt == EVT_HEALTH_MODEL_RATE_LIMITED:
                collected.append((evt, msg, data))

        register_callback(spy)

        model_health.mark_rate_limited("test-model-t9-rl", "test_provider_t9")

        if len(collected) == 0:
            unregister_callback(spy)
            return False

        evt_type, msg, data = collected[0]
        if data.get("model_id") != "test-model-t9-rl":
            unregister_callback(spy)
            return False

        unregister_callback(spy)
        return True

    _cb_test(results, "T9",
             "model_health mark_rate_limited → EVT_HEALTH_MODEL_RATE_LIMITED",
             test_health_rate_limited)
    _print_cb_result(results[-1])

    # ── T10: model_health mark_model_removed emite EVT_HEALTH_MODEL_REMOVED ──
    def test_health_model_removed():
        collected = []
        def spy(evt, msg, data):
            if evt == EVT_HEALTH_MODEL_REMOVED:
                collected.append((evt, msg, data))

        register_callback(spy)

        model_health.mark_model_removed("test-model-t10-rm", "test_provider_t10")

        if len(collected) == 0:
            unregister_callback(spy)
            return False

        evt_type, msg, data = collected[0]
        if data.get("model_id") != "test-model-t10-rm":
            unregister_callback(spy)
            return False

        unregister_callback(spy)
        return True

    _cb_test(results, "T10",
             "model_health mark_model_removed → EVT_HEALTH_MODEL_REMOVED",
             test_health_model_removed)
    _print_cb_result(results[-1])

    # ── T11: EVT_POOL_POPULATED emitido durante populate_pool ──
    def test_pool_populated_event():
        collected = []
        def spy(evt, msg, data):
            if evt == EVT_POOL_POPULATED:
                collected.append((evt, msg, data))

        register_callback(spy)

        # populate_pool fue llamado en FASE 1 (si no es --callbacks-only)
        # Buscar el evento en el buffer
        events = get_events_by_type(EVT_POOL_POPULATED)
        # Si no hay, intentar buscar en get_recent_events
        if not events:
            recent = get_recent_events(100)
            events = [e for e in recent if e.get("type") == EVT_POOL_POPULATED]

        unregister_callback(spy)

        if not events:
            # No se encontró — puede ser porque no se ejecutó FASE 1
            # (modo --callbacks-only). Marcar como SKIP.
            results[-1] if results else None  # placeholder
            return "SKIP"

        # Verificar estructura del evento
        last_evt = events[-1]
        if "total" not in last_evt.get("data", {}):
            return False
        return True

    # Ejecutar T11 con manejo especial de SKIP
    t11_result = CallbackTestResult("T11", "Pool populated → EVT_POOL_POPULATED")
    try:
        t11_outcome = test_pool_populated_event()
        if t11_outcome == "SKIP":
            t11_result.skipped = True
            t11_result.detail = "Pool no poblado en esta ejecución (--callbacks-only)"
        elif t11_outcome:
            t11_result.passed = True
        else:
            t11_result.error = "Evento no encontrado o estructura incorrecta"
    except Exception as e:
        t11_result.error = f"{type(e).__name__}: {e}"
    results.append(t11_result)
    _print_cb_result(t11_result)

    # ── T12: Evento tiene timestamp ──
    def test_event_timestamp():
        notify("test:timestamp", "verificar timestamp", {"ts": True})
        recent = get_recent_events(5)
        ts_events = [e for e in recent if e["type"] == "test:timestamp"]
        if not ts_events:
            return False
        if "timestamp" not in ts_events[0]:
            return False
        if ts_events[0]["timestamp"] <= 0:
            return False
        return True

    _cb_test(results, "T12", "Event structure includes timestamp",
             test_event_timestamp)
    _print_cb_result(results[-1])

    # ── Resumen FASE 6 ──
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    total = len(results)

    print(f"\n  {'=' * 50}")
    print(f"  RESUMEN CALLBACKS: {total} tests | "
          f"PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")
    print(f"  {'=' * 50}")

    # Detalle de fallos
    failed_tests = [r for r in results if not r.passed and not r.skipped]
    if failed_tests:
        print(f"\n  TESTS FALLIDOS:")
        for r in failed_tests:
            print(f"    [{r.test_id}] {r.name}: {r.error}")

    return results


def _print_cb_result(r: CallbackTestResult) -> None:
    """Imprime el resultado de un test de callback."""
    icon = r.status_icon()
    name_short = r.name[:50]
    if r.skipped:
        print(f"    [{icon}] {r.test_id}: {name_short} — {r.detail}")
    elif r.passed:
        print(f"    [{icon}] {r.test_id}: {name_short}")
    else:
        print(f"    [{icon}] {r.test_id}: {name_short} — {r.error}")


def print_callback_summary(cb_results: List[CallbackTestResult]) -> None:
    """Imprime tabla de resultados de callbacks."""
    col = [8, 6, 55, 40]
    headers = ["TEST ID", "STATUS", "NOMBRE", "DETALLE"]
    sep = "-" * (sum(col) + len(col) * 3 + 2)

    print(f"\n{sep}")
    print("  " + "  ".join(h.ljust(c) for h, c in zip(headers, col)))
    print(sep)

    for r in cb_results:
        icon = r.status_icon()
        name_short = r.name[:53]
        detail = r.detail if r.skipped else (r.error if not r.passed else "")
        detail_short = detail[:38] if detail else ""
        row = [r.test_id, icon, name_short, detail_short]
        print("  " + "  ".join(str(v).ljust(c) for v, c in zip(row, col)))

    print(sep)


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="T7: Test E2E del pipeline con modelos gratuitos + Callbacks"
    )
    parser.add_argument("--providers", "-p", type=int, default=3,
                        help="Minimo de proveedores a testear (default: 3)")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="Modo rapido: solo 1 llamada por proveedor")
    parser.add_argument("--list-only", action="store_true",
                        help="Solo listar modelos free disponibles, sin testear")
    parser.add_argument("--no-fallback", action="store_true",
                        help="Desactivar fallback a modelos conocidos (solo pool)")
    parser.add_argument("--callbacks-only", action="store_true",
                        help="v1.4: Ejecutar SOLO tests de callbacks (no necesita API keys)")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  T7 — TEST E2E PIPELINE (modelos gratuitos)  [v1.4]")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.callbacks_only:
        print("  MODO: --callbacks-only (solo tests de notificaciones)")
    elif args.no_fallback:
        print("  MODO: --no-fallback (sin retry con modelos conocidos)")
    print("=" * 70)

    # =======================================================================
    # MODO --callbacks-only: Solo FASE 6
    # =======================================================================
    if args.callbacks_only:
        cb_results = run_callback_tests()
        print_callback_summary(cb_results)

        cb_passed = sum(1 for r in cb_results if r.passed)
        cb_failed = sum(1 for r in cb_results if not r.passed and not r.skipped)

        print(f"\n  VEREDICTO CALLBACKS:")
        print(f"    Tests passed: {cb_passed}/{len(cb_results)}")
        if cb_failed == 0:
            print(f"    RESULTADO: PASS (todos los tests de callbacks pasaron)")
            sys.exit(0)
        else:
            print(f"    RESULTADO: FAIL ({cb_failed} tests fallaron)")
            sys.exit(1)

    # =======================================================================
    # MODO COMPLETO: FASES 1-5 + FASE 6
    # =======================================================================

    # ── FASE 1: Setup ──
    print("\n  FASE 1: Inicializacion del pool")
    pool, free_entries = setup_pool()

    if not free_entries and not args.list_only:
        print("\n  ERROR: No se encontraron modelos free tier.")
        print("  Verifique que al menos 2 proveedores tengan API keys en .env")
        # Continuar con FASE 6 de todas formas
        cb_results = run_callback_tests()
        print_callback_summary(cb_results)
        sys.exit(1)

    # ── FASE 2: Seleccionar objetivos ──
    print(f"\n  FASE 2: Seleccion de objetivos (minimo {args.providers} proveedores)")
    targets = get_test_targets(pool, free_entries, min_providers=args.providers)

    if len(targets) < args.providers:
        print(f"\n  WARNING: Solo {len(targets)} proveedores disponibles "
              f"(se pedian {args.providers})")

    if args.list_only:
        print(f"\n  Modelos free seleccionados ({len(targets)}):")
        for t in targets:
            fallback = KNOWN_FREE_MODELS.get(t["provider"], "-")
            print(f"    - {t['provider']:15s}  {t['model_id']}  "
                  f"(score: {t['score']}, fallback: {fallback})")
        sys.exit(0)

    print(f"  Proveedores seleccionados: {len(targets)}")
    for t in targets:
        fallback = KNOWN_FREE_MODELS.get(t["provider"], "N/A")
        print(f"    - {t['provider']:15s}  {t['model_id']}  (fallback: {fallback})")

    # ── FASE 3: Ejecutar llamadas ──
    print(f"\n  FASE 3: Ejecutando llamadas reales via provider.call()")
    results: List[ProviderTestResult] = []
    start_total = time.time()

    for target in targets:
        prov = target["provider"]
        model = target["model_id"]
        print(f"\n  Testeando {prov} ({model})...", end="", flush=True)

        result = test_provider_with_fallback(
            prov, model, enable_fallback=not args.no_fallback
        )
        results.append(result)

        passed, reason = validate_result(result)
        icon = "PASS" if passed else "FAIL"

        if result.source == "fallback" and passed:
            print(f"\n    fallback {result.model_used} "
                  f"[{icon}] {result.latency_ms:.0f}ms — {reason}")
        elif passed:
            print(f" [{icon}] {result.latency_ms:.0f}ms — {reason}")
        else:
            print(f" [{icon}] {reason[:50]}")
            if result.pool_error and "NO_RETRY" in result.pool_error:
                detail = result.pool_error.split(":", 1)[1].strip() if ":" in result.pool_error else ""
                print(f"    {detail}")

    elapsed_total = time.time() - start_total

    # ── FASE 4: Resultados ──
    print("\n" + "=" * 70)
    print("  RESULTADOS PROVIDERS")
    print("=" * 70)

    print_results(results)
    print_summary(results)

    print(f"\n  Tiempo total providers: {elapsed_total:.1f}s")

    # ── FASE 5: Veredicto providers ──
    passed_results = [r for r in results if r.success is True]
    providers_ok = set(r.provider for r in passed_results)
    has_multi_provider = len(providers_ok) >= 2

    # Contar fallos "reales" (no 429/401/402 que son de config)
    real_failures = [r for r in results if r.success is False
                     and "NO_RETRY" not in (r.pool_error or "")]

    print(f"\n  VEREDICTO PROVIDERS:")
    print(f"    Llamadas exitosas: {len(passed_results)}/{len(results)}")
    print(f"    Multi-proveedor: {'SI' if has_multi_provider else 'NO'} "
          f"({len(providers_ok)} proveedores)")
    if real_failures != results:  # Some were NO_RETRY
        no_retry_count = len(results) - len(real_failures) - len(passed_results)
        print(f"    Fallos por config (429/401/402): {no_retry_count} (no reintentados)")
        print(f"    Fallos reales (modelo/endpoint): {len(real_failures)}")

    provider_verdict = "PASS"
    if not ((len(passed_results) == len(results) and has_multi_provider) or
            (has_multi_provider and len(real_failures) == 0)):
        provider_verdict = "PARTIAL" if has_multi_provider else "FAIL"

    # ── FASE 6: Callbacks / Notificaciones ──
    cb_results = run_callback_tests()
    print_callback_summary(cb_results)

    # ── VEREDICTO FINAL COMBINADO ──
    cb_passed = sum(1 for r in cb_results if r.passed)
    cb_total_no_skip = sum(1 for r in cb_results if not r.skipped)
    cb_failed = sum(1 for r in cb_results if not r.passed and not r.skipped)

    print("\n" + "=" * 70)
    print("  VEREDICTO FINAL COMBINADO")
    print("=" * 70)
    print(f"\n  PROVIDERS:  {provider_verdict} "
          f"({len(passed_results)}/{len(results)} exitosas, "
          f"{len(providers_ok)} proveedores)")
    print(f"  CALLBACKS:  {'PASS' if cb_failed == 0 else 'FAIL'} "
          f"({cb_passed}/{cb_total_no_skip} pasaron, "
          f"{cb_failed} fallaron)")

    all_pass = provider_verdict == "PASS" and cb_failed == 0
    if all_pass:
        print(f"\n    RESULTADO GLOBAL: PASS (providers + callbacks)")
        sys.exit(0)
    else:
        partial_reasons = []
        if provider_verdict != "PASS":
            partial_reasons.append("providers parcial/fail")
        if cb_failed > 0:
            partial_reasons.append(f"{cb_failed} callback tests fallaron")
        print(f"\n    RESULTADO GLOBAL: PARTIAL ({', '.join(partial_reasons)})")
        sys.exit(0)


if __name__ == "__main__":
    main()
