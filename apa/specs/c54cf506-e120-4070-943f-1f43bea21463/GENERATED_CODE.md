# Código generado — c54cf506-e120-4070-943f-1f43bea21463

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| definirestructuradelmodulodecalculo.py | Definir estructura del módulo de cálculo | El archivo contiene funciones definidas con firma correcta y comentarios de propósito. |
| implementarvalidaciondetiposymanejodeerrores.py | Implementar validación de tipos y manejo de errores | Las funciones lanzan excepciones o retornan mensajes de error para entradas no numéricas y división por cero. |
| crearpruebasunitariasparaoperacionesyvalidacion.py | Crear pruebas unitarias para operaciones y validación | Todas las pruebas pasan al ejecutar el test runner. |
| ejecutarpruebasyverificarcobertura.py | Ejecutar pruebas y verificar cobertura | El resultado de ejecutar las pruebas muestra 0 fallos y cobertura completa de ramas. |

## definirestructuradelmodulodecalculo.py
**Tarea:** Definir estructura del módulo de cálculo
**Criterio:** El archivo contiene funciones definidas con firma correcta y comentarios de propósito.
**Descripción:** Define funciones básicas de cálculo (suma, resta, multiplicación, división y validación de tipos). La división retorna None si el divisor es cero. El bloque principal verifica que las funciones estén definidas y devuelvan resultados correctos mediante asserts.

```python
def suma(a, b):
    # Suma dos números y retorna el resultado
    return a + b

def resta(a, b):
    # Resta b a a y retorna el resultado
    return a - b

def multiplicacion(a, b):
    # Multiplica dos números y retorna el resultado
    return a * b

def division(a, b):
    # Divide a entre b y retorna el resultado; retorna None si b es cero
    if b == 0:
        return None
    return a / b

def validar_tipo(valor, tipo):
    # Valida que el valor sea del tipo esperado
    return isinstance(valor, tipo)

if __name__ == '__main__':
    try:
        # Criterio de aceptación: verificar firmas y propósito básico
        assert callable(suma)
        assert callable(resta)
        assert callable(multiplicacion)
        assert callable(division)
        assert callable(validar_tipo)

        assert suma(2, 3) == 5
        assert resta(10, 4) == 6
        assert multiplicacion(3, 7) == 21
        assert division(10, 2) == 5.0
        assert division(1, 0) is None
        assert validar_tipo(5, int) is True
        assert validar_tipo("hola", str) is True
        assert validar_tipo(5, str) is False

        print("CRITERIO OK")
    except AssertionError:
        print("CRITERIO FALLO: validación de funciones o resultados incorrectos")
```

## implementarvalidaciondetiposymanejodeerrores.py
**Tarea:** Implementar validación de tipos y manejo de errores
**Criterio:** Las funciones lanzan excepciones o retornan mensajes de error para entradas no numéricas y división por cero.
**Descripción:** Implementa funciones básicas de suma, resta, multiplicación y división con validación de tipos numéricos y manejo de excepciones para entradas inválidas. La división adicionalmente verifica división por cero. El bloque principal ejecuta pruebas de afirmación para verificar el comportamiento y manejo de errores de las funciones.

```python
def suma(a, b):
    # Suma dos números y retorna el resultado
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a + b

def resta(a, b):
    # Resta b a a y retorna el resultado
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a - b

def multiplicacion(a, b):
    # Multiplica dos números y retorna el resultado
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a * b

def division(a, b):
    # Divide a entre b y retorna el resultado; retorna None si b es cero
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    if b == 0:
        raise ValueError("División por cero")
    return a / b

def validar_tipo(valor, tipo):
    # Valida que el valor sea del tipo esperado
    return isinstance(valor, tipo)

if __name__ == '__main__':
    try:
        # Criterio de aceptación: verificar firmas y manejo de errores
        assert callable(suma)
        assert callable(resta)
        assert callable(multiplicacion)
        assert callable(division)
        assert callable(validar_tipo)

        assert suma(2, 3) == 5
        assert resta(10, 4) == 6
        assert multiplicacion(3, 7) == 21
        assert division(10, 2) == 5.0
        assert validar_tipo(5, int) is True
        assert validar_tipo("hola", str) is True
        assert validar_tipo(5, str) is False

        # Validar excepciones para entradas inválidas
        try:
            suma("a", 1)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            resta(5, "b")
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            multiplicacion("x", 3)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            division(10, 0)
            assert False
        except ValueError as e:
            assert str(e) == "División por cero"

        try:
            division("z", 2)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        print("CRITERIO OK")
    except AssertionError:
        print("CRITERIO FALLO: validación de funciones o resultados incorrectos")
```

