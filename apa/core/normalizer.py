# apa/core/normalizer.py
import re
import logging

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

SUFFIXES_TO_REMOVE = (
    ":free", ":beta", ":experimental",
    "-instruct", "-chat", "-base", "-preview",
    "-turbo", "-exp", "-it", "-vision", "-audio"
)

_SUFFIX_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(s) for s in SUFFIXES_TO_REMOVE) + r")$",
    re.IGNORECASE
)

def _remove_suffixes(name: str) -> str:
    """Elimina de forma segura (case-insensitive) todos los sufijos definidos en la constante."""
    return _SUFFIX_PATTERN.sub("", name)

def normalize_model_id(raw_id: str) -> str:
    """
    Convierte un ID de modelo proveniente de cualquier proveedor (OpenRouter, Anthropic, etc.)
    en una cadena normalizada apta para búsqueda en los datos de Arena (Chatbot Arena).

    Reglas de normalización:
    - Extraer el nombre base según la cantidad de segmentos tras '/'.
    - Eliminar sufijos comunes (':free', '-instruct', '-chat', etc.).
    - Convertir a minúsculas.
    - Eliminar guiones, guiones bajos y puntos.

    Args:
        raw_id: ID crudo del modelo (ej: "qwen/qwen3-coder:free")

    Returns:
        Cadena normalizada (ej: "qwen3coder"). Si el input está vacío, retorna cadena vacía.
    """
    try:
        if not raw_id:
            return ""

        logger.debug(f"Entrada normalización: {raw_id}")

        # Determinar el nombre base según la cantidad de segmentos tras '/'
        if '/' in raw_id:
            parts = raw_id.split('/')
            if len(parts) == 2:
                base = parts[1]
            elif len(parts) > 2:
                base = parts[-2]   # penúltimo segmento
            else:
                base = raw_id
        else:
            base = raw_id

        # 2. Eliminar sufijos definidos (case-insensitive)
        cleaned = _remove_suffixes(base)

        # 3. Convertir a minúsculas
        normalized = cleaned.lower()

        # 4. Eliminar guiones, guiones bajos y puntos
        normalized = re.sub(r"[-_.]", "", normalized)

        logger.debug(f"Salida normalización: {normalized}")
        return normalized
    except Exception as e:
        logger.error(f"Error en normalize_model_id: {e}", exc_info=True)
        return ""

if __name__ == "__main__":
    # Prueba 1: Normalización básica
    assert normalize_model_id("qwen/qwen3-coder:free") == "qwen3coder"
    assert normalize_model_id("Qwen3-Coder") == "qwen3coder"
    assert normalize_model_id("anthropic/claude-opus-4-5") == "claudeopus45"
    assert normalize_model_id("openai/gpt-4o") == "gpt4o"
    assert normalize_model_id("meta-llama/llama-3.1-70b-instruct") == "llama3170b"
    
    # Prueba 2: Casos borde
    assert normalize_model_id("") == ""
    assert normalize_model_id(None) == ""
    assert normalize_model_id("modelo/sin/sufijos") == "sin"
    
    # Prueba 3: Verificación de igualdad según criterio específico
    id1 = "qwen/qwen3-coder:free"
    id2 = "Qwen3-Coder"
    assert normalize_model_id(id1) == normalize_model_id(id2)
    
    print("✅ T1 - Normalizador: Todas las pruebas pasaron.")