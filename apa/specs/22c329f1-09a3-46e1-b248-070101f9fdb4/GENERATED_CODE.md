# Código generado — 22c329f1-09a3-46e1-b248-070101f9fdb4

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** FuncLa función `es_numero` para verificar rá un valor ye número enteiro o float, non str.

```python
import os

def es_numero(valor):
    """Devuelve True si valor es int o float (no str ni otro tipo)."""
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)

if __name__ == '__main__':
    # Crear directorio utils si no existe
    os.makedirs('utils', exist_ok=True)

    # Tests de criterio
    try:
        assert es_numero(5) is True
        assert es_numero(3.14) is True
        assert es_numero('5') is False
        assert es_numero(None) is False
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```
