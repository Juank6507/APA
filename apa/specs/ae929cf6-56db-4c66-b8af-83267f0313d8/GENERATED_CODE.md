# Código generado — ae929cf6-56db-4c66-b8af-83267f0313d8

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función suma existe y acepta exactamente dos parámetros |
| verificar_suma2_3.py | Verificar suma(2, 3) | suma(2, 3) == 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función suma existe y acepta exactamente dos parámetros
**Descripción:** La función `suma` recibe dos valores y devuelve su suma. El bloque principal verifica que la función exista, acepte exactamente dos parámetros y produzca el resultado correcto al sumar 2 y 3, imprimiendo "CRITERIO OK" si todo es correcto o "CRITERIO FALLO" con el error correspondiente en caso contrario.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Verificar que la función existe y acepta exactamente dos parámetros
        import inspect
        sig = inspect.signature(suma)
        params = list(sig.parameters.keys())
        if len(params) != 2:
            raise ValueError(f"La función debe aceptar exactamente 2 parámetros, acepta {len(params)}")
        
        # Verificar que funciona correctamente
        resultado = suma(2, 3)
        if resultado != 5:
            raise ValueError(f"suma(2,3) debería devolver 5, devolvió {resultado}")
        
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_suma2_3.py
**Tarea:** Verificar suma(2, 3)
**Criterio:** suma(2, 3) == 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba automática que verifica que suma(2, 3) produce 5 y muestra “CRITERIO OK” si la condición se cumple o un mensaje de error detallado en caso contrario.

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
