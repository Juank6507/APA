# Código generado — c5f6e728-c077-4f77-ac4f-ca09c901d681

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilshelperpy.py | Crear utils/helper.py |  |
| crearutilsloggerjs.py | Crear utils/logger.js |  |
| crearscriptschecksh.py | Crear scripts/check.sh |  |
| creardbinitsql.py | Crear db/init.sql |  |

## crearutilshelperpy.py
**Tarea:** Crear utils/helper.py
**Criterio:** 
**Descripción:** Define una función que retorna la cadena "CONSTANT". Incluye un bloque de ejecución principal que valida el resultado y muestra un mensaje de éxito o error. Sirve como utilidad para pruebas de verificación.

```python
# utils/helper.py

from typing import Any


def get_constant_value() -> Any:
    """Simple function that returns a constant value."""
    return "CONSTANT"


if __name__ == "__main__":
    try:
        result = get_constant_value()
        if result == "CONSTANT":
            print("CRITERIO OK")
        else:
            print(f"CRITERIO FALLO: expected 'CONSTANT', got '{result}'")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
```

## crearutilsloggerjs.py
**Tarea:** Crear utils/logger.js
**Criterio:** 
**Descripción:** Crea el directorio "utils" si no existe y genera un archivo logger.js con un mensaje de consola específico. La función test_logger verifica que el archivo contenga el contenido esperado e imprime el resultado. El script ejecuta ambas acciones al ejecutarse.

```python
import os

def generar_logger():
    os.makedirs("utils", exist_ok=True)
    with open("utils/logger.js", "w") as f:
        f.write("console.log('CRITERIO OK');\n")

def test_logger():
    try:
        with open("utils/logger.js", "r") as f:
            content = f.read().strip()
        if "console.log('CRITERIO OK');" in content:
            print("CRITERIO OK")
        else:
            print("CRITERIO FALLO: contenido incorrecto")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")

if __name__ == "__main__":
    generar_logger()
    test_logger()
```

## crearscriptschecksh.py
**Tarea:** Crear scripts/check.sh
**Criterio:** 
**Descripción:** Crea un script Bash en `scripts/check.sh` que imprime "CRITERIO OK" y lo ejecuta. Verifica que el script se ejecute correctamente y su salida coincida exactamente con el texto esperado. Devuelve éxito si se cumple el criterio, o error si falla.

```python
#!/usr/bin/env python3
import os
import subprocess
import sys

def generate_bash_script():
    content = '''#!/bin/bash
set -euo pipefail
printf "%s\\n" "CRITERIO OK"
'''
    os.makedirs("scripts", exist_ok=True)
    script_path = "scripts/check.sh"
    with open(script_path, "w") as f:
        f.write(content)
    os.chmod(script_path, 0o755)
    return script_path

def test_script(script_path):
    result = subprocess.run(
        [script_path],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "CRITERIO OK"

if __name__ == "__main__":
    script_path = generate_bash_script()
    if test_script(script_path):
        print("CRITERIO OK")
        sys.exit(0)
    else:
        print("CRITERIO FALLO: output mismatch or script failed")
        sys.exit(1)
```

## creardbinitsql.py
**Tarea:** Crear db/init.sql
**Criterio:** 
**Descripción:** Crea un archivo init.sql con una consulta SQL que devuelve 'CRITERIO OK' y lo guarda en la carpeta db. Verifica la existencia y contenido del archivo, luego ejecuta la consulta en una base de datos SQLite en memoria para validar el resultado. El script informa si cumple o falla el criterio de aceptación.

```python
import os
import sqlite3

def crear_init_sql():
    db_dir = "db"
    os.makedirs(db_dir, exist_ok=True)
    ruta = os.path.join(db_dir, "init.sql")
    with open(ruta, "w") as f:
        f.write("SELECT 'CRITERIO OK';\n")
    return ruta

def test_init_sql():
    ruta = "db/init.sql"
    if not os.path.exists(ruta):
        return False, f"El archivo {ruta} no existe"
    with open(ruta, "r") as f:
        sql = f.read().strip()
    if "CRITERIO OK" not in sql:
        return False, "El archivo no contiene 'CRITERIO OK'"
    conn = sqlite3.connect(":memory:")
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        resultado = cursor.fetchone()
        if resultado and resultado[0] == "CRITERIO OK":
            return True, ""
        else:
            return False, f"Resultado inesperado: {resultado}"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

if __name__ == "__main__":
    archivo = crear_init_sql()
    ok, detalle = test_init_sql()
    if ok:
        print("CRITERIO OK")
    else:
        print(f"CRITERIO FALLO: {detalle}")
```
