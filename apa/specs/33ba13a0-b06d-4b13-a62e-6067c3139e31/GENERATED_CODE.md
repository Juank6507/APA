# Código generado — 33ba13a0-b06d-4b13-a62e-6067c3139e31

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y tiene la firma correcta |
| verificar_resultado_con_caso_de_prueba.py | Verificar resultado con caso de prueba | El valor retornado por suma(2, 3) es exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la firma correcta
**Descripción:** Define la función suma que devuelve la suma de dos valores. El bloque principal ejecuta una prueba automática que verifica que la función exista y produzca el resultado esperado para 2 y 3, mostrando si el criterio de aceptación se cumple.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test de criterio de aceptación: función compila y tiene firma correcta
        assert callable(suma), "suma no es callable"
        assert suma(2, 3) == 5, "suma(2,3) no retorna 5"
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_resultado_con_caso_de_prueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** El valor retornado por suma(2, 3) es exactamente 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba que verifica si suma(2, 3) produce exactamente 5 e imprime si el criterio se cumple o falla.

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
