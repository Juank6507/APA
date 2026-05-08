# Código generado — d11feb89-054b-419a-8ba9-3a5fa6f640ed

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y tiene la firma esperada |
| verificar_resultado_con_caso_de_prueba.py | Verificar resultado con caso de prueba | El valor retornado por suma(2, 3) es exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la firma esperada
**Descripción:** La función `suma` recibe dos enteros y devuelve su suma. El bloque principal ejecuta pruebas automáticas que validan el comportamiento esperado y muestra si el criterio de aceptación se cumple.

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

## verificar_resultado_con_caso_de_prueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** El valor retornado por suma(2, 3) es exactamente 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba automática que verifica que suma(2, 3) devuelva exactamente 5 e imprime si el criterio se cumple o falla.

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
