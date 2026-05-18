#!/usr/bin/env python3
# test_call_providers_v1.0.py — Test de llamada REAL (call()) a TODOS los proveedores
#
# Ejecuta una llamada chat completion real a cada proveedor disponible:
#   1. is_available() — verifica si el proveedor está activo
#   2. call() — envía "Responde solo con la palabra OK" y mide latencia
#   3. Valida que la respuesta contiene texto válido (no vacío)
#
# RESULTADOS: Tabla resumen con estado, latencia y respuesta de cada proveedor
#
# USO:
#   cd APA/apa
#   python test_call_providers_v1.0.py
#   python test_call_providers_v1.0.py --provider cerebras   # solo uno
#   python test_call_providers_v1.0.py --skip-unavailable    # no mostrar los caídos
#
# ENTREGA: v1.1 — Fix modelos obsoletos: cohere command-r→command-a-03-2025,
#         together Llama-3.1-8B-Instruct-Turbo→Meta-Llama-3-8B-Instruct.
#         Ambos modelos fueron removidos de sus APIs en 2025.

import sys
import os
import time
import logging
import argparse
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# ---------------------------------------------------------------------------
# Setup path — permite ejecutar desde APA/apa o desde APA/
# ---------------------------------------------------------------------------
_base_dir = os.path.dirname(os.path.abspath(__file__))
_repo_apa = os.path.join(os.path.dirname(_base_dir), "APA", "apa")
if os.path.isdir(_repo_apa):
    sys.path.insert(0, _repo_apa)
    os.chdir(_repo_apa)
else:
    sys.path.insert(0, _base_dir)
    os.chdir(_base_dir)

logging.basicConfig(level=logging.WARNING)

# ===========================================================================
# CONFIGURACION
# ===========================================================================

# Todos los 18 proveedores con modelo de prueba ligero (barato/rapido)
ALL_PROVIDERS = {
    # --- 10 proveedores nuevos ---
    "cerebras":    "llama3.1-8b",
    "gemini":      "gemini-2.0-flash",
    "siliconflow": "Qwen/Qwen3-8B",
    "deepseek":    "deepseek-chat",
    "mistral":     "mistral-small-latest",
    "sambanova":   "Meta-Llama-3.3-70B-Instruct",
    "huggingface": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "novita":      "deepseek/deepseek-v3-turbo",
    "cloudflare":  "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
    "cohere":      "command-a-03-2025",
    # --- 8 proveedores originales ---
    "openrouter":  "meta-llama/llama-3.3-70b-instruct:free",
    "groq":        "llama-3.1-8b-instant",
    "github":      "Meta-Llama-3.1-8B-Instruct",
    "together":    "meta-llama/Meta-Llama-3-8B-Instruct",
    "fireworks":   "accounts/fireworks/models/llama-v3p1-8b-instruct",
    "anthropic":   "claude-3-haiku-20240307",
    "openai":      "gpt-4o-mini",
    "ollama":      "qwen2.5-coder:1.5b",
}

# Proveedores que se sabe caídos por causas externas (no bugs de código)
KNOWN_DOWN = {
    "fireworks":   "Cuenta suspendida (HTTP 412)",
}

# Mensaje de prueba estandar para todos los proveedores
TEST_MESSAGES = [{"role": "user", "content": "Responde solo con la palabra OK"}]
MAX_TOKENS = 10
TEMPERATURE = 0.1
TIMEOUT_CALL = 45  # segundos maximos por llamada

# ===========================================================================
# ESTRUCTURA DE RESULTADOS
# ===========================================================================

