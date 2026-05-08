# Código generado — 51db1cb7-bc0c-471e-bfce-05cc4a1f9922

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función debe compilar sin errores y tener la firma correcta |
| verificar_resultado_con_caso_de_prueba.py | Verificar resultado con caso de prueba | El resultado de suma(2, 3) debe ser exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función debe compilar sin errores y tener la firma correcta
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque principal ejecuta pruebas automáticas para verificar que la función produzca los resultados esperados y muestra un mensaje indicando si pasaron o fallaron.

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

## verificar_resultado_con_caso_de_prueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** El resultado de suma(2, 3) debe ser exactamente 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba automática que verifica si suma(2, 3) produce exactamente 5 e imprime "CRITERIO OK" si la condición se cumple o un mensaje de error detallado en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: se obtuvo {resultado} en lugar de 5')
```
