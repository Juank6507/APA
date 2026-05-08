# Código generado — ebdb0b25-5dbd-410c-a431-6cfe1fd5d388

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| implementar_funcion_suma.py | Implementar función suma | La función compila sin errores y tiene la firma esperada |
| verificar_resultado_con_caso_de_prueba.py | Verificar resultado con caso de prueba | El valor retornado por suma(2, 3) es exactamente 5 |

## implementar_funcion_suma.py
**Tarea:** Implementar función suma
**Criterio:** La función compila sin errores y tiene la firma esperada
**Descripción:** La función suma(a, b) devuelve la suma de dos valores. El bloque if __name__ == '__main__' ejecuta pruebas automáticas que verifican el comportamiento con números positivos, negativos y ceros, imprimiendo CRITERIO OK si todas pasan o CRITERIO FALLO con el error encontrado.

```python
def suma(a, b):
    return a + b

if __name__ == '__main__':
    try:
        # Test básico
        resultado = suma(2, 3)
        assert resultado == 5, f"Esperado 5, obtenido {resultado}"
        
        # Test con negativos
        resultado = suma(-1, 1)
        assert resultado == 0, f"Esperado 0, obtenido {resultado}"
        
        # Test con ceros
        resultado = suma(0, 0)
        assert resultado == 0, f"Esperado 0, obtenido {resultado}"
        
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## verificar_resultado_con_caso_de_prueba.py
**Tarea:** Verificar resultado con caso de prueba
**Criterio:** El valor retornado por suma(2, 3) es exactamente 5
**Descripción:** La función suma devuelve la suma de dos números. El bloque principal ejecuta una prueba que verifica si suma(2, 3) produce exactamente 5 e imprime si el criterio se cumple o falla.

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
