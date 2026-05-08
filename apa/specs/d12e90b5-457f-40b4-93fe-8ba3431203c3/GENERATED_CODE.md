# Código generado — d12e90b5-457f-40b4-93fe-8ba3431203c3

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definirestructurademodulos.py | Definir estructura de módulos | Los directorios y archivos base existen y contienen esqueletos válidos en Python. |
| implementarvalidadordetipos.py | Implementar validador de tipos | El validador devuelve True para int/float y False/raise para str/list/etc. |
| implementaroperacionesmodularizadas.py | Implementar operaciones modularizadas | Cada operación devuelve el resultado correcto bajo módulo con enteros válidos. |
| integrarcalculadoraconvalidacion.py | Integrar calculadora con validación | La función devuelve el resultado correcto o lanza excepción para entradas inválidas. |

## definirestructurademodulos.py
**Tarea:** Definir estructura de módulos
**Criterio:** Los directorios y archivos base existen y contienen esqueletos válidos en Python.
**Descripción:** Crea una estructura de proyecto con carpetas `calculator` y `validator`, junto con sus archivos `__init__.py` y módulos `.py` que contienen funciones base. Escribe además un `main.py` con una función principal que usa las funciones de los módulos. Verifica la existencia y contenido de todos los elementos para confirmar que la estructura es válida.

```python
import os
from pathlib import Path

def create_project_structure(base_dir: str = ".") -> None:
    """Crea la estructura de carpetas y archivos base."""
    dirs = ["calculator", "validator"]
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
        (Path(d) / "__init__.py").touch()

    files = {
        "calculator/__init__.py": "",
        "calculator/core.py": "# Lógica de la calculadora\n\ndef add(a: float, b: float) -> float:\n    return a + b\n",
        "validator/__init__.py": "",
        "validator/types.py": "# Validación de tipos\n\ndef is_number(value: object) -> bool:\n    return isinstance(value, (int, float))\n",
        "main.py": "# Módulo principal\nfrom calculator.core import add\nfrom validator.types import is_number\n\ndef main() -> None:\n    print(add(1, 2))\n\nif __name__ == \"__main__\":\n    main()\n",
    }
    for fpath, content in files.items():
        Path(fpath).write_text(content)

def verify_structure() -> bool:
    """Verifica que la estructura y contenido sean válidos."""
    checks = [
        os.path.isdir("calculator"),
        os.path.isfile("calculator/__init__.py"),
        os.path.isfile("calculator/core.py"),
        "def add" in Path("calculator/core.py").read_text(),
        os.path.isdir("validator"),
        os.path.isfile("validator/__init__.py"),
        os.path.isfile("validator/types.py"),
        "is_number" in Path("validator/types.py").read_text(),
        os.path.isfile("main.py"),
        "from calculator.core import add" in Path("main.py").read_text(),
        "from validator.types import is_number" in Path("main.py").read_text(),
    ]
    return all(checks)

if __name__ == "__main__":
    create_project_structure()
    if verify_structure():
        print("CRITERIO OK")
    else:
        missing = [
            "calculator/",
            "calculator/__init__.py",
            "calculator/core.py",
            "validator/",
            "validator/__init__.py",
            "validator/types.py",
            "main.py",
        ]
        print(f"CRITERIO FALLO: estructura incompleta o inválida {missing}")
```

## implementarvalidadordetipos.py
**Tarea:** Implementar validador de tipos
**Criterio:** El validador devuelve True para int/float y False/raise para str/list/etc.
**Descripción:** Define dos funciones para validar si un valor es numérico: `is_number` retorna True solo para int o float, lanzando error para otros tipos; `validate_number` retorna True para números, False para strings y excepción para tipos no numéricos. El bloque principal prueba ambos comportamientos con enteros, flotantes, cadenas y estructuras. El objetivo es distinguir estrictamente entre tipos numéricos y no numéricos.

