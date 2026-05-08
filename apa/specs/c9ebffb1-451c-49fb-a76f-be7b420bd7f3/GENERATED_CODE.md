# Código generado — c9ebffb1-451c-49fb-a76f-be7b420bd7f3

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearfuncionsuma.py | Crear función suma | El archivo existe, contiene la función suma(a,b) y al importarla suma(2,3) devuelve 5 |
| crearfuncionresta.py | Crear función resta | El archivo existe, contiene la función resta(a,b) y al importarla resta(5,3) devuelve 2 |
| crearfuncionmultiplicacion.py | Crear función multiplicación | El archivo existe, contiene la función multiplicacion(a,b) y al importarla multiplicacion(4,3) devuelve 12 |

## crearfuncionsuma.py
**Tarea:** Crear función suma
**Criterio:** El archivo existe, contiene la función suma(a,b) y al importarla suma(2,3) devuelve 5
**Descripción:** Define la función suma(a, b) que devuelve la suma de sus dos argumentos. Al ejecutarse como script principal, verifica que suma(2, 3) produzca 5 e imprime si el criterio de aceptación se cumple o falla.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        resultado = suma(2, 3)
        if resultado == 5:
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: suma(2,3) devolvió {resultado} en lugar de 5')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## crearfuncionresta.py
**Tarea:** Crear función resta
**Criterio:** El archivo existe, contiene la función resta(a,b) y al importarla resta(5,3) devuelve 2
**Descripción:** Define la función resta(a, b) que devuelve la diferencia entre a y b. El bloque principal ejecuta una prueba automática que verifica que resta(5, 3) devuelva exactamente 2, mostrando "CRITERIO OK" si la condición se cumple o un mensaje de error detallado en caso contrario.

```python
def resta(a, b):
    return a - b

if __name__ == '__main__':
    try:
        resultado = resta(5, 3)
        if resultado == 2:
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: resta(5,3) devolvió {resultado}, se esperaba 2')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## crearfuncionmultiplicacion.py
**Tarea:** Crear función multiplicación
**Criterio:** El archivo existe, contiene la función multiplicacion(a,b) y al importarla multiplicacion(4,3) devuelve 12
**Descripción:** La función multiplicacion(a, b) devuelve el producto de dos números. El bloque principal verifica que multiplicacion(4, 3) produzca 12 y muestra "CRITERIO OK" si el resultado es correcto o un mensaje de error en caso contrario.

```python
def multiplicacion(a, b):
    return a * b

if __name__ == '__main__':
    try:
        resultado = multiplicacion(4, 3)
        if resultado == 12:
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: multiplicacion(4,3) devolvió {resultado} en lugar de 12')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```
