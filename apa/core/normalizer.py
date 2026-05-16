# apa/core/normalizer.py
# v1.2 — R3 (Asesor): FALSELY_FREE_MODELS — lista explícita de modelos
#         marcados como "free" que en realidad requieren pago.
#         Fuente única de verdad para providers.py._get_fake_free_ids().
#
# CAMBIOS v1.2 vs v1.1:
#   - NUEVO: FALSELY_FREE_MODELS — set de IDs de modelos que las APIs
#     reportan como gratuitos (is_free=True, pricing=prompt:0,completion:0)
#     pero que retornan HTTP 402 payment_required al llamarlos.
#     La causa: estos modelos tienen pricing=0 en el endpoint /models
#     pero requieren crédito en la cuenta para funcionar (no son truly free).
#   - Documentación de cada caso con la razón de la exclusión.
#
# v1.1 — F7 FIX: Normalización mejorada para emparejar modelos
#         entre proveedores y Arena. Ahora soporta:
#         - Variantes de puntos/guiones en versiones (opus-4-6 = opus-4.6 = opus_4_6)
#         - Tabla de alias explícitos para casos no triviales
#         - Función canonical_name() que retorna el nombre canónico para
#           buscar rankings, independientemente del proveedor o nombre exacto.
#
# CAMBIOS v1.1 vs v1.0:
#   - Alias table: mapeos explícitos de variantes conocidas
#   - canonical_name(): nombre canónico para buscar Arena scores
#   - Normalización de versiones: 4-6 = 4.6 = 4_6
#   - F6: Soporte para prefixed_id (OPR:modelo -> ignora prefijo)
import re
import logging

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

# ============================================================================
# R3 (Asesor): FALSELY_FREE_MODELS
# ============================================================================
# Modelos que las APIs reportan como gratuitos (pricing=0, o sufijo :free)
# pero que RETORNAN HTTP 402 payment_required al intentar llamarlos.
#
# RAZÓN: Estos modelos tienen pricing=0 en el endpoint /models de OpenRouter
# porque el proveedor original no cobra por el uso, PERO OpenRouter requiere
# crédito en la cuenta para enrutar la petición. Esto es un error de
# clasificación de OpenRouter (reportar como free lo que no lo es).
#
# EFECTO: Si estos modelos se incluyen como is_free=True, la primera llamada
# falla con 402 y dispara mark_provider_paid_models("openrouter"), que marca
# TODOS los modelos de pago de OpenRouter como payment_required. Esto es la
# cascada que causó la regresión del 0% en v4.0.
#
# SOLUCIÓN: Marcarlos como is_free=False aquí. Así nunca se intentan en el
# tier gratuito y no disparan la cascada de mark_provider_paid_models().
#
# MANTENIMIENTO: Si OpenRouter corrige la clasificación de estos modelos
# (deja de reportar pricing=0 para modelos que requieren crédito), se pueden
# eliminar de esta lista.
FALSELY_FREE_MODELS = {
    # Google Lyria 3 — modelos de generación de MÚSICA (no chat).
    # Retornan 402 porque OpenRouter requiere crédito para música generativa.
    # También filtrados por _NON_CHAT_PATTERNS ("lyria-"), pero se incluyen
    # aquí como doble seguridad: si alguien quita el patrón de _NON_CHAT_PATTERNS,
    # seguirán marcados como no-free.
    "google/lyria-3-pro-preview",      # 402 payment required
    "google/lyria-3-clip-preview",     # 402 payment required

    # DeepSeek V4 Flash free tier — reportado como :free pero retorna 402.
    # OpenRouter lista este modelo con pricing=0 pero requiere crédito.
    "deepseek/deepseek-v4-flash:free", # 402 payment required
}

SUFFIXES_TO_REMOVE = (
    ":free", ":beta", ":experimental",
    "-instruct", "-chat", "-base", "-preview",
    "-turbo", "-exp", "-it", "-vision", "-audio"
)

_SUFFIX_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(s) for s in SUFFIXES_TO_REMOVE) + r")$",
    re.IGNORECASE
)

