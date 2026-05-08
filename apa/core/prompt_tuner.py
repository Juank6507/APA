# apa/core/prompt_tuner.py
import re
import json
import logging
import os
import sys
from typing import Dict, Optional
from pathlib import Path

# Ajustar path para importaciones internas del proyecto APA
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from config.settings import settings
except ImportError:
    class _DummySettings:
        log_level = 'INFO'
    settings = _DummySettings()

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, getattr(settings, 'log_level', 'INFO').upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


def get_error_pattern(error_message: str) -> str:
    """
    Extrae un patrón normalizado del mensaje de error.
    Busca nombres de excepción comunes con expresión regular.
    
    Args:
        error_message: Texto completo del error (stderr, traceback, mensaje).
    
    Returns:
        Nombre de la excepción en formato 'ErrorName' o 'unknown' si no se reconoce.
    """
    if not error_message or not isinstance(error_message, str):
        return "unknown"
    
    # Patrones de excepciones Python comunes (ordenados por especificidad)
    patterns = [
        r'\b(SyntaxError)\b',
        r'\b(IndentationError)\b',
        r'\b(TabError)\b',
        r'\b(ImportError)\b',
        r'\b(ModuleNotFoundError)\b',
        r'\b(NameError)\b',
        r'\b(AttributeError)\b',
        r'\b(TypeError)\b',
        r'\b(ValueError)\b',
        r'\b(KeyError)\b',
        r'\b(IndexError)\b',
        r'\b(AssertionError)\b',
        r'\b(ZeroDivisionError)\b',
        r'\b(FileNotFoundError)\b',
        r'\b(PermissionError)\b',
        r'\b(TimeoutError)\b',
        r'\b(RuntimeError)\b',
        r'\b(NotImplementedError)\b',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Patrones de texto descriptivo para errores sin nombre de excepción explícito
    text_patterns = [
        (r'invalid syntax', 'SyntaxError'),
        (r'unexpected indent', 'IndentationError'),
        (r'unindent does not match', 'IndentationError'),
        (r'no module named', 'ModuleNotFoundError'),
        (r'cannot import name', 'ImportError'),
        (r'is not defined', 'NameError'),
        (r'has no attribute', 'AttributeError'),
        (r'expected \d+ arguments', 'TypeError'),
        (r'takes \d+ positional arguments', 'TypeError'),
        (r'assertion failed', 'AssertionError'),
        (r'criterio fallo', 'AssertionError'),
        (r'key not found', 'KeyError'),
        (r'list index out of range', 'IndexError'),
        (r'division by zero', 'ZeroDivisionError'),
    ]
    
    for text_pattern, error_name in text_patterns:
        if re.search(text_pattern, error_message.lower()):
            return error_name
    
    return "unknown"


class PromptTuner:
    """Ajusta prompts en función de patrones de error para mejorar la tasa de éxito."""

    def __init__(self, rules_file: Optional[str] = None):
        """
        Inicializa el tuner con reglas predefinidas y opcionalmente carga reglas personalizadas.
        
        Args:
            rules_file: Ruta opcional a archivo JSON con reglas adicionales.
        """
        # 1. Cargar reglas por defecto
        self.rules = self._load_default_rules()
        
        # 2. Cargar reglas personalizadas si se proporciona ruta
        if rules_file:
            self._load_custom_rules(rules_file)

    def _load_default_rules(self) -> Dict[str, str]:
        """
        Reglas por defecto basadas en palabras clave del error.
        Cada regla mapea un patrón de error a una instrucción específica para el LLM.
        
        Returns:
            Diccionario {patrón_error: instrucción_añadir}.
        """
        return {
            # Errores de sintaxis
            "SyntaxError": (
                "IMPORTANTE: Revisa cuidadosamente la sintaxis Python. "
                "Verifica: paréntesis balanceados, dos puntos después de def/if/for/while, "
                "sangría consistente con espacios (no tabs), y comillas correctamente cerradas. "
                "El código debe ser parseable por ast.parse() sin errores."
            ),
            "IndentationError": (
                "IMPORTANTE: La sangría en Python es crítica. Usa exclusivamente espacios "
                "(recomendado: 4 por nivel), nunca mezcles tabs con espacios. "
                "Asegura que todos los bloques (if, for, def, class) tengan sangría consistente."
            ),
            "TabError": (
                "IMPORTANTE: Python no permite mezclar tabs y espacios. Convierte todos los "
                "tabs a espacios (4 por nivel) y verifica la consistencia en todo el archivo."
            ),
            
            # Errores de imports
            "ImportError": (
                "IMPORTANTE: Verifica que todos los módulos importados existen y están "
                "disponibles en el entorno. Usa solo la biblioteca estándar o módulos "
                "explícitamente permitidos. Para imports relativos, asegúrate de la ruta correcta."
            ),
            "ModuleNotFoundError": (
                "IMPORTANTE: El módulo mencionado no está disponible. Elimina el import "
                "o reemplázalo con funcionalidad equivalente de la biblioteca estándar. "
                "No asumas que módulos externos están instalados."
            ),
            
            # Errores de nombres y atributos
            "NameError": (
                "IMPORTANTE: Una variable o función no está definida. Verifica: "
                "1) El nombre está escrito exactamente como se definió (case-sensitive), "
                "2) La definición aparece antes del uso, 3) No hay typos en el identificador."
            ),
            "AttributeError": (
                "IMPORTANTE: Se está accediendo a un atributo que no existe. Verifica: "
                "1) El objeto tiene el atributo/método mencionado, 2) El nombre está bien escrito, "
                "3) No confundir atributos de instancia con atributos de clase."
            ),
            
            # Errores de tipos y valores
            "TypeError": (
                "IMPORTANTE: Hay un problema con los tipos de datos. Verifica: "
                "1) Los argumentos pasados a funciones coinciden con los esperados, "
                "2) Las operaciones son válidas para los tipos involucrados, "
                "3) Convierte tipos explícitamente cuando sea necesario (str(), int(), etc.)."
            ),
            "ValueError": (
                "IMPORTANTE: Un valor tiene el tipo correcto pero contenido inválido. "
                "Verifica rangos, formatos de cadena, y valores esperados antes de operar. "
                "Añade validación de entrada si es necesario."
            ),
            "KeyError": (
                "IMPORTANTE: Se intenta acceder a una clave que no existe en un diccionario. "
                "Usa dict.get('clave', default) o verifica 'clave in dict' antes de acceder. "
                "Revisa que las claves estén escritas correctamente (case-sensitive)."
            ),
            "IndexError": (
                "IMPORTANTE: Índice fuera de rango en lista/tupla. Verifica que el índice "
                "está entre 0 y len(secuencia)-1, o usa slicing seguro. Considera iterar "
                "directamente sobre la secuencia en lugar de usar índices."
            ),
            
            # Errores lógicos y de aserción
            "AssertionError": (
                "IMPORTANTE: El código se ejecuta pero no cumple el criterio esperado. "
                "Añade prints de depuración temporales para rastrear valores intermedios. "
                "Revisa la lógica condicional y asegúrate de que el caso de prueba "
                "se evalúa correctamente. El bloque __main__ debe imprimir 'CRITERIO OK' "
                "cuando pase, o 'CRITERIO FALLO: detalle' cuando falle."
            ),
            
            # Errores numéricos y de archivo
            "ZeroDivisionError": (
                "IMPORTANTE: División por cero detectada. Añade validación antes de dividir: "
                "if divisor != 0: ... else: manejar_caso(). Nunca dividas sin verificar."
            ),
            "FileNotFoundError": (
                "IMPORTANTE: El archivo especificado no existe. Verifica la ruta (absoluta vs relativa), "
                "permisos de lectura, y que el archivo fue creado previamente si es esperado. "
                "Usa pathlib.Path para manejo portable de rutas."
            ),
            "PermissionError": (
                "IMPORTANTE: Sin permisos para acceder al recurso. Verifica permisos de archivo, "
                "no intentes escribir en directorios del sistema, y usa rutas dentro del sandbox."
            ),
            
            # Errores genéricos
            "RuntimeError": (
                "IMPORTANTE: Error en tiempo de ejecución no específico. Revisa el traceback "
                "completo para identificar la línea exacta del fallo. Añade manejo de excepciones "
                "try/except alrededor de operaciones riesgosas."
            ),
            "NotImplementedError": (
                "IMPORTANTE: Funcionalidad no implementada. Completa el método o función "
                "con la lógica requerida, o proporciona una implementación alternativa válida."
            ),
            "TimeoutError": (
                "IMPORTANTE: Operación excedió el tiempo límite. Optimiza el código para ser "
                "más eficiente, evita bucles infinitos, y considera procesar datos en chunks "
                "si son muy grandes."
            ),
            # Fallback para errores no reconocidos
            "unknown": (
                "IMPORTANTE: Se ha detectado un error no estándar. Revisa el traceback completo, "
                "valida los tipos de datos de entrada y asegura que el entorno de ejecución "
                "está correctamente configurado. Si es posible, añade manejo de excepciones específico."
            )
        }

    def _load_custom_rules(self, rules_file: str) -> None:
        """
        Carga reglas adicionales desde un archivo JSON.
        El archivo debe contener un diccionario {patrón: instrucción}.
        
        Args:
            rules_file: Ruta al archivo JSON con reglas personalizadas.
        """
        try:
            if os.path.exists(rules_file):
                with open(rules_file, 'r', encoding='utf-8') as f:
                    custom_rules = json.load(f)
                self.rules.update(custom_rules)
                logger.debug(f"Loaded {len(custom_rules)} custom rules from {rules_file}")
            else:
                logger.warning(f"Custom rules file not found: {rules_file}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in rules file {rules_file}: {e}")
        except Exception as e:
            logger.error(f"Error loading custom rules from {rules_file}: {e}")

    def tune(self, original_prompt: str, error_message: str, attempt: int) -> str:
        """
        Retorna un prompt ajustado según el patrón de error detectado.
        Si no se reconoce ningún patrón, devuelve el prompt original.
        
        Args:
            original_prompt: El prompt original sin modificar.
            error_message: Mensaje de error completo para análisis.
            attempt: Número de intento actual (1-based).
        
        Returns:
            Prompt original con prefijo de instrucción añadida si aplica.
        """
        pattern = get_error_pattern(error_message)
        
        if pattern not in self.rules:
            logger.debug(f"No tuning rule for pattern '{pattern}', returning original prompt")
            return original_prompt
        
        instruction = self.rules[pattern]
        
        # Construir prefijo con énfasis progresivo según el intento
        if attempt == 1:
            prefix = f"[INSTRUCCIÓN ADICIONAL]: {instruction}\n\n"
        else:
            prefix = f"[INSTRUCCIÓN ADICIONAL (intento {attempt}) - CRÍTICO]: {instruction}\n\n"
        
        logger.debug(f"Applied tuning rule for pattern '{pattern}' (attempt {attempt})")
        return prefix + original_prompt


if __name__ == "__main__":
    import logging
    import tempfile
    
    # Configurar logging para mostrar DEBUG en pruebas
    logging.disable(logging.NOTSET)
    logger.setLevel(logging.DEBUG)
    
    print("=== INICIO PRUEBAS T14 - PromptTuner ===\n")
    
    tuner = PromptTuner()
    base_prompt = "Genera código Python que cumpla el criterio especificado."
    
    # Prueba 1: SyntaxError
    error_syntax = "File \"test.py\", line 3\n    def foo()\n           ^\nSyntaxError: invalid syntax"
    tuned = tuner.tune(base_prompt, error_syntax, attempt=1)
    assert "[INSTRUCCIÓN ADICIONAL]:" in tuned
    assert base_prompt in tuned
    print("✅ SyntaxError -> instrucción añadida")
    
    # Prueba 2: ImportError / ModuleNotFoundError
    error_import = "ModuleNotFoundError: No module named 'requests'"
    tuned = tuner.tune(base_prompt, error_import, attempt=1)
    assert "IMPORTANTE: El módulo mencionado no está disponible" in tuned or \
           "IMPORTANTE: Verifica que todos los módulos importados" in tuned
    print("✅ ImportError/ModuleNotFoundError -> instrucción añadida")
    
    # Prueba 3: AssertionError
    error_assert = "AssertionError: Expected True, got False\nCRITERIO FALLO: resultado incorrecto"
    tuned = tuner.tune(base_prompt, error_assert, attempt=1)
    assert "Añade prints de depuración" in tuned or "CRITERIO OK" in tuned
    print("✅ AssertionError -> instrucción añadida")
    
    # Prueba 4: Error desconocido -> prompt con regla fallback por defecto
    error_unknown = "Algo raro pasó y no sé qué es"
    tuned = tuner.tune(base_prompt, error_unknown, attempt=1)
    # Verificamos que se aplica la regla por defecto para "unknown"
    assert "IMPORTANTE: Se ha detectado un error no estándar" in tuned
    print("✅ Error desconocido -> se aplica regla fallback")
    
    # Prueba 5: Intento 2 debe incluir número de intento
    error_syntax2 = "SyntaxError: unexpected EOF while parsing"
    tuned = tuner.tune(base_prompt, error_syntax2, attempt=2)
    assert "intento 2" in tuned.lower() and "CRÍTICO" in tuned
    print("✅ Intento 2 -> prefijo incluye 'intento 2'")
    
    # Prueba 6: get_error_pattern funciona correctamente
    assert get_error_pattern("TypeError: unsupported operand type") == "TypeError"
    assert get_error_pattern("invalid syntax at line 5") == "SyntaxError"
    assert get_error_pattern("mensaje genérico sin patrón") == "unknown"
    print("✅ get_error_pattern -> patrones extraídos correctamente")
    
    # Prueba 7: Carga de reglas personalizadas (corregida para Windows)
    tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_custom_rules.json")
    try:
        # Escribimos y cerramos explícitamente para evitar bloqueo en Windows
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({"unknown": "Instrucción personalizada de prueba"}, f)
            
        tuner_custom = PromptTuner(rules_file=tmp_path)
        tuned_custom = tuner_custom.tune(base_prompt, "CustomError: algo pasó", attempt=1)
        
        # Verificación estricta
        assert "Instrucción personalizada de prueba" in tuned_custom, \
               f"Regla personalizada no aplicada. Contenido: {tuned_custom[:100]}..."
        print("✅ Reglas personalizadas -> cargadas y aplicadas")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            
    print("\n=== Todas las pruebas pasaron ===")