# Código generado — 9b490d8b-86ea-472e-851c-ef40f413e3c4

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementarfuncionsuma.py | Implementar función suma | La función compila sin errores y acepta dos parámetros enteros |
| verificarresultadoconcasodeprueba.py | Verificar resultado con caso de prueba | suma(2, 3) == 5 |

## implementarfuncionsuma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y acepta dos parámetros enteros
**Descripción:** La función `suma` recibe dos valores y devuelve su suma. El bloque principal ejecuta una prueba automática que verifica que la función acepte dos enteros y produzca el resultado correcto, imprimiendo 'CRITERIO OK' si la validación pasa o un mensaje de error si falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test que la función compila y acepta dos enteros
        resultado = suma(3, 5)
        if resultado == 8:
            print('CRITERIO OK')
        else:
            print('CRITERIO FALLO: resultado incorrecto')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificarresultadoconcasodeprueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** suma(2, 3) == 5
**Descripción:** La función suma recibe dos números y devuelve su suma. El bloque principal ejecuta una prueba que verifica si suma(2,3) es igual a 5, mostrando un mensaje de éxito o fallo según el resultado.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: suma(2, 3) devolvió {resultado}, se esperaba 5')
```
