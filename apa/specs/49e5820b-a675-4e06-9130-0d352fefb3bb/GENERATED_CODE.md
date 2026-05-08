# Código generado — 49e5820b-a675-4e06-9130-0d352fefb3bb

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| utils/validators.py | Crear utils/validators.py |  |
| crearutilsoperationspy.py | Crear utils/operations.py |  |

## utils/validators.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define una función que verifica si un valor es numérico (int o float) excluyendo booleanos. Crea el directorio 'utils' y ejecuta tests de validación. Si todos los tests pasan, imprime 'CRITERIO OK'; de lo contrario, muestra los resultados fallidos.

```python
import os

def es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)

if __name__ == '__main__':
    os.makedirs('utils', exist_ok=True)
    tests = [
        es_numero(1),
        es_numero(1.5),
        not es_numero('1'),
        not es_numero(None),
        not es_numero([1]),
        not es_numero(True)
    ]
    if all(tests):
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {tests}')

if __name__ == '__main__':
    pass
```

## crearutilsoperationspy.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define funciones para sumar y restar números validando que ambos argumentos sean int o float (excluyendo bool). Maneja errores lanzando ValueError si los operandos no son numéricos. El bloque principal ejecuta tests de operación y verificación de excepciones.

```python
import os

def es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)

def sumar(a, b):
    if es_numero(a) and es_numero(b):
        return a + b
    raise ValueError("Ambos argumentos deben ser números")

def restar(a, b):
    if es_numero(a) and es_numero(b):
        return a - b
    raise ValueError("Ambos argumentos deben ser números")

if __name__ == '__main__':
    tests = [
        sumar(5, 3) == 8,
        restar(10, 4) == 6,
        True,  # placeholder para los errores de ValueError
        True   # placeholder para los errores de ValueError
    ]
    try:
        sumar("a", 1)
        tests[2] = False
    except ValueError:
        pass
    try:
        restar(1, "b")
        tests[3] = False
    except ValueError:
        pass

    if all(tests):
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: {tests}')
```
