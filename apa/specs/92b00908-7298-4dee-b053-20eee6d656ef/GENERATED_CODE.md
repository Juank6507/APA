# Código generado — 92b00908-7298-4dee-b053-20eee6d656ef

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función debe compilar sin errores y aceptar dos parámetros enteros |
| verificar_suma2_3.py | Verificar suma(2, 3) | El resultado de suma(2, 3) debe ser exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función debe compilar sin errores y aceptar dos parámetros enteros
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque if __name__ == '__main__' ejecuta pruebas automáticas que verifican el comportamiento con enteros positivos, negativos, cero y combinaciones, imprimiendo 'CRITERIO OK' si todas pasan o 'CRITERIO FALLO' si alguna falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test con enteros positivos
        assert suma(2, 3) == 5
        # Test con enteros negativos
        assert suma(-1, -1) == -2
        # Test con cero
        assert suma(0, 0) == 0
        # Test con mixto
        assert suma(-5, 5) == 0
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_suma2_3.py
**Tarea:** Verificar suma(2, 3)
**Criterio:** El resultado de suma(2, 3) debe ser exactamente 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba que verifica si suma(2, 3) produce 5 e imprime "CRITERIO OK" si la condición se cumple o un mensaje de error detallado en caso contrario.

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
