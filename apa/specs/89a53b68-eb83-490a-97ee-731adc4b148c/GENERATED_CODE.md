# Código generado — 89a53b68-eb83-490a-97ee-731adc4b148c

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función debe compilar sin errores y aceptar dos parámetros enteros |
| verificar_suma2_3.py | Verificar suma(2, 3) | suma(2, 3) debe retornar exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función debe compilar sin errores y aceptar dos parámetros enteros
**Descripción:** La función suma recibe dos valores y devuelve su suma. El bloque principal prueba que la función funciona correctamente con los valores 2 y 3, imprimiendo 'CRITERIO OK' si el resultado es 5 o un mensaje de error en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        resultado = suma(2, 3)
        assert resultado == 5
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_suma2_3.py
**Tarea:** Verificar suma(2, 3)
**Criterio:** suma(2, 3) debe retornar exactamente 5
**Descripción:** El código define una función `suma` que devuelve la suma de dos números y luego verifica si `suma(2, 3)` retorna exactamente 5. Si el resultado es correcto, imprime "CRITERIO OK"; de lo contrario, indica el fallo mostrando el valor obtenido.

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
