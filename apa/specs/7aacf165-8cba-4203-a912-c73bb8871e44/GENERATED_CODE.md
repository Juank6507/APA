# Código generado — 7aacf165-8cba-4203-a912-c73bb8871e44

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definirestructurademodulos.py | Definir estructura de módulos | Los archivos existen y contienen esqueletos válidos en Python. |
| implementarvalidaciondetipos.py | Implementar validación de tipos | La función devuelve False para entradas no numéricas y True para numéricas. |
| implementaroperacionesmodularizadas.py | Implementar operaciones modularizadas | Cada función devuelve el resultado correcto para casos de prueba válidos. |
| integrarcalculadoraconvalidacion.py | Integrar calculadora con validación | El módulo devuelve resultados correctos o errores para entradas válidas/inválidas. |
| ejecutarpruebasunitarias.py | Ejecutar pruebas unitarias | Todas las pruebas pasan sin errores. |

## definirestructurademodulos.py
**Tarea:** Definir estructura de módulos
**Criterio:** Los archivos existen y contienen esqueletos válidos en Python.
**Descripción:** Crea tres módulos Python: `calculator.py` con funciones aritméticas, `validator.py` con funciones de validación y `main.py` que los utiliza. Verifica que los archivos existan y contengan las funciones requeridas. Si todo coincide, imprime "CRITERIO OK".

```python
import os
from typing import Tuple

def create_file(path: str, content: str) -> None:
    with open(path, 'w') as f:
        f.write(content)

def create_calculator_module() -> str:
    content = '''# calculator.py
from typing import Union

Number = Union[int, float]

def add(a: Number, b: Number) -> Number:
    return a + b

def subtract(a: Number, b: Number) -> Number:
    return a - b

def multiply(a: Number, b: Number) -> Number:
    return a * b

def divide(a: Number, b: Number) -> Number:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
'''
    return content

def create_validator_module() -> str:
    content = '''# validator.py
from typing import Union, Any

Number = Union[int, float]

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float))

def validate_numbers(a: Any, b: Any) -> bool:
    return is_number(a) and is_number(b)
'''
    return content

def create_main_module() -> str:
    content = '''# main.py
from calculator import add, subtract, multiply, divide
from validator import validate_numbers

def main() -> None:
    a, b = 10, 5
    if not validate_numbers(a, b):
        print("Invalid input")
        return
    print(f"Add: {add(a, b)}")
    print(f"Subtract: {subtract(a, b)}")
    print(f"Multiply: {multiply(a, b)}")
    print(f"Divide: {divide(a, b)}")

if __name__ == "__main__":
    main()
'''
    return content

def check_criteria() -> Tuple[bool, str]:
    required_files = {
        'calculator.py': [
            'def add',
            'def subtract',
            'def multiply',
            'def divide'
        ],
        'validator.py': [
            'def is_number',
            'def validate_numbers'
        ],
        'main.py': [
            'from calculator import',
            'from validator import',
            'if __name__ == "__main__"'
        ]
    }
    for filename, expected_strings in required_files.items():
        if not os.path.exists(filename):
            return False, f"Missing file: {filename}"
        with open(filename, 'r') as f:
            content = f.read()
        for expected in expected_strings:
            if expected not in content:
                return False, f"Missing '{expected}' in {filename}"
    return True, ""

if __name__ == '__main__':
    create_file('calculator.py', create_calculator_module())
    create_file('validator.py', create_validator_module())
    create_file('main.py', create_main_module())

    passed, detail = check_criteria()
    if passed:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {detail}')
if __name__ == '__main__':
    pass
```

## implementarvalidaciondetipos.py
**Tarea:** Implementar validación de tipos
**Criterio:** La función devuelve False para entradas no numéricas y True para numéricas.
**Descripción:** Verifica si un valor es numérico (int o float) excluyendo booleanos. La función `validate_type` utiliza `is_number` para realizar esta comprobación. El script ejecuta tests que confirman el retorno correcto para valores numéricos y no numéricos.

