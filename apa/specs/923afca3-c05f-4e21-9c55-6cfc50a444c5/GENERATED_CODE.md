# Código generado — 923afca3-c05f-4e21-9c55-6cfc50a444c5

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define la función es_numero que distingue valores numéricos (int o float) de cualquier otro tipo, excluyendo los booleanos. Al ejecutarse como script crea el archivo utils/validators.py con el mismo código y ejecuta pruebas para verificar que la función clasifica correctamente distintos tipos de datos.

```python
import os
import sys

def es_numero(valor):
    """
    Retorna True si valor es int o float, False en caso contrario.
    """
    # Excluir bool explícitamente porque isinstance(True, int) es True
    if isinstance(valor, bool):
        return False
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    # Crear directorio utils si no existe
    os.makedirs('utils', exist_ok=True)
    
    # Guardar el código actual en utils/validators.py
    with open('utils/validators.py', 'w') as f:
        f.write('''import os
import sys

def es_numero(valor):
    """
    Retorna True si valor es int o float, False en caso contrario.
    """
    # Excluir bool explícitamente porque isinstance(True, int) es True
    if isinstance(valor, bool):
        return False
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    # Crear directorio utils si no existe
    os.makedirs('utils', exist_ok=True)
    
    # Guardar el código actual en utils/validators.py
    with open('utils/validators.py', 'w') as f:
        f.write(open(__file__).read())
    
    # Tests
    tests = [
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
        ('3.14', False),
    ]
    
    fallos = []
    for valor, esperado in tests:
        resultado = es_numero(valor)
        if resultado != esperado:
            fallos.append(f"es_numero({valor!r}) -> {resultado}, esperado {esperado}")
    
    if not fallos:
        print('CRITERIO OK')
    else:
        print('CRITERIO FALLO: ' + '; '.join(fallos))
''')
    
    # Tests
    tests = [
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
        ('3.14', False),
    ]
    
    fallos = []
    for valor, esperado in tests:
        resultado = es_numero(valor)
        if resultado != esperado:
            fallos.append(f"es_numero({valor!r}) -> {resultado}, esperado {esperado}")
    
    if not fallos:
        print('CRITERIO OK')
    else:
        print('CRITERIO FALLO: ' + '; '.join(fallos))
```
