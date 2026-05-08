# Código generado — a8d84f40-2a54-40ef-9f8d-f304a5269eb3

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y tiene la firma esperada |
| validar_resultado_con_caso_de_prueba.py | Validar resultado con caso de prueba | suma(2, 3) retorna exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la firma esperada
**Descripción:** La función suma recibe dos enteros y devuelve su suma. El bloque principal ejecuta pruebas básicas para verificar que la función cumple con el criterio de aceptación y muestra si pasó o falló.

```python
def suma(a: int, b: int) -> int:
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
**Criterio:** suma(2, 3) retorna exactamente 5
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque principal ejecuta una prueba automática que verifica si suma(2, 3) produce exactamente 5 e imprime "CRITERIO OK" si la condición se cumple o un mensaje de error detallado en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: suma(2, 3) retornó {resultado}, se esperaba 5')
```
