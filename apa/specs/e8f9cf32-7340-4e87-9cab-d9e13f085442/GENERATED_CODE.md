# Código generado — e8f9cf32-7340-4e87-9cab-d9e13f085442

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementarfuncionsuma.py | Implementar función suma | La función debe compilar sin errores y tener la firma suma(a, b) |
| verificarsuma23.py | Verificar suma(2, 3) | suma(2, 3) debe retornar exactamente 5 |

## implementarfuncionsuma.py
**Tarea:** Implementar función suma
**Criterio:** La función debe compilar sin errores y tener la firma suma(a, b)
**Descripción:** La función suma(a, b) devuelve la suma de dos valores numéricos. El bloque if __name__ == '__main__' ejecuta pruebas automáticas que verifican el comportamiento con números positivos, negativos y ceros, mostrando 'CRITERIO OK' si todas pasan o 'CRITERIO FALLO' si alguna falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test básico
        resultado = suma(2, 3)
        assert resultado == 5, f"suma(2, 3) esperaba 5, obtuvo {resultado}"
        
        # Test con negativos
        resultado = suma(-1, 1)
        assert resultado == 0, f"suma(-1, 1) esperaba 0, obtuvo {resultado}"
        
        # Test con ceros
        resultado = suma(0, 0)
        assert resultado == 0, f"suma(0, 0) esperaba 0, obtuvo {resultado}"
        
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificarsuma23.py
**Tarea:** Verificar suma(2, 3)
**Criterio:** suma(2, 3) debe retornar exactamente 5
**Descripción:** La función suma(a, b) devuelve la suma de dos números. El bloque principal ejecuta una prueba automática que verifica si suma(2, 3) produce exactamente 5 e imprime "CRITERIO OK" si la condición se cumple o un mensaje de error detallado si falla.

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