```python
from typing import Any

def is_number(value: Any) -> bool:
    """
    Valida si el valor recibido es un número (int o float).
    Lanza ValueError para tipos inválidos (str, list, etc.).
    """
    if isinstance(value, (int, float)):
        return True
    raise ValueError(f"Tipo inválido: {type(value).__name__}")

def validate_number(value: Any) -> bool:
    """
    Devuelve True si es número, False si no lo es sin lanzar excepción,
    o lanza excepción para tipos inválidos según criterio estricto.
    """
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return False
    raise ValueError(f"Tipo inválido: {type(value).__name__}")

if __name__ == "__main__":
    # Criterio de aceptación:
    # - is_number debe devolver True para int/float
    # - is_number debe lanzar ValueError para str/list/etc.
    # - validate_number debe devolver False para str/list/etc.
    all_ok = True

    # Test 1: int -> True
    try:
        if not is_number(42):
            all_ok = False
            print("CRITERIO FALLO: is_number(42) no devolvió True")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: is_number(42) lanzó excepción inesperada")

    # Test 2: float -> True
    try:
        if not is_number(3.14):
            all_ok = False
            print("CRITERIO FALLO: is_number(3.14) no devolvió True")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: is_number(3.14) lanzó excepción inesperada")

    # Test 3: str -> False (validate_number)
    try:
        if validate_number("hola") is not False:
            all_ok = False
            print("CRITERIO FALLO: validate_number('hola') no devolvió False")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: validate_number('hola') lanzó excepción inesperada")

    # Test 4: list -> ValueError (is_number)
    try:
        is_number([1, 2])
        all_ok = False
        print("CRITERIO FALLO: is_number([1,2]) no lanzó excepción")
    except ValueError:
        pass  # esperado
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: is_number([1,2]) lanzó excepción incorrecta")

    # Test 5: dict -> ValueError (is_number)
    try:
        is_number({"a": 1})
        all_ok = False
        print("CRITERIO FALLO: is_number({'a':1}) no lanzó excepción")
    except ValueError:
        pass  # esperado
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: is_number({'a':1}) lanzó excepción incorrecta")

    if all_ok:
        print("CRITERIO OK")
```

## implementaroperacionesmodularizadas.py
**Tarea:** Implementar operaciones modularizadas
**Criterio:** Cada operación devuelve el resultado correcto bajo módulo con enteros válidos.
**Descripción:** Implementa operaciones aritméticas módulo (suma, resta, multiplicación y división), validando que el módulo sea positivo y que el divisor tenga inverso modular. La división usa el algoritmo extendido de Euclides para calcular el inverso. Incluye una prueba que verifica los resultados esperados de cada operación.

```python
from typing import Tuple

def modular_add(a: int, b: int, modulo: int) -> int:
    """Retorna (a + b) % modulo."""
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    return (a + b) % modulo

def modular_subtract(a: int, b: int, modulo: int) -> int:
    """Retorna (a - b) % modulo ajustado para resultado no negativo."""
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    return (a - b) % modulo

def modular_multiply(a: int, b: int, modulo: int) -> int:
    """Retorna (a * b) % modulo."""
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    return (a * b) % modulo

def modular_divide(a: int, b: int, modulo: int) -> int:
    """
    Retorna (a / b) % modulo usando el inverso modular de b.
    Lanza ValueError si b no tiene inverso o si modulo <= 0.
    """
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    g, inv, _ = extended_gcd(b % modulo, modulo)
    if g != 1:
        raise ValueError("El divisor no tiene inverso modular.")
    return (a % modulo) * (inv % modulo) % modulo

def extended_gcd(x: int, y: int) -> Tuple[int, int, int]:
    """Devuelve (g, x, y) tal que g = gcd(x, y) y g = x*a + y*b."""
    if x == 0:
        return y, 0, 1
    g, s1, s2 = extended_gcd(y % x, x)
    return g, s2 - (y // x) * s1, s1

def run_tests() -> Tuple[bool, str]:
    """Ejecuta los tests de aceptación y devuelve (ok, detalle)."""
    tests = [
        (modular_add(10, 5, 7), 1, "modular_add"),
        (modular_subtract(10, 5, 7), 5, "modular_subtract"),
        (modular_multiply(10, 5, 7), 1, "modular_multiply"),
        (modular_divide(10, 5, 7), 2, "modular_divide"),
    ]
    for result, expected, name in tests:
        if result != expected:
            return False, f"{name} devolvió {result}, esperado {expected}"
    return True, ""

if __name__ == "__main__":
    ok, detail = run_tests()
    if ok:
        print("CRITERIO OK")
    else:
        print(f"CRITERIO FALLO: {detail}")
```