```python
from typing import Any

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def validate_type(input_value: Any) -> bool:
    return is_number(input_value)

def run_tests() -> bool:
    test_cases = [
        (42, True),
        (3.14, True),
        (0, True),
        (-7, True),
        (-2.5, True),
        ("hello", False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
    ]
    for value, expected in test_cases:
        if validate_type(value) != expected:
            return False, f"Failed for input: {value}"
    return True, ""

if __name__ == '__main__':
    passed, detail = run_tests()
    if passed:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {detail}')
```

## implementaroperacionesmodularizadas.py
**Tarea:** Implementar operaciones modularizadas
**Criterio:** Cada función devuelve el resultado correcto para casos de prueba válidos.
**Descripción:** Define funciones para operaciones aritméticas básicas (suma, resta, multiplicación y división) con validación de división por cero. Incluye utilidades para verificar si un valor es numérico. Ejecuta pruebas unitarias que validan los resultados y el manejo de excepciones, informando el estado final.

```python
from typing import Union, Any, Tuple

Number = Union[int, float]

def add(a: Number, b: Number) -> Number:
    return a + b

def subtract(a: Number, b: Number) -> Number:
    return a - b

def multiply(a: Number, b: Number) -> Number:
    return a * b

def divide(a: Number, b: Number) -> Number:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float))

def validate_numbers(a: Any, b: Any) -> bool:
    return is_number(a) and is_number(b)

def run_tests() -> Tuple[bool, str]:
    tests = [
        (add(10, 5), 15, "add"),
        (subtract(10, 5), 5, "subtract"),
        (multiply(10, 5), 50, "multiply"),
        (divide(10, 5), 2.0, "divide"),
    ]
    for result, expected, name in tests:
        if result != expected:
            return False, f"{name} expected {expected}, got {result}"
    try:
        divide(1, 0)
        return False, "divide should raise ValueError"
    except ValueError:
        pass
    return True, ""

if __name__ == '__main__':
    passed, detail = run_tests()
    if passed:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {detail}')
```

## integrarcalculadoraconvalidacion.py
**Tarea:** Integrar calculadora con validación
**Criterio:** El módulo devuelve resultados correctos o errores para entradas válidas/inválidas.
**Descripción:** Define funciones para validar números (excluyendo booleanos) y realizar operaciones aritméticas básicas con verificación de tipos. La función `calculate` ejecuta la operación indicada sobre dos operandos validados, lanzando excepciones para entradas inválidas. El bloque de pruebas verifica el comportamiento con casos válidos, inválidos y de error.

```python
from typing import Any, Tuple, Union

Number = Union[int, float]

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def validate_type(value: Any) -> bool:
    return is_number(value)

def validate_numbers(a: Any, b: Any) -> bool:
    return is_number(a) and is_number(b)

def add(a: Number, b: Number) -> Number:
    return a + b

def subtract(a: Number, b: Number) -> Number:
    return a - b

def multiply(a: Number, b: Number) -> Number:
    return a * b

def divide(a: Number, b: Number) -> Number:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def calculate(operation: str, operands: Any) -> Any:
    if not isinstance(operands, (list, tuple)) or len(operands) != 2:
        raise ValueError("Operands must be a list or tuple of two numbers")
    a, b = operands
    if not validate_numbers(a, b):
        raise ValueError("Operands must be numbers")
    if operation == "add":
        return add(a, b)
    elif operation == "subtract":
        return subtract(a, b)
    elif operation == "multiply":
        return multiply(a, b)
    elif operation == "divide":
        return divide(a, b)
    else:
        raise ValueError("Invalid operation")

def run_tests() -> Tuple[bool, str]:
    test_cases = [
        (42, True),
        (3.14, True),
        (0, True),
        (-7, True),
        (-2.5, True),
        ("hello", False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
    ]
    for value, expected in test_cases:
        if validate_type(value) != expected:
            return False, f"validate_type failed for input: {value}"

    calc_tests = [
        ("add", [10, 5], 15),
        ("subtract", [10, 5], 5),
        ("multiply", [10, 5], 50),
        ("divide", [10, 5], 2.0),
    ]
    for op, operands, expected in calc_tests:
        result = calculate(op, operands)
        if result != expected:
            return False, f"{op} expected {expected}, got {result}"

    try:
        calculate("divide", [1, 0])
        return False, "divide should raise ValueError"
    except ValueError:
        pass

    try:
        calculate("unknown", [1, 2])
        return False, "unknown operation should raise ValueError"
    except ValueError:
        pass

    try:
        calculate("add", [1])
        return False, "invalid operands should raise ValueError"
    except ValueError:
        pass

    try:
        calculate("add", ["a", "b"])
        return False, "non-numeric operands should raise ValueError"
    except ValueError:
        pass

    return True, ""

if __name__ == '__main__':
    passed, detail = run_tests()
    if passed:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {detail}')
```

