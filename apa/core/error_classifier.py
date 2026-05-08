# apa/core/error_classifier.py
import re
import logging
import sys
import os
from enum import Enum
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    from config.settings import settings
except ImportError:
    class _DummySettings:
        SIMPLE_MODEL = "qwen/qwen3-coder:free"
        COMPLEX_MODEL = "nim/meta/llama-3.1-70b-instruct"
        log_level = "INFO"
    settings = _DummySettings()

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, getattr(settings, 'log_level', 'INFO').upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


class ErrorComplexity(Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"


# Patrones de errores simples ordenados por detección rápida
# Formato: (patrón_regex, complejidad)
ERROR_PATTERNS = [
    (r"\bSyntaxError\b", ErrorComplexity.SIMPLE),
    (r"\bIndentationError\b", ErrorComplexity.SIMPLE),
    (r"\bTabError\b", ErrorComplexity.SIMPLE),
    (r"\bImportError\b", ErrorComplexity.SIMPLE),
    (r"\bModuleNotFoundError\b", ErrorComplexity.SIMPLE),
    (r"\bNameError\b", ErrorComplexity.SIMPLE),
    (r"\bAttributeError\b", ErrorComplexity.SIMPLE),
    (r"\bTypeError\b", ErrorComplexity.SIMPLE),
    (r"invalid syntax", ErrorComplexity.SIMPLE),
    (r"unexpected eof", ErrorComplexity.SIMPLE),
    (r"expected ':'", ErrorComplexity.SIMPLE),
    (r"can't assign to literal", ErrorComplexity.SIMPLE),
    (r"unexpected indent", ErrorComplexity.SIMPLE),
    (r"unindent does not match", ErrorComplexity.SIMPLE),
    (r"takes \d+ positional argument", ErrorComplexity.SIMPLE),
]


class ErrorClassifier:
    """Clasifica errores de ejecución/corrección para seleccionar el modelo adecuado."""

    def __init__(self):
        # Compilación anticipada de patrones para eficiencia
        self._compiled_patterns = [(re.compile(p, re.IGNORECASE), c) for p, c in ERROR_PATTERNS]

    def classify(self, error_output: str, code: Optional[str] = None, execution_result: Optional[Dict[str, Any]] = None) -> ErrorComplexity:
        """
        Analiza el error y determina si es SIMPLE o COMPLEX.
        """
        if not error_output or not isinstance(error_output, str):
            logger.debug("Error output vacío o inválido, clasificado como COMPLEX por defecto")
            return ErrorComplexity.COMPLEX

        text_lower = error_output.lower()
        for pattern, complexity in self._compiled_patterns:
            if pattern.search(text_lower):
                logger.debug(f"Clasificación: {complexity.value} (coincidió '{pattern.pattern}')")
                return ErrorComplexity.SIMPLE if complexity == ErrorComplexity.SIMPLE else ErrorComplexity.COMPLEX

        logger.debug("Clasificación: COMPLEX (ningún patrón simple detectado)")
        return ErrorComplexity.COMPLEX


def get_recommended_model(complexity: ErrorComplexity, task_type: str = "correction") -> str:
    """
    Retorna el identificador del modelo recomendado según la complejidad.
    
    Args:
        complexity: ErrorComplexity.SIMPLE o ErrorComplexity.COMPLEX
        task_type: Tipo de tarea (reservado para futuras extensiones)
    
    Returns:
        Identificador del modelo recomendado.
    """
    if complexity == ErrorComplexity.SIMPLE:
        # Modelo rápido/económico para errores simples de sintaxis o imports
        return getattr(settings, 'SIMPLE_MODEL', "qwen/qwen3-coder:free")
    else:
        # Modelo más capaz para errores lógicos o de ejecución complejos
        return getattr(settings, 'COMPLEX_MODEL', "nim/meta/llama-3.1-70b-instruct")


if __name__ == "__main__":
    import logging
    # Silenciamos logs internos para cumplir con el formato de salida esperado
    logging.disable(logging.INFO)

    classifier = ErrorClassifier()

    # Casos de prueba exactos solicitados
    test_cases = [
        ("Traceback (most recent call last):\n  File \"main.py\", line 5\n    def foo()\n           ^\nSyntaxError: invalid syntax", "SyntaxError"),
        ("ModuleNotFoundError: No module named 'requests'", "ImportError"),
        ("Traceback (most recent call last):\nAssertionError: Expected True, got False", "AssertionError"),
        ("Traceback (most recent call last):\n  File \"test.py\", line 10\n    print(data['key'])\nKeyError: 'key'", "KeyError"),
    ]

    expected_map = {
        "SyntaxError": ErrorComplexity.SIMPLE,
        "ImportError": ErrorComplexity.SIMPLE,
        "AssertionError": ErrorComplexity.COMPLEX,
        "KeyError": ErrorComplexity.COMPLEX,
    }

    for err_text, name in test_cases:
        result = classifier.classify(err_text)
        expected = expected_map[name]
        assert result == expected, f"Fallo en {name}: esperado {expected.value}, obtenido {result.value}"
        print(f"✅ {name} -> {result.value.upper()}")

    simple_model = get_recommended_model(ErrorComplexity.SIMPLE)
    complex_model = get_recommended_model(ErrorComplexity.COMPLEX)
    
    print(f"Modelo recomendado SIMPLE: {simple_model}")
    print(f"Modelo recomendado COMPLEX: {complex_model}")
    
    print("Todas las pruebas pasaron.")