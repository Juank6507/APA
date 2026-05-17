#!/usr/bin/env python3
# test_new_providers_v1.py — Test individual de CARGA para cada proveedor nuevo
#
# Version: 1.0
# Fecha: 2026-05-17
# Autor: Agente Especialista Senior de Programación
#
#Qué hace:
#   1. Verifica que cada clase de proveedor se instancie correctamente
#   2. Verifica que is_available() responda sin crashear
#   3. Verifica que get_models() devuelva modelos sin crashear
#   4. Ejecuta N llamadas concurrentes (load test) midiendo:
#      - Latencia promedio y máxima
#      - Tasa de éxito / fallo
#      - Respuesta real del modelo
#
# USO:
#   cd APA/apa
#   python test_new_providers_v1.py                     # test básico (sin llamadas)
#   python test_new_providers_v1.py --call              # 1 llamada real por proveedor
#   python test_new_providers_v1.py --call --load 5     # 5 llamadas concurrentes por proveedor
#   python test_new_providers_v1.py -p cerebras --call  # solo un proveedor
#   python test_new_providers_v1.py -p cerebras -p gemini --call --load 3
#   python test_new_providers_v1.py --validate          # solo validación interna

import sys
import os
import time
import logging
import argparse
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# --- Rutas ---
_base_dir = os.path.dirname(os.path.abspath(__file__))
_repo_apa = os.path.join(os.path.dirname(_base_dir), "APA", "apa")
if os.path.isdir(_repo_apa):
    sys.path.insert(0, _repo_apa)
    os.chdir(_repo_apa)
else:
    sys.path.insert(0, _base_dir)
    os.chdir(_base_dir)

logging.basicConfig(level=logging.WARNING)

# --- Configuración de proveedores ---
PROVIDERS_NUEVOS = [
    "cerebras", "gemini", "siliconflow", "deepseek", "mistral",
    "sambanova", "huggingface", "novita", "cloudflare", "cohere",
]

CLASES = {
    "cerebras": "CerebrasProvider",
    "gemini": "GeminiProvider",
    "siliconflow": "SiliconFlowProvider",
    "deepseek": "DeepSeekProvider",
    "mistral": "MistralProvider",
    "sambanova": "SambaNovaProvider",
    "huggingface": "HuggingFaceProvider",
    "novita": "NovitaProvider",
    "cloudflare": "CloudflareProvider",
    "cohere": "CohereProvider",
}

# Modelos recomendados para test (del plan del Asesor)
MODELOS_TEST = {
    "cerebras": "llama3.1-8b",
    "gemini": "gemini-2.0-flash",
    "siliconflow": "Qwen/Qwen3-8B",
    "deepseek": "deepseek-chat",
    "mistral": "mistral-small-latest",
    "sambanova": "Meta-Llama-3.3-70B-Instruct",
    "huggingface": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "novita": "deepseek/deepseek-v3-turbo",
    "cloudflare": "@cf/meta/llama-3.1-8b-instruct-fp8-fast",
    "cohere": "command-r",
}

# Resultados globales
_resultados = []


def _obtener_provider(provider_name: str):
    """Obtiene una instancia del provider desde el ProviderManager o la crea."""
    from core.providers import provider_manager

    # Intentar obtener del ProviderManager (ya instanciado)
    provider = provider_manager.providers.get(provider_name)
    if provider is not None:
        return provider

    # Si no está en el manager, instanciar directamente
    class_name = CLASES.get(provider_name)
    if not class_name:
        return None
    mod = __import__("core.providers", fromlist=[class_name])
    cls = getattr(mod, class_name, None)
    if cls is None:
        return None
    return cls()


