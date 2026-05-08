# Código generado — 9b2b4067-076f-4fd7-9d68-b4a4fb0140a7

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función debe compilar sin errores y tener la firma esperada |
| verificar_suma2_3.py | Verificar suma(2, 3) | El resultado de suma(2, 3) debe ser exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función debe compilar sin errores y tener la firma esperada
**Descripción:** La función suma recibe dos argumentos y devuelve su suma. El bloque if __name__ == '__main__' ejecuta pruebas básicas para verificar que la función cumple con el comportamiento esperado y muestra un mensaje indicando si pasó o falló el criterio de aceptación.

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

## verificar_suma2_3.py
**Tarea:** Verificar suma(2, 3)
**Criterio:** El resultado de suma(2, 3) debe ser exactamente 5
**Descripción:** Define una función suma que devuelve la suma de dos números. Al ejecutarse como script principal comprueba que suma(2, 3) devuelve 5 e imprime si el criterio se cumple o falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: resultado fue {resultado}, esperado 5')
```
