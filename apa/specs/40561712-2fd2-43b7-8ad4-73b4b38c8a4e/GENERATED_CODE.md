# Código generado — 40561712-2fd2-43b7-8ad4-73b4b38c8a4e

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y retorna la suma de a y b |
| validar_resultado_con_caso_de_prueba.py | Validar resultado con caso de prueba | El resultado de suma(2, 3) es exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y retorna la suma de a y b
**Descripción:** La función suma recibe dos argumentos y devuelve su suma. El bloque principal ejecuta pruebas automáticas que verifican el comportamiento esperado y muestra si el criterio de aceptación se cumple.

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
**Criterio:** El resultado de suma(2, 3) es exactamente 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba que verifica si suma(2, 3) produce 5 e imprime "CRITERIO OK" si la condición se cumple, o un mensaje de error detallado en caso contrario.

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
