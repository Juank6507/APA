# Código generado — be99d398-1ec1-423c-84e0-f55530a0a461

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| utils/operations.py | Crear utils/operations.py |  |
| main.py | Crear main.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** La función es_numero verifica si un valor es un número (int o float) excluyendo booleanos. El script incluye pruebas automatizadas que validan el comportamiento esperado y terminan con código de error si alguna falla.

```python
import os
import sys

def es_numero(valor):
    # Excluir bool explícitamente porque isinstance(True, int) es True
    if isinstance(valor, bool):
        return False
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    # Test cases
    test_cases = [
        (5, True),
        (3.14, True),
        (0, True),
        (-7, True),
        (-2.5, True),
        ('5', False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
    ]
    
    try:
        for valor, expected in test_cases:
            result = es_numero(valor)
            if result != expected:
                print(f'CRITERIO FALLO: es_numero({valor}) devolvió {result}, se esperaba {expected}')
                sys.exit(1)
        
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
        sys.exit(1)
```

## utils/operations.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define dos funciones, sumar y restar, que validan sus argumentos con es_numero y lanzan ValueError si no son numéricos. El bloque principal ejecuta pruebas automáticas que verifican el comportamiento correcto con entradas válidas e inválidas.

```python
from utils.validators import es_numero

def sumar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a + b

def restar(a, b):
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a - b

if __name__ == '__main__':
    try:
        # Test sumar con números válidos
        assert sumar(3, 5) == 8
        assert sumar(2.5, 1.5) == 4.0
        
        # Test restar con números válidos
        assert restar(10, 4) == 6
        assert restar(7.5, 2.5) == 5.0
        
        # Test con argumentos no numéricos
        try:
            sumar("a", 3)
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass
        
        try:
            restar(3, None)
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass
        
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## main.py
**Tarea:** Crear main.py
**Criterio:** 
**Descripción:** El script main.py importa las funciones sumar y restar desde utils.operations y define una función calcular que ejecuta la operación solicitada entre dos números, devolviendo un mensaje de error si la operación no es válida. Al ejecutarse como script principal, valida el comportamiento mediante assertions y muestra "CRITERIO OK" si todas las pruebas pasan.

```python
# utils/operations.py
def sumar(a, b):
    return a + b

def restar(a, b):
    return a - b

# main.py
from utils.operations import sumar, restar

def calcular(operacion, a, b):
    try:
        if operacion == 'sumar':
            return sumar(a, b)
        elif operacion == 'restar':
            return restar(a, b)
        else:
            raise ValueError("Operación desconocida")
    except ValueError as e:
        return f"Error: {e}"

if __name__ == '__main__':
    try:
        assert calcular('sumar', 5, 3) == 8
        assert calcular('restar', 5, 3) == 2
        assert calcular('multiplicar', 5, 3) == "Error: Operación desconocida"
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```
