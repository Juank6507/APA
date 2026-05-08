# Código generado — 4262bc23-a324-483f-80da-9966e22d098b

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementarfuncionsuma.py | Implementar función suma | La función suma existe y acepta exactamente dos parámetros |
| verificarsuma23.py | Verificar suma(2,3) | El resultado de suma(2,3) es exactamente 5 |

## implementarfuncionsuma.py
**Tarea:** Implementar función suma
**Criterio:** La función suma existe y acepta exactamente dos parámetros
**Descripción:** La función suma recibe dos argumentos y devuelve su suma. El bloque principal verifica mediante introspección que la función esté definida con exactamente dos parámetros y muestra "CRITERIO OK" si cumple la condición o un mensaje de error detallado en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    import inspect
    sig = inspect.signature(suma)
    params = list(sig.parameters.keys())
    if len(params) == 2:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: se esperaban 2 parámetros, se encontraron {len(params)}')
```

## verificarsuma23.py
**Tarea:** Verificar suma(2,3)
**Criterio:** El resultado de suma(2,3) es exactamente 5
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque principal ejecuta una prueba unitaria que verifica que suma(2, 3) produce exactamente 5, imprimiendo 'CRITERIO OK' si la condición se cumple o un mensaje de error detallado en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: resultado={resultado}, esperado=5')
```
