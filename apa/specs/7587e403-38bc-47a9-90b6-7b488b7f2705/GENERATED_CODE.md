# Código generado — 7587e403-38bc-47a9-90b6-7b488b7f2705

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `validate_number` que verifica si un valor es entero o float finito, lanzando `TypeError` para tipos no numéricos y `ValueError` para infinitos o NaN. El bloque principal ejecuta tests de validación para asegurar que la función rechace correctamente entradas inválidas como strings, listas, y valores no finitos. Si todos los tests pasan, imprime "CRITERIO OK".

```python
import os
import sys

def validate_number(value):
    if not isinstance(value, (int, float)):
        raise TypeError("value must be int or float")
    if isinstance(value, float) and (not value == value or abs(value) == float('inf')):
        raise ValueError("value must be a finite float")
    return True

if __name__ == '__main__':
    try:
        # Test 1: int válido
        assert validate_number(5) is True
        # Test 2: float válido
        assert validate_number(3.14) is True
        # Test 3: TypeError por string
        try:
            validate_number("10")
            print("CRITERIO FALLO: TypeError no lanzado para string")
            sys.exit(1)
        except TypeError:
            pass
        # Test 4: TypeError por lista
        try:
            validate_number([1])
            print("CRITERIO FALLO: TypeError no lanzado para lista")
            sys.exit(1)
        except TypeError:
            pass
        # Test 5: ValueError por inf
        try:
            validate_number(float('inf'))
            print("CRITERIO FALLO: ValueError no lanzado para inf")
            sys.exit(1)
        except ValueError:
            pass
        # Test 6: ValueError por -inf
        try:
            validate_number(float('-inf'))
            print("CRITERIO FALLO: ValueError no lanzado para -inf")
            sys.exit(1)
        except ValueError:
            pass
        # Test 7: ValueError por nan
        try:
            validate_number(float('nan'))
            print("CRITERIO FALLO: ValueError no lanzado para nan")
            sys.exit(1)
        except ValueError:
            pass
        print("CRITERIO OK")
    except AssertionError:
        print("CRITERIO FALLO: aserción fallida")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
if __name__=='__main__':
    pass
```
