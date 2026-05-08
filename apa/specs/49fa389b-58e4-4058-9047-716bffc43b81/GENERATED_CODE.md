# Código generado — 49fa389b-58e4-4058-9047-716bffc43b81

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| utils/validators.py | Crear utils/validators.py |  |
| crearutilsoperationspy.py | Crear utils/operations.py |  |
| crearmainpy.py | Crear main.py |  |

## utils/validators.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es de tipo entero o flotante. El bloque principal ejecuta tests de validación para asegurar que la función identifique correctamente números y rechace otros tipos. En caso de fallos, imprime los errores; si todo pasa, muestra "CRITERIO OK".

```python
import os

def es_numero(valor):
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    os.makedirs('utils', exist_ok=True)
    tests = [
        (5, True),
        (5.0, True),
        (0, True),
        (-3, True),
        (-2.5, True),
        ('5', False),
        (None, False),
        ([], False),
        ({}, False),
    ]
    fallos = []
    for valor, esperado in tests:
        if es_numero(valor) != esperado:
            fallos.append(f'Input({valor!r}) esperado={esperado} obtenido={es_numero(valor)}')
    if fallos:
        print(f'CRITERIO FALLO: {fallos}')
    else:
        print('CRITERIO OK')

if __name__ == '__main__':
    pass
```

## crearutilsoperationspy.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define funciones para sumar y restar números validando que ambos argumentos sean int o float. Lanza ValueError si los argumentos no son numéricos. El bloque principal prueba las operaciones con casos válidos y de error.

```python
import os

def es_numero(valor):
    return isinstance(valor, (int, float))

def sumar(a, b):
    if es_numero(a) and es_numero(b):
        return a + b
    raise ValueError("Ambos argumentos deben ser números")

def restar(a, b):
    if es_numero(a) and es_numero(b):
        return a - b
    raise ValueError("Ambos argumentos deben ser números")

if __name__ == '__main__':
    try:
        assert sumar(5, 3) == 8
        assert sumar(-1, 1) == 0
        assert restar(5, 3) == 2
        assert restar(3, 5) == -2
        try:
            sumar("a", 1)
            assert False, "Expected ValueError"
        except ValueError:
            pass
        try:
            restar(1, "b")
            assert False, "Expected ValueError"
        except ValueError:
            pass
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## crearmainpy.py
**Tarea:** Crear main.py
**Criterio:** 
**Descripción:** Define funciones para validar números y realizar sumas o restas, lanzando excepciones si los argumentos no son numéricos o la operación es inválida. El bloque principal prueba las operaciones de suma y resta y verifica que se manejen correctamente los errores. Imprime 'CRITERIO OK' si todas las pruebas pasan.

```python
import os
import sys

def es_numero(valor):
    return isinstance(valor, (int, float))

def sumar(a, b):
    if es_numero(a) and es_numero(b):
        return a + b
    raise ValueError("Ambos argumentos deben ser números")

def restar(a, b):
    if es_numero(a) and es_numero(b):
        return a - b
    raise ValueError("Ambos argumentos deben ser números")

def calcular(operacion, a, b):
    if operacion == 'sumar':
        return sumar(a, b)
    elif operacion == 'restar':
        return restar(a, b)
    else:
        raise ValueError(f"Operación desconocida: {operacion}")

if __name__ == '__main__':
    try:
        assert calcular('sumar', 5, 3) == 8
        assert calcular('restar', 5, 3) == 2

        try:
            calcular('multiplicar', 5, 3)
            print('CRITERIO FALLO: Se esperaba ValueError para operación desconocida')
        except ValueError:
            pass

        print('CRITERIO OK')
    except AssertionError:
        print('CRITERIO FALLO: Las operaciones aritméticas no funcionan correctamente')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```
