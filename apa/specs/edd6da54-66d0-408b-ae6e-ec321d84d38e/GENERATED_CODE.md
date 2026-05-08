# Código generado — edd6da54-66d0-408b-ae6e-ec321d84d38e

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y tiene la firma esperada |
| validar_resultado_con_caso_de_prueba.py | Validar resultado con caso de prueba | suma(2, 3) == 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la firma esperada
**Descripción:** Define una función suma que retorna la suma de dos valores. El bloque principal ejecuta pruebas básicas para verificar que la función devuelva los resultados esperados y confirma si cumple el criterio de aceptación.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        assert suma(2, 3) == 5
        assert suma(-1, 1) == 0
        assert suma(0, 0) == 0
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## validar_resultado_con_caso_de_prueba.py
**Tarea:** Validar resultado con caso de prueba
**Criterio:** suma(2, 3) == 5
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque principal ejecuta una prueba automática que verifica si suma(2, 3) produce 5 e imprime "CRITERIO OK" si la condición se cumple o un mensaje de error detallado en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: suma(2, 3) devolvió {resultado}, se esperaba 5')
```
