# Código generado — c83a5390-21fa-466b-8674-e9acc6cdd16c

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| crearutilsoperationspy.py | Crear utils/operations.py |  |
| crearmainpy.py | Crear main.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es de tipo entero o flotante, excluyendo booleanos. El bloque principal ejecuta tests de casos válidos y no válidos, reportando fallos si la función no coincide con los resultados esperados. El código no crea el directorio `utils` relacionado con la tarea.

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
        (False, False),
    ]
    fallos = []
    for valor, esperado in tests:
        if es_numero(valor) != esperado:
            fallos.append(f'valor={valor!r} esperado={esperado} obtenido={es_numero(valor)}')
    if fallos:
        print(f'CRITERIO FALLO: {"; ".join(fallos)}')
    else:
        print('CRITERIO OK')

if __name__ == '__main__':
    pass
```

## crearutilsoperationspy.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define funciones para sumar, restar, multiplicar y dividir validando que los argumentos sean números y que la división no tenga divisor cero. El bloque principal crea un directorio 'utils' y ejecuta pruebas de validación. Si todas pasan, imprime 'CRITERIO OK'.

```python
import os

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
    assert sumar(3, 2) == 5
    assert restar(5, 3) == 2
    assert multiplicar(4, 3) == 12
    assert dividir(10, 2) == 5.0
    try:
        dividir(1, 0)
        assert False, "Debería lanzar ValueError"
    except ValueError:
        pass
    print('CRITERIO OK')
```

## crearmainpy.py
**Tarea:** Crear main.py
**Criterio:** 
**Descripción:** Define funciones para validar números y realizar sumas o restas, verificando que los argumentos no sean booleanos. La función `calcular` ejecuta la operación indicada o lanza un error si no se reconoce. El bloque principal prueba las operaciones válidas y el manejo de errores para una operación no soportada.

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
    try:
        assert calcular('sumar', 3, 2) == 5
        assert calcular('restar', 5, 3) == 2
        try:
            calcular('multiplicar', 2, 3)
            assert False, "Debería lanzar ValueError"
        except ValueError as e:
            assert str(e) == "Operación desconocida"
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
```
