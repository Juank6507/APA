# Código generado — 63edaf33-1a9c-413a-85e2-6d2cde3e3037

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| utils/validators.py | Crear utils/validators.py |  |
| utils/operations.py | Crear utils/operations.py |  |

## utils/validators.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** La función es_numero verifica si un valor es de tipo numérico (int o float). El bloque principal ejecuta pruebas unitarias para validar que la función distingue correctamente entre números y otros tipos de datos.

```python
import os
import sys

def es_numero(valor):
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    # Criterio de aceptación
    try:
        assert es_numero(5) == True
        assert es_numero(3.14) == True
        assert es_numero("5") == False
        assert es_numero(None) == False
        assert es_numero([1, 2, 3]) == False
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
```

## utils/operations.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define dos funciones que validan y suman o restan dos valores numéricos, lanzando excepción si algún argumento no es número. Al ejecutarse como script ejecuta pruebas unitarias que verifican el comportamiento correcto de ambas operaciones.

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
        assert sumar(2, 3) == 5
        assert restar(5, 2) == 3
        try:
            sumar("a", 2)
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass
        try:
            restar("a", 2)
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```
