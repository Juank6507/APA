# Código generado — 331bc7c6-d465-46d7-b066-db0fbd211c1c

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definir_funcion_suma.py | Definir función suma | La función suma existe y acepta dos parámetros |
| implementar_logica_de_suma.py | Implementar lógica de suma | La función suma retorna un valor numérico |
| verificar_resultado_de_suma.py | Verificar resultado de suma | suma(2, 3) retorna 5 |

## definir_funcion_suma.py
**Tarea:** Definir función suma
**Criterio:** La función suma existe y acepta dos parámetros
**Descripción:** La función suma acepta dos números enteros como parámetros y devuelve su suma. El código también incluye pruebas para verificar que la función existe y acepta exactamente dos parámetros, imprimiendo un mensaje de éxito o fracaso según el resultado. Esto garantiza que la función cumpla con los criterios de aceptación definidos.

```python
def suma(a: int, b: int) -> int:
 # Función que acepta dos parámetros enteros y devuelve su suma
 return a + b

if __name__ == '__main__':
 try:
  # Verificar que la función existe
  assert 'suma' in globals(), "La función suma no existe"
  
  # Verificar que la función acepta dos parámetros
  assert suma.__code__.co_argcount == 2, "La función suma no acepta dos parámetros"
  
  print('CRITERIO OK')
 except AssertionError as e:
  print(f'CRITERIO FALLO: {e}')
```

## implementar_logica_de_suma.py
**Tarea:** Implementar lógica de suma
**Criterio:** La función suma retorna un valor numérico
**Descripción:** La función suma acepta dos parámetros numéricos y devuelve su suma. El resultado es validado para asegurar que sea un valor numérico. Esta función cumple con el criterio de aceptación si retorna un número entero o flotante.

```python
def suma(a, b):
    # Función que suma dos números enteros
    return a + b

if __name__ == '__main__':
    # Test del criterio de aceptación
    try:
        a = 2
        b = 3
        resultado = suma(a, b)
        assert isinstance(resultado, (int, float)), "El resultado no es numérico"
        print('CRITERIO OK')
    except AssertionError as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_resultado_de_suma.py
**Tarea:** Verificar resultado de suma
**Criterio:** suma(2, 3) retorna 5
**Descripción:** La función suma devuelve la suma de dos números enteros. El código principal verifica el resultado de la función suma con el criterio de aceptación suma(2, 3) retorna 5 e imprime el resultado de la verificación. Si el resultado es correcto, imprime "CRITERIO OK", de lo contrario, imprime un mensaje de error.

```python
def suma(a, b):
 # Función que retorna la suma de dos números
 return a + b

if __name__=='__main__':
 # Criterio de aceptación: suma(2, 3) retorna 5
 resultado = suma(2, 3)
 if resultado == 5:
 print('CRITERIO OK')
 else:
 print(f'CRITERIO FALLO: se esperaba 5, se obtuvo {resultado}')
```
