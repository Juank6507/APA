# Código generado — a7bc8a36-1e04-4afa-9103-43d853b3aaa6

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| utils/validators.py | Crear utils/validators.py |  |

## utils/validators.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es de tipo entero o flotante, excluyendo booleanos. Crea el directorio 'utils' y ejecuta tests de validación, reportando fallos si el resultado no coincide con lo esperado. El script imprime 'CRITERIO OK' si todos los tests pasan o los detalles de los fallos.

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
        (-7, True),
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
            fallos.append(f'valor={valor!r} esperado={esperado} obtenido={es_numero(valor)}')
    if fallos:
        print(f'CRITERIO FALLO: {"; ".join(fallos)}')
    else:
        print('CRITERIO OK')

if __name__ == '__main__':
    pass
```
