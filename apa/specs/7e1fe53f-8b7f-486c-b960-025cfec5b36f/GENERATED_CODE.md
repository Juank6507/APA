# Código generado — 7e1fe53f-8b7f-486c-b960-025cfec5b36f

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definirestructurademodulos.py | Definir estructura de módulos | Se verifica la existencia de los directorios y archivos principales (ej: operations/, validation/, main.py). |
| implementarvalidaciondetipos.py | Implementar validación de tipos | La función devuelve True para entradas válidas y lanza excepción para entradas inválidas (ej: string en lugar de número). |
| implementaroperacionesmodularizadas.py | Implementar operaciones modularizadas | Cada función recibe dos números y devuelve el resultado correcto (ej: add(2,3) == 5). |
| integrarvalidacionyoperaciones.py | Integrar validación y operaciones | La función principal ejecuta operaciones solo si los tipos son válidos; caso contrario, lanza error. |
| ejecutarpruebasunitarias.py | Ejecutar pruebas unitarias | Todas las pruebas unitarias pasan sin errores. |

## definirestructurademodulos.py
**Tarea:** Definir estructura de módulos
**Criterio:** Se verifica la existencia de los directorios y archivos principales (ej: operations/, validation/, main.py).
**Descripción:** Crea la estructura de directorios y archivos necesarios para un proyecto, incluyendo las carpetas 'operations' y 'validation' con sus __init__.py, y el archivo 'main.py'. Verifica si esta estructura existe correctamente y reporta los elementos faltantes en caso de incompletitud. El script genera la estructura al ejecutarse y valida su creación exitosa.

```python
import os

def create_structure():
    os.makedirs('operations', exist_ok=True)
    os.makedirs('validation', exist_ok=True)
    open('main.py', 'w').close()
    open('operations/__init__.py', 'w').close()
    open('validation/__init__.py', 'w').close()

def check_structure():
    dirs_ok = os.path.isdir('operations') and os.path.isdir('validation')
    files_ok = os.path.isfile('main.py')
    ops_init = os.path.isfile('operations/__init__.py')
    val_init = os.path.isfile('validation/__init__.py')
    return dirs_ok and files_ok and ops_init and val_init

if __name__ == '__main__':
    create_structure()
    if check_structure():
        print('CRITERIO OK')
    else:
        missing = []
        if not os.path.isdir('operations'): missing.append('operations/')
        if not os.path.isdir('validation'): missing.append('validation/')
        if not os.path.isfile('main.py'): missing.append('main.py')
        if not os.path.isfile('operations/__init__.py'): missing.append('operations/__init__.py')
        if not os.path.isfile('validation/__init__.py'): missing.append('validation/__init__.py')
        print(f'CRITERIO FALLO: {", ".join(missing)}')
```

## implementarvalidaciondetipos.py
**Tarea:** Implementar validación de tipos
**Criterio:** La función devuelve True para entradas válidas y lanza excepción para entradas inválidas (ej: string en lugar de número).
**Descripción:** El script crea una estructura de carpetas y archivos vacíos para simular un paquete Python, define una función `validate_input` que verifica si un valor es un número (int o float) y no un booleano, lanzando `TypeError` en caso contrario, y luego ejecuta pruebas en `__main__` para verificar que la función devuelve `True` para entradas válidas y lanza la excepción esperada para entradas inválidas, además de comprobar que la estructura de directorios y archivos se haya creado correctamente.

```python
import os

# Copiadas de T1 para autocontenido
def create_structure():
    os.makedirs('operations', exist_ok=True)
    os.makedirs('validation', exist_ok=True)
    open('main.py', 'w').close()
    open('operations/__init__.py', 'w').close()
    open('validation/__init__.py', 'w').close()

def check_structure():
    dirs_ok = os.path.isdir('operations') and os.path.isdir('validation')
    files_ok = os.path.isfile('main.py')
    ops_init = os.path.isfile('operations/__init__.py')
    val_init = os.path.isfile('validation/__init__.py')
    return dirs_ok and files_ok and ops_init and val_init

# --- Implementación de la tarea ---

def validate_input(value):
    """
    Valida que el input sea un número (int o float, no bool).
    Lanza TypeError si el tipo es inválido.
    Devuelve True si es válido.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Tipo inválido: {type(value).__name__}, se esperaba número")
    return True

# --- Pruebas en __main__ ---

if __name__ == '__main__':
    create_structure()

    # Criterio de aceptación: devuelve True para entradas válidas y lanza excepción para inválidas
    try:
        assert validate_input(42) is True
        assert validate_input(3.14) is True
        # Debe lanzar excepción
        try:
            validate_input("hola")
            print('CRITERIO FALLO: no se lanzó excepción para string')
        except TypeError:
            pass  # Esperado
        # Debe lanzar excepción
        try:
            validate_input([1, 2])
            print('CRITERIO FALLO: no se lanzó excepción para lista')
        except TypeError:
            pass  # Esperado
        # Debe lanzar excepción (bool no es número válido aquí)
        try:
            validate_input(True)
            print('CRITERIO FALLO: no se lanzó excepción para bool')
        except TypeError:
            pass  # Esperado
        print('CRITERIO OK')
    except AssertionError:
        print('CRITERIO FALLO: validación falló para entrada válida')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')

    if check_structure():
        print('ESTRUCTURA OK')
    else:
        missing = []
        if not os.path.isdir('operations'): missing.append('operations/')
        if not os.path.isdir('validation'): missing.append('validation/')
        if not os.path.isfile('main.py'): missing.append('main.py')
        if not os.path.isfile('operations/__init__.py'): missing.append('operations/__init__.py')
        if not os.path.isfile('validation/__init__.py'): missing.append('validation/__init__.py')
        print(f'ESTRUCTURA FALLO: {", ".join(missing)}')
```

