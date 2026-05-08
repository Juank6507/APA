# Código generado — e13d9fbb-5d7c-40db-935e-0739517fb4ee

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilsmathhelperspy.py | Crear utils/math_helpers.py |  |

## crearutilsmathhelperspy.py
**Tarea:** Crear utils/math_helpers.py
**Criterio:** 
**Descripción:** Define dos funciones matemáticas auxiliares: `es_par` verifica si un número es par y `es_primo` determina si es primo. Al ejecutarse como script ejecuta pruebas unitarias que validan ambas funciones y muestra si los criterios de aceptación se cumplen.

```python
import os
import sys

def es_par(n):
    return n % 2 == 0

def es_primo(n):
    if n < 2:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True

if __name__ == '__main__':
    # Criterio de aceptación
    try:
        assert es_par(2) is True
        assert es_par(3) is False
        assert es_par(0) is True
        assert es_par(-4) is True
        assert es_par(-5) is False
        
        assert es_primo(2) is True
        assert es_primo(3) is True
        assert es_primo(4) is False
        assert es_primo(1) is False
        assert es_primo(0) is False
        assert es_primo(17) is True
        assert es_primo(18) is False
        
        print('CRITERIO OK')
    except AssertionError as e:
        print('CRITERIO FALLO:', e)
```
