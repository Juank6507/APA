# Código generado — 8ad55727-3bf3-4d2b-9bf8-5a5618b8206a

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es de tipo entero o flotante, excluyendo booleanos. Crea el directorio 'utils' y ejecuta tests de validación, reportando fallos si la función no coincide con los resultados esperados. El script imprime 'CRITERIO OK' si todos los tests pasan.

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