class CallResult:
    """Almacena el resultado de una prueba call() para un proveedor."""
    def __init__(self, name: str, test_model: str):
        self.name = name
        self.test_model = test_model
        self.available: Optional[bool] = None
        self.call_success: Optional[bool] = None
        self.content: str = ""
        self.error: str = ""
        self.http_status: Optional[int] = None
        self.latency: float = 0.0
        self.timestamp: str = ""

    def status_icon(self) -> str:
        if self.available is False:
            return "OFF"
        if self.call_success is True:
            return "PASS"
        if self.call_success is False:
            return "FAIL"
        return "SKIP"

    def to_row(self) -> Tuple[str, str, str, str, str]:
        """Devuelve (icono, nombre, latencia, modelo, respuesta)."""
        icon = self.status_icon()
        latency = f"{self.latency:.2f}s" if self.latency > 0 else "-"
        model_short = self.test_model
        if len(model_short) > 35:
            model_short = model_short[:32] + "..."
        if self.content:
            resp = self.content[:40].replace("\n", " ")
        elif self.error:
            resp = self.error[:40].replace("\n", " ")
        else:
            resp = "-"
        return (icon, self.name, latency, model_short, resp)


# ===========================================================================
# FUNCIONES DE TEST
# ===========================================================================

def test_single_provider(name: str, test_model: str) -> CallResult:
    """Ejecuta is_available() + call() para un proveedor. Retorna CallResult."""
    result = CallResult(name, test_model)
    result.timestamp = datetime.now().strftime("%H:%M:%S")

    try:
        from core.providers import provider_manager
    except ImportError as e:
        result.available = False
        result.error = f"Import fallida: {e}"
        return result

    provider = provider_manager.providers.get(name)

    # ---- Paso 1: is_available() ----
    if provider is None:
        result.available = False
        result.error = "No registrado (sin key en .env)"
        # Verificar si es conocido como caído externamente
        if name in KNOWN_DOWN:
            result.error = f"No registrado — {KNOWN_DOWN[name]}"
        return result

    try:
        result.available = provider.is_available()
    except Exception as e:
        result.available = False
        result.error = f"is_available() exception: {e}"
        return result

    if not result.available:
        result.error = "is_available() = False (sin key o sin conexión)"
        return result

    # ---- Paso 2: call() real ----
    try:
        start = time.time()
        resp = provider.call(
            test_model,
            TEST_MESSAGES,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )
        result.latency = time.time() - start

        # Parsear respuesta estándar de providers.py
        result.call_success = resp.get("success", False)
        result.content = resp.get("content", "")
        result.error = resp.get("error", "")
        result.http_status = resp.get("http_status")

        # Validación adicional: contenido no vacío
        if result.call_success and not result.content.strip():
            result.call_success = False
            result.error = "Respuesta vacía (success=True pero content='')"

    except Exception as e:
        result.latency = time.time() - start if 'start' in dir() else 0.0
        result.call_success = False
        result.error = f"Excepción: {type(e).__name__}: {e}"
        result.http_status = None

    return result


def print_provider_detail(r: CallResult) -> None:
    """Imprime detalle completo de un proveedor."""
    icon = r.status_icon()
    print(f"\n  [{icon}] {r.name.upper()}")
    print(f"       Modelo:   {r.test_model}")
    print(f"       Hora:     {r.timestamp}")

    if r.available is False:
        print(f"       Estado:   NO DISPONIBLE")
        print(f"       Motivo:   {r.error}")
        return

    print(f"       Disponible: SI")
    print(f"       Latencia:   {r.latency:.2f}s")

    if r.call_success:
        content_display = r.content[:60].replace("\n", " ")
        print(f"       Respuesta: '{content_display}'")
    else:
        status_str = f" HTTP {r.http_status}" if r.http_status else ""
        print(f"       ERROR{status_str}: {r.error[:80]}")


