# Código generado — 8742c230-e489-4661-80b6-aeef9a6ff822

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| utils/validators.py | Crear utils/validators.py |  |

## utils/validators.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** La función es_numero verifica si un valor es de tipo numérico (int o float). El bloque principal ejecuta pruebas unitarias para validar el comportamiento esperado y muestra un mensaje indicando si todas las pruebas pasaron o no.

```python
import os
import sys

def es_numero(valor):
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    try:
        assert es_numero(5) is True
        assert es_numero(3.14) is True
        assert es_numero('5') is False
        assert es_numero(None) is False
        assert es_numero([1, 2, 3]) is False
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
```
