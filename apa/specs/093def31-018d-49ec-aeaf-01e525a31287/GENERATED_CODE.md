# Código generado — 093def31-018d-49ec-aeaf-01e525a31287

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearfuncionsuma.py | Crear función suma | None |

## crearfuncionsuma.py
**Tarea:** Crear función suma
**Criterio:** None
**Descripción:** Define una función suma que devuelve la suma de dos valores. El bloque principal ejecuta pruebas automáticas para verificar que la función produce los resultados esperados y muestra si los criterios se cumplen o fallan.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        assert suma(2, 3) == 5
        assert suma(-1, 1) == 0
        assert suma(0, 0) == 0
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
```