def print_summary_table(results: List[CallResult]) -> None:
    """Imprime tabla resumen final con todos los resultados."""
    # Headers
    col = [8, 14, 8, 38, 42]
    headers = ["ESTADO", "PROVEEDOR", "TIEMPO", "MODELO", "RESPUESTA / ERROR"]
    sep = "-" * (sum(col) + len(col) * 3 + 2)

    print(f"\n{sep}")
    print("  " + "  ".join(h.ljust(c) for h, c in zip(headers, col)))
    print(sep)

    for r in results:
        row = r.to_row()
        print("  " + "  ".join(str(v).ljust(c) for v, c in zip(row, col)))

    print(sep)

    # Estadísticas
    total = len(results)
    passed = sum(1 for r in results if r.call_success is True)
    failed = sum(1 for r in results if r.call_success is False)
    skipped = sum(1 for r in results if r.call_success is None)
    off = sum(1 for r in results if r.available is False)

    print(f"\n  TOTAL: {total} | PASS: {passed} | FAIL: {failed} | OFF: {off} | SKIP: {skipped}")

    # Latencias de los que pasaron
    call_results = [r for r in results if r.call_success is True]
    if call_results:
        latencies = [r.latency for r in call_results]
        fastest = min(call_results, key=lambda x: x.latency)
        slowest = max(call_results, key=lambda x: x.latency)
        avg = sum(latencies) / len(latencies)
        print(f"  LATENCIA: min={fastest.latency:.2f}s ({fastest.name}) | "
              f"max={slowest.latency:.2f}s ({slowest.name}) | "
              f"media={avg:.2f}s")

    # Ranking por velocidad
    if len(call_results) > 1:
        ranked = sorted(call_results, key=lambda x: x.latency)
        print(f"\n  RANKING VELOCIDAD:")
        for i, r in enumerate(ranked, 1):
            print(f"    #{i}  {r.name:14s}  {r.latency:.2f}s  {r.content[:30].replace(chr(10), ' ')}")


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="APA — Test de llamada REAL (call()) a todos los proveedores"
    )
    parser.add_argument("--provider", "-p", type=str, default=None,
                        help="Proveedor específico (ej: cerebras, openai, anthropic)")
    parser.add_argument("--skip-unavailable", "-s", action="store_true",
                        help="Ocultar proveedores no disponibles del detalle")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  APA — TEST DE LLAMADA REAL (call()) — TODOS LOS PROVEEDORES")
    print(f"  v1.1 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Seleccionar proveedores a testear
    if args.provider:
        pname = args.provider.lower().strip()
        if pname not in ALL_PROVIDERS:
            print(f"\n  ERROR: Proveedor '{pname}' no reconocido.")
            print(f"  Disponibles: {', '.join(sorted(ALL_PROVIDERS.keys()))}")
            sys.exit(1)
        targets = {pname: ALL_PROVIDERS[pname]}
    else:
        targets = dict(ALL_PROVIDERS)

    # Ejecutar tests
    results: List[CallResult] = []
    start_total = time.time()

    for name, model in targets.items():
        print(f"\n  Testeando {name}...", end="", flush=True)
        result = test_single_provider(name, model)
        results.append(result)

        # Feedback inline
        icon = result.status_icon()
        if icon == "PASS":
            print(f" [{icon}] {result.latency:.2f}s")
        elif icon == "FAIL":
            print(f" [{icon}] {result.error[:50]}")
        elif icon == "OFF":
            print(f" [{icon}] No disponible")
        else:
            print(f" [{icon}]")

    elapsed_total = time.time() - start_total

    # Detalle por proveedor (si no es skip)
    if not args.skip_unavailable:
        print("\n" + "=" * 70)
        print("  DETALLE POR PROVEEDOR")
        print("=" * 70)
        for r in results:
            print_provider_detail(r)

    # Tabla resumen SIEMPRE visible
    print("\n" + "=" * 70)
    print("  RESUMEN FINAL")
    print("=" * 70)
    print_summary_table(results)

    print(f"\n  Tiempo total: {elapsed_total:.2f}s")
    print("=" * 70)

    # Exit code
    has_fail = any(r.call_success is False for r in results)
    sys.exit(1 if has_fail else 0)


if __name__ == "__main__":
    main()