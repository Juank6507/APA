# Código generado — fed15e48-ea88-4fea-8ae9-33eddb22136a

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función debe compilar sin errores y tener la firma correcta |
| verificar_resultado_con_caso_de_prueba.py | Verificar resultado con caso de prueba | suma(2, 3) debe retornar exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función debe compilar sin errores y tener la firma correcta
**Descripción:** La función `suma` recibe dos valores y devuelve su suma. El bloque de prueba verifica que la función compile y produzca el resultado esperado (5) para los valores 2 y 3, imprimiendo "CRITERIO OK" si la prueba pasa o un mensaje de error si falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test del criterio de aceptación
        resultado = suma(2, 3)
        if resultado == 5:
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: resultado esperado 5, obtenido {resultado}')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_resultado_con_caso_de_prueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** suma(2, 3) debe retornar exactamente 5
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque principal ejecuta una prueba automática que verifica que la suma de 2 y 3 sea exactamente 5, imprimiendo 'CRITERIO OK' si el resultado es correcto o un mensaje de error detallado en caso contrario.

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
