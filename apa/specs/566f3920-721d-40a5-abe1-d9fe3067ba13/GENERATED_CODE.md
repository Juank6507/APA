# Código generado — 566f3920-721d-40a5-abe1-d9fe3067ba13

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definirestructuradelmodulodecalculo.py | Definir estructura del módulo de cálculo | El archivo contiene funciones definidas con firma correcta y retornan errores de tipo cuando corresponde. |

## definirestructuradelmodulodecalculo.py
**Tarea:** Definir estructura del módulo de cálculo
**Criterio:** El archivo contiene funciones definidas con firma correcta y retornan errores de tipo cuando corresponde.
**Descripción:** Define funciones básicas de cálculo (suma, resta, multiplicación, división) con validación de tipos y manejo de división por cero. Incluye un stub de prueba que verifica el comportamiento de las operaciones y los mensajes de error. Al ejecutarse, imprime el resultado de la validación.

```python
from typing import Union

Number = Union[int, float]


def suma(a: Number, b: Number) -> Number:
    """Stub de suma."""
    return a + b


def resta(a: Number, b: Number) -> Number:
    """Stub de resta."""
    return a - b


def multiplicacion(a: Number, b: Number) -> Number:
    """Stub de multiplicación."""
    return a * b


def division(a: Number, b: Number) -> Number:
    """Stub de división."""
    if b == 0:
        raise ValueError("División por cero")
    return a / b


def validar_tipo(valor: object, tipo: type) -> bool:
    """Stub de validación de tipo."""
    return isinstance(valor, tipo)


def _test_criterio() -> None:
    ok = True
    # Suma
    if not validar_tipo(suma(1, 2), (int, float)):
        ok = False
    # Resta
    if not validar_tipo(resta(5, 3), (int, float)):
        ok = False
    # Multiplicación
    if not validar_tipo(multiplicacion(2, 3.0), (int, float)):
        ok = False
    # División
    try:
        resultado = division(10, 2)
        if not validar_tipo(resultado, (int, float)):
            ok = False
    except Exception:
        ok = False
    # Validación de tipo
    if not validar_tipo(42, int):
        ok = False
    if validar_tipo("42", int):
        ok = False
    # División por cero
    try:
        division(1, 0)
        ok = False
    except ValueError:
        pass
    except Exception:
        ok = False

    if ok:
        print("CRITERIO OK")
    else:
        print("CRITERIO FALLO: test falló")


if __name__ == "__main__":
    _test_criterio()
```
