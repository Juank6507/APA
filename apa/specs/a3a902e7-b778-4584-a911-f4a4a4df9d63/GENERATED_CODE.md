# Código generado — a3a902e7-b778-4584-a911-f4a4a4df9d63

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definirestructuradelmodulodelacalculadora.py | Definir estructura del módulo de la calculadora | Los directorios src y tests existen y contienen los archivos iniciales. |
| implementarvalidaciondetiposenoperaciones.py | Implementar validación de tipos en operaciones | La función raise TypeError al recibir un string o None como input. |
| implementaroperacionesaritmeticasmodularizadas.py | Implementar operaciones aritméticas modularizadas | Cada función devuelve el resultado correcto para al menos un caso de prueba y raise error adecuado para división por cero. |
| ejecutarpruebasunitariasinternas.py | Ejecutar pruebas unitarias internas | Todos los tests pasan sin errores ni fallos. |

## definirestructuradelmodulodelacalculadora.py
**Tarea:** Definir estructura del módulo de la calculadora
**Criterio:** Los directorios src y tests existen y contienen los archivos iniciales.
**Descripción:** Crea la estructura de carpetas `src` y `tests` junto con los archivos `calculator.py` y `test_calculator.py` si no existen. Verifica que dichos directorios y archivos estén presentes, devolviendo un estado de éxito o un mensaje de error. Al ejecutarse, imprime si se cumple el criterio de estructura o el detalle del fallo.

```python
import os
from pathlib import Path
from typing import Tuple

def create_structure() -> None:
    base = Path('.')
    src_dir = base / 'src'
    tests_dir = base / 'tests'
    src_dir.mkdir(exist_ok=True)
    tests_dir.mkdir(exist_ok=True)
    (src_dir / 'calculator.py').touch(exist_ok=True)
    (tests_dir / 'test_calculator.py').touch(exist_ok=True)

def check_structure() -> Tuple[bool, str]:
    base = Path('.')
    src_dir = base / 'src'
    tests_dir = base / 'tests'
    if not src_dir.is_dir():
        return False, f"Directorio src no existe"
    if not tests_dir.is_dir():
        return False, f"Directorio tests no existe"
    calc_file = src_dir / 'calculator.py'
    test_file = tests_dir / 'test_calculator.py'
    if not calc_file.is_file():
        return False, f"Archivo {calc_file} no existe"
    if not test_file.is_file():
        return False, f"Archivo {test_file} no existe"
    return True, ""

if __name__ == '__main__':
    create_structure()
    ok, detail = check_structure()
    if ok:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {detail}')
```

## implementarvalidaciondetiposenoperaciones.py
**Tarea:** Implementar validación de tipos en operaciones
**Criterio:** La función raise TypeError al recibir un string o None como input.
**Descripción:** La función `validate_types` verifica que todos los argumentos recibidos sean de tipo `int` o `float`. Si algún argumento no cumple esta condición, lanza un `TypeError` con el nombre del tipo inválido. El bloque principal prueba que al recibir un string y un `None` se active correctamente la excepción.

```python
from typing import Any

def validate_types(*inputs: Any) -> None:
    for value in inputs:
        if not isinstance(value, (int, float)):
            raise TypeError(f"Tipo no permitido: {type(value).__name__}")

if __name__ == '__main__':
    try:
        validate_types("texto", None)
        print('CRITERIO FALLO: No se lanzó TypeError')
    except TypeError:
        print('CRITERIO OK')
```

## implementaroperacionesaritmeticasmodularizadas.py
**Tarea:** Implementar operaciones aritméticas modularizadas
**Criterio:** Cada función devuelve el resultado correcto para al menos un caso de prueba y raise error adecuado para división por cero.
**Descripción:** Define funciones aritméticas (suma, resta, multiplicación y división) que validan tipos numéricos antes de operar. La división además verifica que el divisor no sea cero. El bloque principal prueba las operaciones y confirma que los errores se lanzan correctamente.

```python
from typing import Any

def validate_types(*inputs: Any) -> None:
    for value in inputs:
        if not isinstance(value, (int, float)):
            raise TypeError(f"Tipo no permitido: {type(value).__name__}")

def add(a: float, b: float) -> float:
    validate_types(a, b)
    return a + b

def subtract(a: float, b: float) -> float:
    validate_types(a, b)
    return a - b

def multiply(a: float, b: float) -> float:
    validate_types(a, b)
    return a * b

def divide(a: float, b: float) -> float:
    validate_types(a, b)
    if b == 0:
        raise ZeroDivisionError("División por cero")
    return a / b

if __name__ == '__main__':
    try:
        assert add(2, 3) == 5
        assert subtract(10, 4) == 6
        assert multiply(3, 7) == 21
        assert divide(10, 2) == 5.0
        divide(1, 0)
        print('CRITERIO FALLO: No se lanzó ZeroDivisionError')
    except (AssertionError, ZeroDivisionError, TypeError) as e:
        if isinstance(e, ZeroDivisionError):
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: {e}')
```

## ejecutarpruebasunitariasinternas.py
**Tarea:** Ejecutar pruebas unitarias internas
**Criterio:** Todos los tests pasan sin errores ni fallos.
**Descripción:** Define funciones de validación de tipos y operaciones aritméticas que verifican que los argumentos sean numéricos. Implementa suma, resta, multiplicación y división con comprobación de división por cero. El bloque principal ejecuta pruebas unitarias que validan el funcionamiento y el manejo de errores.

```python
from typing import Any

def validate_types(*inputs: Any) -> None:
    for value in inputs:
        if not isinstance(value, (int, float)):
            raise TypeError(f"Tipo no permitido: {type(value).__name__}")

def add(a: float, b: float) -> float:
    validate_types(a, b)
    return a + b

def subtract(a: float, b: float) -> float:
    validate_types(a, b)
    return a - b

def multiply(a: float, b: float) -> float:
    validate_types(a, b)
    return a * b

def divide(a: float, b: float) -> float:
    validate_types(a, b)
    if b == 0:
        raise ZeroDivisionError("División por cero")
    return a / b

if __name__ == '__main__':
    try:
        assert add(2, 3) == 5
        assert subtract(10, 4) == 6
        assert multiply(3, 7) == 21
        assert divide(10, 2) == 5.0
        divide(1, 0)
        print('CRITERIO FALLO: No se lanzó ZeroDivisionError')
    except (AssertionError, ZeroDivisionError, TypeError) as e:
        if isinstance(e, ZeroDivisionError):
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: {e}')
```