def test_instanciar(provider_name: str):
    """Test 1: Verifica que la clase se instancie correctamente."""
    class_name = CLASES[provider_name]
    try:
        provider = _obtener_provider(provider_name)
        if provider is None:
            return False, f"No se pudo instanciar {class_name}"
        # Verificar que tiene los métodos obligatorios
        assert hasattr(provider, "name"), "Falta propiedad 'name'"
        assert hasattr(provider, "is_available"), "Falta método 'is_available'"
        assert hasattr(provider, "get_models"), "Falta método 'get_models'"
        assert hasattr(provider, "call"), "Falta método 'call'"
        assert callable(provider.is_available), "is_available no es callable"
        assert callable(provider.get_models), "get_models no es callable"
        assert callable(provider.call), "call no es callable"
        return True, f"{class_name} instanciada OK (name='{provider.name}')"
    except Exception as e:
        return False, f"{class_name}: {e}"


def test_disponibilidad(provider_name: str):
    """Test 2: Verifica que is_available() responda sin crashear."""
    try:
        provider = _obtener_provider(provider_name)
        if provider is None:
            return False, "No se pudo obtener el provider"
        avail = provider.is_available()
        if avail:
            return True, "DISPONIBLE (API key configurada y responde)"
        else:
            return True, "NO DISPONIBLE (sin API key o sin conexión)"
    except Exception as e:
        return False, f"is_available() crasheó: {e}"


def test_obtener_modelos(provider_name: str):
    """Test 3: Verifica que get_models() devuelva modelos sin crashear."""
    try:
        provider = _obtener_provider(provider_name)
        if provider is None:
            return False, "No se pudo obtener el provider"
        models = provider.get_models()
        if not isinstance(models, list):
            return False, f"get_models() retornó {type(models).__name__}, se esperaba list"
        # Verificar estructura de cada modelo
        for m in models[:5]:
            assert "id" in m, f"Modelo sin campo 'id': {m}"
            assert "provider" in m, f"Modelo sin campo 'provider': {m}"
        nombres = [m["id"] for m in models[:5]]
        detalle = ", ".join(nombres)
        if len(models) > 5:
            detalle += f" ... (+{len(models)-5} más)"
        return True, f"{len(models)} modelos encontrados: [{detalle}]"
    except Exception as e:
        return False, f"get_models() crasheó: {e}"


def test_llamada_simple(provider_name: str, model_id: str):
    """Test 4: Una sola llamada real al proveedor."""
    try:
        provider = _obtener_provider(provider_name)
        if provider is None:
            return False, "No se pudo obtener el provider"
        start = time.time()
        result = provider.call(
            model_id,
            [{"role": "user", "content": "Responde solo con la palabra OK"}],
            max_tokens=10,
            temperature=0.1
        )
        elapsed = time.time() - start
        if result.get("success"):
            content = (result.get("content") or "")[:80].strip()
            return True, f"OK en {elapsed:.2f}s — respuesta: '{content}'"
        else:
            error = result.get("error", "desconocido")
            http = result.get("http_status", "")
            return False, f"HTTP {http}: {error}"
    except Exception as e:
        return False, f"call() crasheó: {e}"


