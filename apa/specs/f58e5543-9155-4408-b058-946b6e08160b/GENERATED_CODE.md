# Código generado — f58e5543-9155-4408-b058-946b6e08160b

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es de tipo entero o flotante, excluyendo booleanos. El script de prueba valida esta función con casos como números, cadenas y tipos nulos, reportando fallos si no coincide. El bloque principal crea el directorio `utils` para organizar el módulo.

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
    fallos = []
    for valor, esperado in tests:
        if es_numero(valor) != esperado:
            fallos.append(f'input({valor!r}) esperado {esperado}, obtuvo {es_numero(valor)}')
    if fallos:
        print(f'CRITERIO FALLO: {"; ".join(fallos)}')
    else:
        print('CRITERIO OK')

if __name__ == '__main__':
    pass
```
