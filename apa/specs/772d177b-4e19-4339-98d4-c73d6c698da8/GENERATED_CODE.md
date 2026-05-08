# Código generado — 772d177b-4e19-4339-98d4-c73d6c698da8

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** La función es_numero verifica si un valor es un número (int o float) excluyendo booleanos. El script incluye pruebas automatizadas que validan el comportamiento esperado y muestran "CRITERIO OK" si todas pasan o "CRITERIO FALLO" con detalles si alguna falla.

```python
import os
import sys

def es_numero(valor):
    # Excluir bool explícitamente porque isinstance(True, int) es True
    if isinstance(valor, bool):
        return False
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    tests = [
        (5, True),
        (3.14, True),
        ("5", False),
        (None, False),
        ([], False),
        (True, False)
    ]
    try:
        for valor, esperado in tests:
            resultado = es_numero(valor)
            assert resultado == esperado, f"es_numero({valor!r}) devolvió {resultado}, se esperaba {esperado}"
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
```