## ejecutarpruebasunitarias.py
**Tarea:** Ejecutar pruebas unitarias
**Criterio:** Todas las pruebas pasan sin errores.
**Descripción:** Define funciones para validar números reales y realizar operaciones aritméticas básicas (suma, resta, multiplicación y división). La función `calculate` ejecuta la operación indicada sobre dos operandos numéricos validados. El bloque de pruebas verifica el comportamiento de validación y cálculo, incluyendo manejo de errores.

```python
from typing import Any, Tuple, Union

Number = Union[int, float]

def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)

def validate_type(value: Any) -> bool:
    return is_number(value)

def validate_numbers(a: Any, b: Any) -> bool:
    return is_number(a) and is_number(b)

def add(a: Number, b: Number) -> Number:
    return a + b

def subtract(a: Number, b: Number) -> Number:
    return a - b

def multiply(a: Number, b: Number) -> Number:
    return a * b

def divide(a: Number, b: Number) -> Number:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def calculate(operation: str, operands: Any) -> Any:
    if not isinstance(operands, (list, tuple)) or len(operands) != 2:
        raise ValueError("Operands must be a list or tuple of two numbers")
    a, b = operands
    if not validate_numbers(a, b):
        raise ValueError("Operands must be numbers")
    if operation == "add":
        return add(a, b)
    elif operation == "subtract":
        return subtract(a, b)
    elif operation == "multiply":
        return multiply(a, b)
    elif operation == "divide":
        return divide(a, b)
    else:
        raise ValueError("Invalid operation")

def run_tests() -> Tuple[bool, str]:
    test_cases = [
        (42, True),
        (3.14, True),
        (0, True),
        (-7, True),
        (-2.5, True),
        ("hello", False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
    ]
    for value, expected in test_cases:
        if validate_type(value) != expected:
            return False, f"validate_type failed for input: {value}"

    calc_tests = [
        ("add", [10, 5], 15),
        ("subtract", [10, 5], 5),
        ("multiply", [10, 5], 50),
        ("divide", [10, 5], 2.0),
    ]
    for op, operands, expected in calc_tests:
        result = calculate(op, operands)
        if result != expected:
            return False, f"{op} expected {expected}, got {result}"

    try:
        calculate("divide", [1, 0])
        return False, "divide should raise ValueError"
    except ValueError:
        pass

    try:
        calculate("unknown", [1, 2])
        return False, "unknown operation should raise ValueError"
    except ValueError:
        pass

    try:
        calculate("add", [1])
        return False, "invalid operands should raise ValueError"
    except ValueError:
        pass

    try:
        calculate("add", ["a", "b"])
        return False, "non-numeric operands should raise ValueError"
    except ValueError:
        pass

    return True, ""

if __name__ == '__main__':
    passed, detail = run_tests()
    if passed:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {detail}')
```