def test_carga(provider_name: str, model_id: str, num_calls: int = 5):
    """Test 5: N llamadas concurrentes (load test) al proveedor.

    Mide latencia, tasa de éxito y consistencia de respuestas.
    """
    provider = _obtener_provider(provider_name)
    if provider is None:
        return False, "No se pudo obtener el provider"

    latencias = []
    exitos = 0
    fallos = 0
    errores_detalle = []
    respuestas = []

    def _call_once(idx):
        start = time.time()
        try:
            result = provider.call(
                model_id,
                [{"role": "user", "content": f"Dime un número del 1 al 100. Solo el número."}],
                max_tokens=15,
                temperature=0.1
            )
            elapsed = time.time() - start
            return idx, elapsed, result
        except Exception as e:
            elapsed = time.time() - start
            return idx, elapsed, {"success": False, "error": str(e), "http_status": None, "content": ""}

    # Ejecutar llamadas concurrentes
    with ThreadPoolExecutor(max_workers=min(num_calls, 5)) as executor:
        futures = {executor.submit(_call_once, i): i for i in range(num_calls)}
        for future in as_completed(futures):
            idx, elapsed, result = future.result()
            latencias.append(elapsed)
            if result.get("success"):
                exitos += 1
                content = (result.get("content") or "").strip()[:50]
                respuestas.append(content)
            else:
                fallos += 1
                error = result.get("error", "desconocido")
                http = result.get("http_status", "")
                errores_detalle.append(f"  Llamada #{idx+1}: HTTP {http} — {error}")

    # Calcular estadísticas
    if latencias:
        lat_min = min(latencias)
        lat_max = max(latencias)
        lat_avg = statistics.mean(latencias)
        lat_median = statistics.median(latencias)
        tasa_exito = (exitos / num_calls) * 100
    else:
        lat_min = lat_max = lat_avg = lat_median = 0
        tasa_exito = 0

    # Construir reporte
    reporte = [
        f"  Llamadas: {num_calls} concurrentes",
        f"  Exitos: {exitos}/{num_calls} ({tasa_exito:.0f}%)",
        f"  Fallos: {fallos}/{num_calls}",
        f"  Latencia promedio: {lat_avg:.2f}s",
        f"  Latencia mediana: {lat_median:.2f}s",
        f"  Latencia mín: {lat_min:.2f}s",
        f"  Latencia máx: {lat_max:.2f}s",
    ]

    if respuestas:
        reporte.append(f"  Respuestas: {respuestas[:3]}")
    if errores_detalle:
        reporte.append("  Errores:")
        reporte.extend(errores_detalle[:3])

    if tasa_exito >= 80:
        return True, "\n".join(reporte)
    elif tasa_exito >= 50:
        return True, f"PARCIAL ({tasa_exito:.0f}% éxito)\n" + "\n".join(reporte)
    else:
        return False, f"BAJO ({tasa_exito:.0f}% éxito)\n" + "\n".join(reporte)


def ejecutar_test_proveedor(provider_name: str, do_call: bool = False, load_count: int = 1):
    """Ejecuta todos los tests para un proveedor."""
    class_name = CLASES[provider_name]
    test_model = MODELOS_TEST.get(provider_name, "unknown")

    print(f"\n{'='*65}")
    print(f"  PROVEEDOR: {provider_name.upper()} ({class_name})")
    print(f"  Modelo de test: {test_model}")
    print(f"{'='*65}")

    proveedor_ok = True

    # Test 1: Instanciación
    ok, msg = test_instanciar(provider_name)
    estado = "PASS" if ok else "FAIL"
    print(f"  [{estado}] Instanciación: {msg}")
    if not ok:
        proveedor_ok = False
        _resultados.append({"provider": provider_name, "test": "instanciar", "ok": ok, "msg": msg})
        return

    # Test 2: Disponibilidad
    ok, msg = test_disponibilidad(provider_name)
    estado = "PASS" if ok else "FAIL"
    print(f"  [{estado}] Disponibilidad: {msg}")
    disponible = "DISPONIBLE" in msg
    _resultados.append({"provider": provider_name, "test": "disponibilidad", "ok": ok, "msg": msg})

    # Test 3: Obtener modelos
    ok, msg = test_obtener_modelos(provider_name)
    estado = "PASS" if ok else "FAIL"
    print(f"  [{estado}] Modelos: {msg}")
    _resultados.append({"provider": provider_name, "test": "modelos", "ok": ok, "msg": msg})

    # Test 4: Llamada simple (solo si --call y disponible)
    if do_call and disponible:
        ok, msg = test_llamada_simple(provider_name, test_model)
        estado = "PASS" if ok else "FAIL"
        print(f"  [{estado}] Llamada simple: {msg}")
        _resultados.append({"provider": provider_name, "test": "llamada_simple", "ok": ok, "msg": msg})

        # Test 5: Load test (solo si la llamada simple funcionó)
        if ok and load_count > 1:
            print(f"\n  --- CARGA: {load_count} llamadas concurrentes ---")
            ok, msg = test_carga(provider_name, test_model, load_count)
            estado = "PASS" if ok else "FAIL"
            print(f"  [{estado}] Load test:")
            for linea in msg.split("\n"):
                print(f"    {linea}")
            _resultados.append({"provider": provider_name, "test": "load_test", "ok": ok, "msg": msg})
    elif do_call and not disponible:
        print(f"  [SKIP] Llamada simple: proveedor no disponible (sin API key)")
        print(f"  [SKIP] Load test: proveedor no disponible")
    else:
        print(f"  [SKIP] Llamada simple: usar --call para probar llamada real")
        print(f"  [SKIP] Load test: usar --call --load N para prueba de carga")


