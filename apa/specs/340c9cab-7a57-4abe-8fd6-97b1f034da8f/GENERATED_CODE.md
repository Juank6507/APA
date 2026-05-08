# Código generado — 340c9cab-7a57-4abe-8fd6-97b1f034da8f

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |

## crearutilsvalidatorspy.py
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