# F7: Tabla de alias explícitos
# Clave = nombre normalizado (lowercase, sin separadores)
# Valor = nombre canónico que se usa para buscar en Arena
# Esto cubre casos donde la normalización genérica no alcanza,
# como cuando dos proveedores usan nombres muy distintos para
# el mismo modelo.
ALIAS_TABLE = {
    # Claude family
    "claudeopus45":    "claude-opus-4-5",
    "claudeopus46":    "claude-opus-4-6",
    "claudesonnet4":   "claude-sonnet-4",
    "claudesonnet35":  "claude-3-5-sonnet",
    "claude35sonnet":  "claude-3-5-sonnet",
    "claude3haiku":    "claude-3-haiku",
    "claude3opus":     "claude-3-opus",

    # GPT family
    "gpt4o":           "gpt-4o",
    "gpt4omini":       "gpt-4o-mini",
    "gpt4turbo":       "gpt-4-turbo",
    "gpt4":            "gpt-4",
    "o1":              "o1",
    "o1mini":          "o1-mini",
    "o1pro":           "o1-pro",
    "o3":              "o3",
    "o3mini":          "o3-mini",
    "o4mini":          "o4-mini",

    # Gemini family
    "geminipro":       "gemini-pro",
    "gemini15pro":     "gemini-1.5-pro",
    "gemini15flash":   "gemini-1.5-flash",
    "gemini2flash":    "gemini-2.0-flash",
    "gemini25pro":     "gemini-2.5-pro",
    "gemini25flash":   "gemini-2.5-flash",

    # Llama family
    "llama3170b":      "llama-3.1-70b",
    "llama318b":       "llama-3.1-8b",
    "llama370b":       "llama-3-70b",
    "llama38b":        "llama-3-8b",
    "llama4maverick":  "llama-4-maverick",
    "llama4scout":     "llama-4-scout",

    # Qwen family
    "qwen3coder":      "qwen3-coder",
    "qwen25coder":     "qwen2.5-coder",
    "qwen272b":        "qwen2.5-72b",
    "qwen3235b":       "qwen3-235b",

    # DeepSeek family
    "deepseekr1":      "deepseek-r1",
    "deepseekv3":      "deepseek-v3",
    "deepseekcoder":   "deepseek-coder",

    # Mistral family
    "mistral large":   "mistral-large",
    "mistralmedium":   "mistral-medium",
    "mistral small":   "mistral-small",
    "mixtral8x7b":     "mixtral-8x7b",
    "mixtral8x22b":    "mixtral-8x22b",
    "codestral":       "codestral",

    # Phi family
    "phi4":            "phi-4",
    "phi3mini":        "phi-3-mini",
    "phi3medium":      "phi-3-medium",

    # Command family (Cohere)
    "commandr":        "command-r",
    "commandrplus":    "command-r-plus",
}

# Reverse map: variantes normalizadas -> nombre canónico (con guiones, formato Arena)
# La clave es el nombre normalizado (sin separadores), el valor es el nombre
# canónico tal cual está en la tabla (con guiones, formato Arena).
_CANONICAL_MAP = {}
for _norm_key, _canonical in ALIAS_TABLE.items():
    _CANONICAL_MAP[_norm_key] = _canonical  # Preservar formato Arena (con guiones)


def _remove_suffixes(name: str) -> str:
    """Elimina de forma segura (case-insensitive) todos los sufijos definidos en la constante."""
    return _SUFFIX_PATTERN.sub("", name)


def _strip_provider_prefix(raw_id: str) -> str:
    """F6: Elimina prefijos de proveedor del tipo 'OPR:', 'ANT:', etc.

    Si el ID tiene formato 'XXX:resto', y XXX es un prefijo de proveedor
    conocido, retorna 'resto'. Si no, retorna el ID original.
    """
    if not raw_id or ":" not in raw_id:
        return raw_id

    # Prefijos de proveedor conocidos (F6)
    _PROVIDER_PREFIXES = {
        "OPR", "ANT", "OAI", "GRQ", "GTH", "TGT", "FWR", "OLL", "UNK"
    }

    prefix, rest = raw_id.split(":", 1)
    if prefix.upper() in _PROVIDER_PREFIXES:
        return rest
    return raw_id


def normalize_model_id(raw_id: str) -> str:
    """
    Convierte un ID de modelo proveniente de cualquier proveedor (OpenRouter, Anthropic, etc.)
    en una cadena normalizada apta para búsqueda en los datos de Arena (Chatbot Arena).

    F7: Ahora soporta variantes de puntos/guiones en versiones y
    prefijos de proveedor (F6).

    Reglas de normalización:
    - F6: Eliminar prefijo de proveedor si existe (OPR:, ANT:, etc.)
    - Extraer el nombre base según la cantidad de segmentos tras '/'.
    - Eliminar sufijos comunes (':free', '-instruct', '-chat', etc.).
    - Convertir a minúsculas.
    - Eliminar guiones, guiones bajos y puntos.

    Args:
        raw_id: ID crudo del modelo (ej: "OPR:qwen/qwen3-coder:free", "anthropic/claude-opus-4-6")

    Returns:
        Cadena normalizada (ej: "qwen3coder", "claudeopus46"). Si el input está vacío, retorna cadena vacía.
    """
    try:
        if not raw_id:
            return ""

        logger.debug(f"Entrada normalización: {raw_id}")

        # F6: Eliminar prefijo de proveedor
        cleaned = _strip_provider_prefix(raw_id)

        # Determinar el nombre base según la cantidad de segmentos tras '/'
        if '/' in cleaned:
            parts = cleaned.split('/')
            if len(parts) == 2:
                base = parts[1]
            elif len(parts) > 2:
                base = parts[-2]   # penúltimo segmento
            else:
                base = cleaned
        else:
            base = cleaned

        # Eliminar sufijos definidos (case-insensitive)
        base = _remove_suffixes(base)

        # Convertir a minúsculas
        normalized = base.lower()

        # Eliminar guiones, guiones bajos y puntos
        normalized = re.sub(r"[-_.]", "", normalized)

        logger.debug(f"Salida normalización: {normalized}")
        return normalized
    except Exception as e:
        logger.error(f"Error en normalize_model_id: {e}", exc_info=True)
        return ""