def ejecutar_validacion_interna():
    """Validación interna del script (sin requerir API keys).

    Verifica que la estructura del script es correcta y que las
    importaciones funcionan.
    """
    print("\n" + "=" * 65)
    print("  VALIDACIÓN INTERNA DEL SCRIPT")
    print("=" * 65)

    errores = 0

    # 1. Verificar que todos los proveedores tienen clase y modelo
    print("\n  [1] Verificando mapeo de proveedores...")
    for p in PROVIDERS_NUEVOS:
        if p not in CLASES:
            print(f"    [FAIL] '{p}' no tiene clase definida en CLASES")
            errores += 1
        if p not in MODELOS_TEST:
            print(f"    [FAIL] '{p}' no tiene modelo de test en MODELOS_TEST")
            errores += 1
    if errores == 0:
        print(f"    [PASS] Los {len(PROVIDERS_NUEVOS)} proveedores tienen clase y modelo")

    # 2. Verificar que se puede importar providers
    print("\n  [2] Verificando importación de core.providers...")
    try:
        from core.providers import provider_manager, CerebrasProvider, GeminiProvider, \
            SiliconFlowProvider, DeepSeekProvider, MistralProvider, SambaNovaProvider, \
            HuggingFaceProvider, NovitaProvider, CloudflareProvider, CohereProvider
        print("    [PASS] Todas las clases importadas correctamente")
    except ImportError as e:
        print(f"    [FAIL] Error de importación: {e}")
        errores += 1

    # 3. Verificar ProviderManager tiene todos los proveedores registrados
    print("\n  [3] Verificando ProviderManager...")
    try:
        from core.providers import provider_manager
        prefijos = provider_manager.PROVIDER_PREFIXES
        faltantes = []
        for p in PROVIDERS_NUEVOS:
            if p not in prefijos:
                faltantes.append(p)
        if faltantes:
            print(f"    [FAIL] ProviderManager no tiene prefijos para: {faltantes}")
            errores += 1
        else:
            print(f"    [PASS] Los {len(PROVIDERS_NUEVOS)} proveedores tienen prefijo en ProviderManager")
    except Exception as e:
        print(f"    [FAIL] Error: {e}")
        errores += 1

    # 4. Verificar settings tiene todas las API keys
    print("\n  [4] Verificando settings.py...")
    try:
        from config.settings import settings
        keys = {
            "cerebras": settings.cerebras_api_key,
            "gemini": settings.google_api_key,
            "siliconflow": settings.siliconflow_api_key,
            "deepseek": settings.deepseek_api_key,
            "mistral": settings.mistral_api_key,
            "sambanova": settings.sambanova_api_key,
            "huggingface": settings.HF_TOKEN,
            "novita": settings.novita_api_key,
            "cloudflare": settings.cloudflare_api_token,
            "cohere": settings.cohere_api_key,
        }
        configuradas = sum(1 for k, v in keys.items() if v and v.strip())
        print(f"    [INFO] API keys configuradas: {configuradas}/{len(keys)}")
        for nombre, valor in keys.items():
            estado = "OK" if (valor and valor.strip()) else "VACÍA"
            print(f"      {nombre}: {estado}")
        print(f"    [PASS] Todas las API keys existen en settings.py")
    except Exception as e:
        print(f"    [FAIL] Error: {e}")
        errores += 1

    # 5. Verificar funciones internas
    print("\n  [5] Verificando funciones internas del script...")
    funciones = [
        ("_obtener_provider", callable(_obtener_provider)),
        ("test_instanciar", callable(test_instanciar)),
        ("test_disponibilidad", callable(test_disponibilidad)),
        ("test_obtener_modelos", callable(test_obtener_modelos)),
        ("test_llamada_simple", callable(test_llamada_simple)),
        ("test_carga", callable(test_carga)),
        ("ejecutar_test_proveedor", callable(ejecutar_test_proveedor)),
    ]
    for nombre, es_callable in funciones:
        if es_callable:
            print(f"    [PASS] {nombre}()")
        else:
            print(f"    [FAIL] {nombre}() no es callable")
            errores += 1

    # Resumen
    print(f"\n{'='*65}")
    if errores == 0:
        print("  VALIDACIÓN INTERNA: TODAS LAS PRUEBAS PASARON")
    else:
        print(f"  VALIDACIÓN INTERNA: {errores} ERROR(ES) ENCONTRADO(S)")
    print(f"{'='*65}")
    return errores == 0