## integrarcalculadoraconvalidacion.py
**Tarea:** Integrar calculadora con validación
**Criterio:** La función devuelve el resultado correcto o lanza excepción para entradas inválidas.
**Descripción:** Este módulo implementa una calculadora de aritmética modular que primero valida que los operandos y el módulo sean valores numéricos (int, float o strings convertibles a int), los convierte a enteros y luego ejecuta la operación solicitada (suma, resta, multiplicación o división) bajo el módulo indicado. Cada operación verifica que el módulo sea positivo y, en el caso de la división, que el divisor tenga inverso modular; de lo contrario lanza una excepción ValueError. El bloque principal incluye pruebas que verifican tanto los resultados correctos como el manejo adecuado de entradas inválidas.

```python
from typing import Any, Tuple

def is_number(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    raise ValueError(f"Tipo inválido: {type(value).__name__}")

def validate_number(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return False
    raise ValueError(f"Tipo inválido: {type(value).__name__}")

def modular_add(a: int, b: int, modulo: int) -> int:
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    return (a + b) % modulo

def modular_subtract(a: int, b: int, modulo: int) -> int:
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    return (a - b) % modulo

def modular_multiply(a: int, b: int, modulo: int) -> int:
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    return (a * b) % modulo

def modular_divide(a: int, b: int, modulo: int) -> int:
    if modulo <= 0:
        raise ValueError("El módulo debe ser mayor que 0.")
    g, inv, _ = extended_gcd(b % modulo, modulo)
    if g != 1:
        raise ValueError("El divisor no tiene inverso modular.")
    return (a % modulo) * (inv % modulo) % modulo

def extended_gcd(x: int, y: int) -> Tuple[int, int, int]:
    if x == 0:
        return y, 0, 1
    g, s1, s2 = extended_gcd(y % x, x)
    return g, s2 - (y // x) * s1, s1

def calculate(operation: str, a: Any, b: Any, modulo: Any) -> int:
    is_number(a)
    is_number(b)
    is_number(modulo)
    a = int(a)
    b = int(b)
    modulo = int(modulo)
    if operation == "add":
        return modular_add(a, b, modulo)
    if operation == "subtract":
        return modular_subtract(a, b, modulo)
    if operation == "multiply":
        return modular_multiply(a, b, modulo)
    if operation == "divide":
        return modular_divide(a, b, modulo)
    raise ValueError("Operación no soportada")

if __name__ == "__main__":
    all_ok = True

    # Test válido: add
    try:
        if calculate("add", 10, 5, 7) != 1:
            all_ok = False
            print("CRITERIO FALLO: calculate('add', 10, 5, 7) no devolvió 1")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: calculate('add', 10, 5, 7) lanzó excepción inesperada")

    # Test válido: subtract
    try:
        if calculate("subtract", 10, 5, 7) != 5:
            all_ok = False
            print("CRITERIO FALLO: calculate('subtract', 10, 5, 7) no devolvió 5")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: calculate('subtract', 10, 5, 7) lanzó excepción inesperada")

    # Test válido: multiply
    try:
        if calculate("multiply", 10, 5, 7) != 1:
            all_ok = False
            print("CRITERIO FALLO: calculate('multiply', 10, 5, 7) no devolvió 1")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: calculate('multiply', 10, 5, 7) lanzó excepción inesperada")

    # Test válido: divide
    try:
        if calculate("divide", 10, 5, 7) != 2:
            all_ok = False
            print("CRITERIO FALLO: calculate('divide', 10, 5, 7) no devolvió 2")
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: calculate('divide', 10, 5, 7) lanzó excepción inesperada")

    # Test de tipo inválido para a
    try:
        calculate("add", "x", 5, 7)
        all_ok = False
        print("CRITERIO FALLO: calculate('add', 'x', 5, 7) no lanzó excepción")
    except ValueError:
        pass
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: calculate('add', 'x', 5, 7) lanzó excepción incorrecta")

    # Test de tipo inválido para modulo
    try:
        calculate("add", 1, 5, "mod")
        all_ok = False
        print("CRITERIO FALLO: calculate('add', 1, 5, 'mod') no lanzó excepción")
    except ValueError:
        pass
    except Exception:
        all_ok = False
        print("CRITERIO FALLO: calculate('add', 1, 5, 'mod') lanzó excepción incorrecta")

    if all_ok:
        print("CRITERIO OK")
```