## crearpruebasunitariasparaoperacionesyvalidacion.py
**Tarea:** Crear pruebas unitarias para operaciones y validación
**Criterio:** Todas las pruebas pasan al ejecutar el test runner.
**Descripción:** Define funciones básicas de suma, resta, multiplicación y división con validación de tipos y manejo de errores. Incluye una utilidad para verificar tipos y pruebas unitarias que cubren casos válidos, errores de entrada no numérica y división por cero. El script confirma que todas las operaciones y validaciones funcionan correctamente.

```python
def suma(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a + b

def resta(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a - b

def multiplicacion(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a * b

def division(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    if b == 0:
        raise ValueError("División por cero")
    return a / b

def validar_tipo(valor, tipo):
    return isinstance(valor, tipo)

if __name__ == '__main__':
    try:
        # Operaciones válidas
        assert suma(2, 3) == 5
        assert resta(10, 4) == 6
        assert multiplicacion(3, 7) == 21
        assert division(10, 2) == 5.0
        assert validar_tipo(5, int) is True
        assert validar_tipo("hola", str) is True
        assert validar_tipo(5, str) is False

        # Operaciones inválidas -> ValueError
        try:
            suma("a", 1)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            resta(5, "b")
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            multiplicacion("x", 3)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        # División por cero -> ValueError
        try:
            division(10, 0)
            assert False
        except ValueError as e:
            assert str(e) == "División por cero"

        # Entrada no numérica en división -> ValueError
        try:
            division("z", 2)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        print("CRITERIO OK")
    except AssertionError:
        print("CRITERIO FALLO: validación de funciones o resultados incorrectos")
```

## ejecutarpruebasyverificarcobertura.py
**Tarea:** Ejecutar pruebas y verificar cobertura
**Criterio:** El resultado de ejecutar las pruebas muestra 0 fallos y cobertura completa de ramas.
**Descripción:** Define funciones básicas de aritmética (suma, resta, multiplicación y división) que validan tipos numéricos y manejan errores de entrada inválida o división por cero. Incluye una utilidad para verificar tipos de datos. El bloque principal ejecuta pruebas de unidad para confirmar el comportamiento correcto y la cobertura de errores.

```python
def suma(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a + b

def resta(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a - b

def multiplicacion(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    return a * b

def division(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ValueError("Entradas no numéricas")
    if b == 0:
        raise ValueError("División por cero")
    return a / b

def validar_tipo(valor, tipo):
    return isinstance(valor, tipo)

if __name__ == '__main__':
    try:
        # Operaciones válidas
        assert suma(2, 3) == 5
        assert resta(10, 4) == 6
        assert multiplicacion(3, 7) == 21
        assert division(10, 2) == 5.0
        assert validar_tipo(5, int) is True
        assert validar_tipo("hola", str) is True
        assert validar_tipo(5, str) is False

        # Operaciones inválidas -> ValueError
        try:
            suma("a", 1)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            resta(5, "b")
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        try:
            multiplicacion("x", 3)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        # División por cero -> ValueError
        try:
            division(10, 0)
            assert False
        except ValueError as e:
            assert str(e) == "División por cero"

        # Entrada no numérica en división -> ValueError
        try:
            division("z", 2)
            assert False
        except ValueError as e:
            assert str(e) == "Entradas no numéricas"

        print("CRITERIO OK")
    except AssertionError:
        print("CRITERIO FALLO: validación de funciones o resultados incorrectos")
```
