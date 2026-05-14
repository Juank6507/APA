# diagnostico_providers.py
# Ejecutar con: python diagnostico_providers.py
# (desde C:\Python\Proyectos\APA\apa\)

import os
import sys

# Asegurar directorio correcto
_base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base)
os.chdir(_base)

print("=" * 70)
print("DIAGNÓSTICO DE PROVIDERS — ¿Por qué APA no ve los modelos?")
print("=" * 70)

# =========================================================================
# PASO 1: ¿Existe el archivo .env?
# =========================================================================
print("\n--- PASO 1: Archivo .env ---")
env_path = os.path.join(_base, ".env")
print(f"  Buscando .env en: {env_path}")
print(f"  Existe: {os.path.exists(env_path)}")

if os.path.exists(env_path):
    # Leer el .env y mostrar qué keys hay (SIN mostrar los valores)
    with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    key_names = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key_name = line.split("=")[0].strip()
            has_value = len(line.split("=", 1)[1].strip()) > 0
            key_names.append((key_name, has_value))
    
    print(f"  Variables en .env: {len(key_names)}")
    for name, has_val in key_names:
        status = "CON VALOR" if has_val else "VACIA"
        # Ocultar valor completo, mostrar solo primeros 4 chars
        print(f"    {name:30s} {status}")
else:
    print("  *** NO SE ENCUENTRA .env ***")

# =========================================================================
# PASO 2: ¿Settings lee las keys?
# =========================================================================
print("\n--- PASO 2: ¿Settings lee las keys del .env? ---")
try:
    from config.settings import settings
    
    keys_check = {
        "openrouter_api_key": settings.openrouter_api_key,
        "anthropic_api_key": settings.anthropic_api_key,
        "openai_api_key": settings.openai_api_key,
        "groq_api_key": settings.groq_api_key,
        "github_token": settings.github_token,
        "together_api_key": settings.together_api_key,
        "fireworks_api_key": settings.fireworks_api_key,
        "ollama_base_url": settings.ollama_base_url,
    }
    
    configured_count = 0
    for attr, val in keys_check.items():
        if val and val.strip():
            configured_count += 1
            # Mostrar solo primeros 6 caracteres
            preview = val[:6] + "..." if len(val) > 6 else val
            print(f"  {attr:30s} = {preview} (OK)")
        else:
            print(f"  {attr:30s} = (VACIA)")
    
    print(f"\n  Keys configuradas: {configured_count} de {len(keys_check)}")
except Exception as e:
    print(f"  ERROR cargando settings: {e}")

# =========================================================================
# PASO 3: ¿ProviderManager instanció los providers?
# =========================================================================
print("\n--- PASO 3: ¿Qué providers se instanciaron? ---")
try:
    from core.providers import provider_manager
    
    print(f"  Providers activos: {list(provider_manager.providers.keys())}")
    
    if not provider_manager.providers:
        print("  *** NINGÚN PROVIDER SE INSTANCIÓ ***")
        print("  Esto significa que ninguna API key llegó al ProviderManager.")
except Exception as e:
    print(f"  ERROR: {e}")

# =========================================================================
# PASO 4: Probar cada provider individualmente
# =========================================================================
print("\n--- PASO 4: Probar cada provider ---")
try:
    from core.providers import provider_manager
    import requests
    
    for name, prov in provider_manager.providers.items():
        print(f"\n  [{name}]")
        print(f"    confidence_score: {prov.confidence_score}")
        
        # Probar disponibilidad
        try:
            avail = prov.is_available()
            print(f"    is_available: {avail}")
        except Exception as e:
            print(f"    is_available ERROR: {e}")
            avail = False
        
        if avail:
            try:
                models = prov.get_models()
                print(f"    modelos: {len(models)}")
                for m in models[:3]:
                    print(f"      - {m.get('id', '?')}")
                if len(models) > 3:
                    print(f"      ... y {len(models)-3} más")
            except Exception as e:
                print(f"    get_models ERROR: {e}")
except Exception as e:
    print(f"  ERROR general: {e}")

# =========================================================================
# PASO 5: Probar OpenRouter directamente (sin provider)
# =========================================================================
print("\n--- PASO 5: OpenRouter — prueba directa ---")
try:
    api_key = settings.openrouter_api_key
    if api_key and api_key.strip():
        # Listar modelos
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        print(f"  GET /models → HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            free = [m for m in data if m.get("pricing", {}).get("prompt", "1") == "0"
                    and m.get("pricing", {}).get("completion", "1") == "0"]
            print(f"  Modelos totales: {len(data)}")
            print(f"  Modelos gratuitos: {len(free)}")
        else:
            print(f"  Respuesta: {resp.text[:200]}")
        
        # Probar una llamada simple
        print("  Probando llamada a modelo gratuito...")
        resp2 = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [{"role": "user", "content": "Responde solo: OK"}],
                "max_tokens": 5
            },
            timeout=15
        )
        print(f"  POST /chat/completions → HTTP {resp2.status_code}")
        if resp2.status_code == 200:
            content = resp2.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"  Respuesta del modelo: {content}")
        else:
            print(f"  Error: {resp2.text[:200]}")
    else:
        print("  No hay API key de OpenRouter configurada")
except Exception as e:
    print(f"  ERROR: {e}")

# =========================================================================
# PASO 6: Probar Ollama directamente
# =========================================================================
print("\n--- PASO 6: Ollama — prueba directa ---")
try:
    base_url = settings.ollama_base_url
    print(f"  URL: {base_url}")
    resp = requests.get(f"{base_url}/api/tags", timeout=3)
    if resp.status_code == 200:
        models = resp.json().get("models", [])
        print(f"  Modelos locales: {len(models)}")
        for m in models:
            name = m.get("name", "?")
            size_mb = m.get("size", 0) / (1024*1024)
            print(f"    - {name} ({size_mb:.0f} MB)")
    else:
        print(f"  HTTP {resp.status_code}")
except requests.exceptions.ConnectionError:
    print("  NO CONECTA — ¿Ollama está corriendo?")
except Exception as e:
    print(f"  ERROR: {e}")

# =========================================================================
# PASO 7: Probar Groq directamente
# =========================================================================
print("\n--- PASO 7: Groq — prueba directa ---")
try:
    api_key = settings.groq_api_key
    if api_key and api_key.strip():
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        print(f"  GET /models → HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            print(f"  Modelos disponibles: {len(data)}")
            for m in data[:5]:
                print(f"    - {m.get('id', '?')}")
    else:
        print("  No hay API key de Groq configurada")
except Exception as e:
    print(f"  ERROR: {e}")

# =========================================================================
# RESUMEN
# =========================================================================
print("\n" + "=" * 70)
print("RESUMEN DEL DIAGNÓSTICO")
print("=" * 70)
print()
print("Si ves keys configuradas en PASO 2 pero 0 providers en PASO 3,")
print("el problema está en cómo ProviderManager lee las keys.")
print()
print("Si ves providers en PASO 3 pero is_available=False en PASO 4,")
print("el problema está en la conexión a cada API.")
print()
print("Si OpenRouter funciona en PASO 5 pero no en PASO 4,")
print("el problema está en el código del provider.")
print()
print("Copia este diagnóstico completo y envíamelo para analizarlo.")
