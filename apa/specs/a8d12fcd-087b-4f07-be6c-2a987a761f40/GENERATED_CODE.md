# Código generado — a8d12fcd-087b-4f07-be6c-2a987a761f40

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y tiene la signatura correcta |
| verificar_resultado_con_caso_de_prueba.py | Verificar resultado con caso de prueba | suma(2, 3) == 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la signatura correcta
**Descripción:** Define una función suma que recibe dos enteros y devuelve su suma. El bloque principal ejecuta pruebas básicas para verificar que el resultado sea correcto y confirma que la implementación cumple el criterio de aceptación.

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
**Criterio:** suma(2, 3) == 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta un caso de prueba que verifica que suma(2, 3) devuelva 5 e imprime si el criterio se cumple o falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    a = 2
    b = 3
    resultado = suma(a, b)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: suma(2, 3) devolvió {resultado}, se esperaba 5')
```
