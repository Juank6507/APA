# Código generado — 63020a9a-7f93-4152-ae54-2aaeb22e8dd7

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementarfuncionsuma.py | Implementar función suma | La función compila sin errores y tiene la firma esperada |
| verificarresultadoconcasodeprueba.py | Verificar resultado con caso de prueba | suma(2, 3) == 5 |

## implementarfuncionsuma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la firma esperada
**Descripción:** La función suma toma dos argumentos y devuelve su suma. El bloque if __name__ == '__main__' ejecuta una prueba automática que verifica que la función compile correctamente y que al sumar 2 y 3 devuelva 5, imprimiendo "CRITERIO OK" si todo funciona o un mensaje de error en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test de compilación y firma
        resultado = suma(2, 3)
        if resultado == 5:
            print('CRITERIO OK')
        else:
            print('CRITERIO FALLO: resultado incorrecto')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificarresultadoconcasodeprueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** suma(2, 3) == 5
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque principal ejecuta una prueba unitaria que verifica que suma(2, 3) produzca 5, imprimiendo 'CRITERIO OK' si la condición se cumple o un mensaje de error detallado en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    resultado = suma(2, 3)
    if resultado == 5:
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: suma(2, 3) devolvió {resultado} en lugar de 5')
```
