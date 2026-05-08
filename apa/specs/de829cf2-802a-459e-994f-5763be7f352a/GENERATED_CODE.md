# Código generado — de829cf2-802a-459e-994f-5763be7f352a

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| utils/validators.py | Crear utils/validators.py |  |

## utils/validators.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función `es_numero` que verifica si un valor es de tipo entero o flotante, excluyendo booleanos. Crea el directorio 'utils' y ejecuta tests para validar el comportamiento de la función. Informa los casos fallidos o confirma que todos los tests pasaron correctamente.

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