def canonical_name(raw_id: str) -> str:
    """F7: Retorna el nombre canónico de un modelo para buscar rankings.

    El nombre canónico es el identificador estándar que se usa para
    buscar el modelo en la Arena de Chatbot Arena y para emparejar
    modelos que vienen de distintos proveedores.

    Flujo:
    1. Normalizar el ID (quitar prefijos, sufijos, separadores)
    2. Buscar en la tabla de alias si hay un mapeo explícito
    3. Si no hay alias, usar el nombre normalizado como canónico

    Ejemplos:
    - "OPR:anthropic/claude-opus-4-6" -> "claudeopus46" -> alias -> "claude-opus-4-6"
    - "ANT:claude-opus-4.6"           -> "claudeopus46" -> alias -> "claude-opus-4-6"
    - "openai/gpt-4o"                -> "gpt4o"        -> alias -> "gpt-4o"
    - "meta-llama/llama-3.1-70b-instruct" -> "llama3170b" -> alias -> "llama-3.1-70b"

    Args:
        raw_id: ID crudo del modelo (acepta prefixed_id o base_id)

    Returns:
        Nombre canónico (lowercase, con guiones, sin prefijo de proveedor).
        Si no se encuentra en la tabla de alias, retorna el nombre normalizado.
    """
    norm = normalize_model_id(raw_id)
    if not norm:
        return ""

    # Buscar en la tabla de alias
    if norm in _CANONICAL_MAP:
        return _CANONICAL_MAP[norm]

    # No hay alias — retornar el nombre normalizado
    return norm


def models_match(id_a: str, id_b: str) -> bool:
    """F7: Determina si dos IDs de modelo se refieren al mismo LLM.

    Compara los nombres canónicos de ambos IDs.
    Dos proveedores pueden entregar el mismo LLM y esto se interpreta
    como dos modelos con el mismo ranking.

    Ejemplos:
    - models_match("OPR:anthropic/claude-opus-4-6", "ANT:claude-opus-4.6") -> True
    - models_match("openai/gpt-4o", "OAI:gpt-4o") -> True
    - models_match("gpt-4o", "gpt-4o-mini") -> False
    """
    return canonical_name(id_a) == canonical_name(id_b)


if __name__ == "__main__":
    # Prueba 1: Normalización básica
    assert normalize_model_id("qwen/qwen3-coder:free") == "qwen3coder"
    assert normalize_model_id("Qwen3-Coder") == "qwen3coder"
    assert normalize_model_id("anthropic/claude-opus-4-5") == "claudeopus45"
    assert normalize_model_id("openai/gpt-4o") == "gpt4o"
    assert normalize_model_id("meta-llama/llama-3.1-70b-instruct") == "llama3170b"

    # Prueba 2: F6 - Prefijos de proveedor
    assert normalize_model_id("OPR:anthropic/claude-opus-4-6") == "claudeopus46"
    assert normalize_model_id("ANT:claude-opus-4-6") == "claudeopus46"
    assert normalize_model_id("OAI:gpt-4o") == "gpt4o"
    assert normalize_model_id("OLL:llama3") == "llama3"

    # Prueba 3: F7 - Nombres canónicos (alias)
    assert canonical_name("OPR:anthropic/claude-opus-4-6") == "claude-opus-4-6"
    assert canonical_name("ANT:claude-opus-4.6") == "claude-opus-4-6"
    assert canonical_name("openai/gpt-4o") == "gpt-4o"
    assert canonical_name("meta-llama/llama-3.1-70b-instruct") == "llama-3.1-70b"

    # Prueba 4: F7 - Emparejamiento de modelos
    assert models_match("OPR:anthropic/claude-opus-4-6", "ANT:claude-opus-4.6") == True
    assert models_match("openai/gpt-4o", "OAI:gpt-4o") == True
    assert models_match("gpt-4o", "gpt-4o-mini") == False

    # Prueba 5: Casos borde
    assert normalize_model_id("") == ""
    assert normalize_model_id(None) == ""
    assert canonical_name("") == ""
    assert canonical_name(None) == ""

    print("T1 - Normalizador v1.1: Todas las pruebas pasaron.")
