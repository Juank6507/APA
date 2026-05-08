# Código generado — 5e7f4471-1a4a-4dee-9cd3-6ae8d3b16313

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| crearutilsoperationspy.py | Crear utils/operations.py |  |

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define la función es_numero que distingue valores numéricos (int o float) de cualquier otro tipo, excluyendo explícitamente los booleanos. Al ejecutarse como script, crea el directorio utils, valida la función con casos de prueba y guarda el código resultante en utils/validators.py.

```python
import os
import sys

def es_numero(valor):
    """
    Retorna True si valor es int o float, False en caso contrario.
    """
    # Excluir bool explícitamente porque isinstance(True, int) es True
    if isinstance(valor, bool):
        return False
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    # Crear directorio utils si no existe
    os.makedirs('utils', exist_ok=True)
    
    # Tests de validación
    tests = [
        (5, True),
        (3.14, True),
        (0, True),
        (-7, True),
        (-2.5, True),
        ("5", False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
        (complex(1,2), False),
    ]
    
    try:
        for valor, esperado in tests:
            resultado = es_numero(valor)
            assert resultado == esperado, f"Fallo en {valor}: esperado {esperado}, obtenido {resultado}"
        
        # Guardar el código en utils/validators.py
        codigo = '''import os
import sys

def es_numero(valor):
    """
    Retorna True si valor es int o float, False en caso contrario.
    """
    # Excluir bool explícitamente porque isinstance(True, int) es True
    if isinstance(valor, bool):
        return False
    return isinstance(valor, (int, float))

if __name__ == '__main__':
    # Tests de validación
    tests = [
        (5, True),
        (3.14, True),
        (0, True),
        (-7, True),
        (-2.5, True),
        ("5", False),
        (None, False),
        ([], False),
        ({}, False),
        (True, False),
        (complex(1,2), False),
    ]
    
    try:
        for valor, esperado in tests:
            resultado = es_numero(valor)
            assert resultado == esperado, f"Fallo en {valor}: esperado {esperado}, obtenido {resultado}"
        print("CRITERIO OK")
    except AssertionError as e:
        print(f"CRITERIO FALLO: {e}")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
'''
        
        with open('utils/validators.py', 'w') as f:
            f.write(codigo)
        
        print("CRITERIO OK")
    except AssertionError as e:
        print(f"CRITERIO FALLO: {e}")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
```

## crearutilsoperationspy.py
**Tarea:** Crear utils/operations.py
**Criterio:** 
**Descripción:** Define tres funciones auxiliares: es_numero para verificar si un valor es int o float, y sumar/restar que validan sus argumentos y devuelven la suma o diferencia respectiva, lanzando ValueError si algún argumento no es numérico. El bloque principal ejecuta pruebas unitarias que confirman el comportamiento esperado con entradas válidas e inválidas.

```python
def es_numero(x):
    """Valida si el valor es un número (int o float)"""
    return isinstance(x, (int, float))

def sumar(a, b):
    """Suma dos números después de validarlos"""
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a + b

def restar(a, b):
    """Resta dos números después de validarlos"""
    if not es_numero(a) or not es_numero(b):
        raise ValueError("Ambos argumentos deben ser números")
    return a - b

if __name__ == '__main__':
    try:
        # Test de suma con números válidos
        assert sumar(2, 3) == 5
        assert sumar(2.5, 3.5) == 6.0
        
        # Test de resta con números válidos
        assert restar(5, 3) == 2
        assert restar(5.5, 2.5) == 3.0
        
        # Test con valores no numéricos
        try:
            sumar("a", 3)
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass
        
        try:
            restar(3, "b")
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass
        
        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {str(e)}')
```