## implementaroperacionesmodularizadas.py
**Tarea:** Implementar operaciones modularizadas
**Criterio:** Cada función recibe dos números y devuelve el resultado correcto (ej: add(2,3) == 5).
**Descripción:** Crea la estructura de carpetas y archivos necesarios para un proyecto modular con operaciones aritméticas. Implementa funciones de suma, resta, multiplicación y división con validación de división por cero. Ejecuta comprobaciones de estructura y pruebas unitarias para validar el funcionamiento.

```python
import os

def create_structure():
    os.makedirs('operations', exist_ok=True)
    os.makedirs('validation', exist_ok=True)
    open('main.py', 'w').close()
    open('operations/__init__.py', 'w').close()
    open('validation/__init__.py', 'w').close()

def check_structure():
    dirs_ok = os.path.isdir('operations') and os.path.isdir('validation')
    files_ok = os.path.isfile('main.py')
    ops_init = os.path.isfile('operations/__init__.py')
    val_init = os.path.isfile('validation/__init__.py')
    return dirs_ok and files_ok and ops_init and val_init

# Implementación de operaciones modularizadas
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

if __name__ == '__main__':
    create_structure()
    if check_structure():
        print('CRITERIO OK')
    else:
        missing = []
        if not os.path.isdir('operations'): missing.append('operations/')
        if not os.path.isdir('validation'): missing.append('validation/')
        if not os.path.isfile('main.py'): missing.append('main.py')
        if not os.path.isfile('operations/__init__.py'): missing.append('operations/__init__.py')
        if not os.path.isfile('validation/__init__.py'): missing.append('validation/__init__.py')
        print(f'CRITERIO FALLO: {", ".join(missing)}')

    # Criterio de aceptación: test de las funciones de operaciones
    tests = [
        (add(2, 3), 5),
        (subtract(10, 4), 6),
        (multiply(3, 7), 21),
        (divide(10, 2), 5.0),
    ]
    all_ok = True
    for result, expected in tests:
        if result != expected:
            all_ok = False
            break
    # Test de división por cero
    try:
        divide(1, 0)
        all_ok = False
    except ValueError:
        pass

    if all_ok:
        print('CRITERIO OK')
    else:
        print('CRITERIO FALLO: operaciones')
```

## integrarvalidacionyoperaciones.py
**Tarea:** Integrar validación y operaciones
**Criterio:** La función principal ejecuta operaciones solo si los tipos son válidos; caso contrario, lanza error.
**Descripción:** Crea la estructura de carpetas y archivos necesarios para el proyecto. Implementa funciones de validación y operaciones aritméticas básicas, asegurando que los operandos sean números excluyendo booleanos. Ejecuta pruebas de operación y validación, informando el resultado del criterio de aceptación y la integridad estructural.

```python
import os

# Copiadas de T1 para autocontenido
def create_structure():
    os.makedirs('operations', exist_ok=True)
    os.makedirs('validation', exist_ok=True)
    open('main.py', 'w').close()
    open('operations/__init__.py', 'w').close()
    open('validation/__init__.py', 'w').close()

def check_structure():
    dirs_ok = os.path.isdir('operations') and os.path.isdir('validation')
    files_ok = os.path.isfile('main.py')
    ops_init = os.path.isfile('operations/__init__.py')
    val_init = os.path.isfile('validation/__init__.py')
    return dirs_ok and files_ok and ops_init and val_init

# --- Implementación de la tarea ---

def validate_input(value):
    """
    Valida que el input sea un número (int o float, no bool).
    Lanza TypeError si el tipo es inválido.
    Devuelve True si es válido.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Tipo inválido: {type(value).__name__}, se esperaba número")
    return True

def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def calculate(operation, a, b):
    """
    Ejecuta una operación después de validar tipos de entrada.
    Lanza TypeError si los operandos no son válidos.
    """
    validate_input(a)
    validate_input(b)
    ops = {
        'add': add,
        'subtract': subtract,
        'multiply': multiply,
        'divide': divide,
    }
    if operation not in ops:
        raise ValueError(f"Operación no soportada: {operation}")
    return ops[operation](a, b)

if __name__ == '__main__':
    create_structure()

    # Criterio de aceptación: calculate ejecuta operaciones solo con tipos válidos; lanza error cualquier otro.
    all_ok = True

    # Operaciones válidas
    try:
        if calculate('add', 2, 3) != 5:
            all_ok = False
        if calculate('subtract', 10, 4) != 6:
            all_ok = False
        if calculate('multiply', 3, 7) != 21:
            all_ok = False
        if calculate('divide', 10, 2) != 5.0:
            all_ok = False
    except Exception:
        all_ok = False

    # Validación de tipos: bool debe lanzar TypeError
    try:
        calculate('add', True, 1)
        all_ok = False
    except TypeError:
        pass

    # Validación de tipos: string debe lanzar TypeError
    try:
        calculate('add', "hola", 1)
        all_ok = False
    except TypeError:
        pass

    # Validación de tipos: lista debe lanzar TypeError
    try:
        calculate('add', [1], 1)
        all_ok = False
    except TypeError:
        pass

    # Operación no soportada debe lanzar ValueError
    try:
        calculate('mod', 10, 3)
        all_ok = False
    except ValueError:
        pass

    if all_ok:
        print('CRITERIO OK')
    else:
        print('CRITERIO FALLO: operaciones o validación')

    if check_structure():
        print('ESTRUCTURA OK')
    else:
        missing = []
        if not os.path.isdir('operations'): missing.append('operations/')
        if not os.path.isdir('validation'): missing.append('validation/')
        if not os.path.isfile('main.py'): missing.append('main.py')
        if not os.path.isfile('operations/__init__.py'): missing.append('operations/__init__.py')
        if not os.path.isfile('validation/__init__.py'): missing.append('validation/__init__.py')
        print(f'ESTRUCTURA FALLO: {", ".join(missing)}')
```