def main():
    parser = argparse.ArgumentParser(
        description="Test individual de CARGA para proveedores nuevos de APA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python test_new_providers_v1.py                     # Test básico (sin llamadas API)
  python test_new_providers_v1.py --call              # 1 llamada real por proveedor
  python test_new_providers_v1.py --call --load 5     # 5 llamadas concurrentes
  python test_new_providers_v1.py -p cerebras --call  # Solo un proveedor
  python test_new_providers_v1.py --validate          # Solo validación interna
        """
    )
    parser.add_argument("--provider", "-p", type=str, action="append", default=None,
                        help="Proveedor específico (se puede repetir: -p cerebras -p gemini)")
    parser.add_argument("--call", "-c", action="store_true",
                        help="Ejecutar llamadas reales a la API")
    parser.add_argument("--load", "-l", type=int, default=1,
                        help="Número de llamadas concurrentes para load test (default: 1)")
    parser.add_argument("--validate", "-v", action="store_true",
                        help="Ejecutar solo validación interna (sin llamadas API)")
    args = parser.parse_args()

    # --- Validación interna ---
    if args.validate:
        exito = ejecutar_validacion_interna()
        sys.exit(0 if exito else 1)

    # --- Banner ---
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*65}")
    print(f"  APA — TEST DE CARGA INDIVIDUAL — PROVEEDORES NUEVOS")
    print(f"  Versión: 1.0 | {timestamp}")
    print(f"{'='*65}")
    print(f"  Fase 1: Cerebras, Gemini, SiliconFlow")
    print(f"  Fase 2: DeepSeek, Mistral, SambaNova, HuggingFace, Novita")
    print(f"  Fase 3: Cloudflare, Cohere")
    print(f"  Modo: {'LLAMADAS REALES' if args.call else 'SIN LLAMADAS (básico)'}")
    if args.call and args.load > 1:
        print(f"  Load test: {args.load} llamadas concurrentes por proveedor")

    start_total = time.time()

    # --- Determinar proveedores a testear ---
    if args.provider:
        proveedores = [p.lower() for p in args.provider]
        for p in proveedores:
            if p not in PROVIDERS_NUEVOS:
                print(f"\n  ERROR: Proveedor '{p}' no reconocido.")
                print(f"  Disponibles: {', '.join(PROVIDERS_NUEVOS)}")
                sys.exit(1)
    else:
        proveedores = PROVIDERS_NUEVOS

    # --- Ejecutar tests ---
    for pname in proveedores:
        ejecutar_test_proveedor(pname, do_call=args.call, load_count=args.load)

    # --- Resumen ---
    elapsed = time.time() - start_total
    total = len(_resultados)
    pasados = sum(1 for r in _resultados if r["ok"])
    fallidos = total - pasados

    print(f"\n{'='*65}")
    print(f"  RESUMEN FINAL: {pasados}/{total} PASS, {fallidos}/{total} FAIL")
    print(f"  Tiempo total: {elapsed:.2f}s")

    if fallidos > 0:
        print(f"\n  Tests fallidos:")
        for r in _resultados:
            if not r["ok"]:
                print(f"    [{r['provider']}] {r['test']}: {r['msg']}")

    print(f"{'='*65}")
    sys.exit(0 if fallidos == 0 else 1)


if __name__ == "__main__":
    main()
