# Código generado — b41196cb-898a-4dfa-ac9c-9c4b6ad13061

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| crearutilsoperationspy.py | Crear utils/operations.py |  |
| crearmainpy.py | Crear main.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es entero o flotante excluyendo booleanos. Crea el directorio `utils` y ejecuta tests para validar el comportamiento de la función. Finalmente, guarda la implementación en `utils/validators.py`.

```python
import os

def es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)

if __name__ == '__main__':
    os.makedirs('utils', exist_ok=True)
    tests = [
        (42, True),
        (3.14, True),
        (0, True),
        (-5, True),
        (-2.5, True),
        ('123', False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
        (False, False)
    ]
    passed = True
    for valor, esperado in tests:
        if es_numero(valor) != esperado:
            passed = False
            print(f'CRITERIO FALLO: es_numero({valor!r}) retornó {es_numero(valor)}, esperado {esperado}')
            break
    if passed:
        print('CRITERIO OK')
    # Guardar en utils/validators.py
    with open('utils/validators.py', 'w') as f:
        f.write('def es_numero(valor):\n')
        f.write('    return isinstance(valor, (int, float)) and not isinstance(valor, bool)\n')

if __name__ == '__main__':
    pass
```

## crearutilsoperationspy.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define funciones básicas de aritmética (sumar, restar, multiplicar, dividir) que validan que los argumentos sean números y manejan errores como división por cero. En el bloque principal crea el directorio 'utils' y ejecuta pruebas de validación de las operaciones. Finaliza con código de salida según el éxito de los tests.

```python
import os
import sys

def es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)

def sumar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a + b

def restar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a - b

def multiplicar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a * b

def dividir(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    if b == 0:
        raise ValueError("No se puede dividir por cero")
    return a / b

if __name__ == '__main__':
    os.makedirs('utils', exist_ok=True)
    passed = True
    try:
        assert sumar(3, 2) == 5
        assert restar(5, 3) == 2
        assert multiplicar(4, 3) == 12
        assert dividir(10, 2) == 5.0
        try:
            dividir(1, 0)
            passed = False
            print('CRITERIO FALLO: dividir(1, 0) debería lanzar ValueError')
        except ValueError:
            pass
        if passed:
            print('CRITERIO OK')
    except AssertionError as e:
        passed = False
        print(f'CRITERIO FALLO: {e}')
    sys.exit(0 if passed else 1)
```

## crearmainpy.py
**Tarea:** Crear main.py
**Criterio:** 
**Descripción:** Define funciones para validar números y realizar sumas o restas, lanzando excepciones si los argumentos no son numéricos válidos. La función `calcular` ejecuta la operación indicada por cadena. El bloque principal prueba casos válidos y el manejo de errores para operaciones no soportadas.

```python
def es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)

def sumar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a + b

def restar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a - b

def calcular(operacion, a, b):
    if operacion == 'sumar':
        return sumar(a, b)
    elif operacion == 'restar':
        return restar(a, b)
    else:
        raise ValueError("Operación desconocida")

if __name__ == '__main__':
    passed = True
    try:
        assert calcular('sumar', 3, 2) == 5
        assert calcular('restar', 5, 3) == 2
        try:
            calcular('multiplicar', 1, 1)
            passed = False
            print('CRITERIO FALLO: Operación desconocida no lanzó ValueError')
        except ValueError:
            pass
        if passed:
            print('CRITERIO OK')
    except AssertionError as e:
        passed = False
        print(f'CRITERIO FALLO: {e}')
```