## ejecutarpruebasunitarias.py
**Tarea:** Ejecutar pruebas unitarias
**Criterio:** Todas las pruebas unitarias pasan sin errores.
**Descripción:** Crea la estructura de carpetas y archivos necesarios para el proyecto. Implementa funciones de cálculo con validación estricta de tipos que rechaza booleanos, cadenas y listas. Ejecuta pruebas unitarias para verificar operaciones aritméticas y manejo de errores, además de comprobar la estructura del proyecto.

```python
import os

# Copiadas de T1 para autocontenido
def create_structure():
    os.makedirs('operations', exist_ok=True)
    os.makedirs('validation', exist_ok=True)
    open('main.py', 'w').close()
    open('operations/__init__.py', 'w').close()
    open('validation/__init__.py', 'w').close()

def check_structure():
    dirs_ok = os.path.isdir('operations') and os.path.isdir('validation')
    files_ok = os.path.isfile('main.py')
    ops_init = os.path.isfile('operations/__init__.py')
    val_init = os.path.isfile('validation/__init__.py')
    return dirs_ok and files_ok and ops_init and val_init

# --- Implementación de la tarea ---

def validate_input(value):
    """
    Valida que el input sea un número (int o float, no bool).
    Lanza TypeError si el tipo es inválido.
    Devuelve True si es válido.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Tipo inválido: {type(value).__name__}, se esperaba número")
    return True

def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def calculate(operation, a, b):
    """
    Ejecuta una operación después de validar tipos de entrada.
    Lanza TypeError si los operandos no son válidos.
    """
    validate_input(a)
    validate_input(b)
    ops = {
        'add': add,
        'subtract': subtract,
        'multiply': multiply,
        'divide': divide,
    }
    if operation not in ops:
        raise ValueError(f"Operación no soportada: {operation}")
    return ops[operation](a, b)

if __name__ == '__main__':
    create_structure()

    # Criterio de aceptación: calculate ejecuta operaciones solo con tipos válidos; lanza error cualquier otro.
    all_ok = True

    # Operaciones válidas
    try:
        if calculate('add', 2, 3) != 5:
            all_ok = False
        if calculate('subtract', 10, 4) != 6:
            all_ok = False
        if calculate('multiply', 3, 7) != 21:
            all_ok = False
        if calculate('divide', 10, 2) != 5.0:
            all_ok = False
    except Exception:
        all_ok = False

    # Validación de tipos: bool debe lanzar TypeError
    try:
        calculate('add', True, 1)
        all_ok = False
    except TypeError:
        pass

    # Validación de tipos: string debe lanzar TypeError
    try:
        calculate('add', "hola", 1)
        all_ok = False
    except TypeError:
        pass

    # Validación de tipos: lista debe lanzar TypeError
    try:
        calculate('add', [1], 1)
        all_ok = False
    except TypeError:
        pass

    # Operación no soportada debe lanzar ValueError
    try:
        calculate('mod', 10, 3)
        all_ok = False
    except ValueError:
        pass

    if all_ok:
        print('CRITERIO OK')
    else:
        print('CRITERIO FALLO: operaciones o validación')

    if check_structure():
        print('ESTRUCTURA OK')
    else:
        missing = []
        if not os.path.isdir('operations'): missing.append('operations/')
        if not os.path.isdir('validation'): missing.append('validation/')
        if not os.path.isfile('main.py'): missing.append('main.py')
        if not os.path.isfile('operations/__init__.py'): missing.append('operations/__init__.py')
        if not os.path.isfile('validation/__init__.py'): missing.append('validation/__init__.py')
        print(f'ESTRUCTURA FALLO: {", ".join(missing)}')
```
