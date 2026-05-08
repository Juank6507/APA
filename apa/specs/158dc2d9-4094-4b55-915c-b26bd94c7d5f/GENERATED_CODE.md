# Código generado — 158dc2d9-4094-4b55-915c-b26bd94c7d5f

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearutilshelperpy.py | Crear utils/helper.py |  |
| crearutilsloggerjs.py | Crear utils/logger.js |  |
| crearscriptschecksh.py | Crear scripts/check.sh |  |
| creardbinitsql.py | Crear db/init.sql |  |
| crearmaincpp.py | Crear main.cpp |  |

## crearutilshelperpy.py
**Tarea:** Crear utils/helper.py
**Criterio:** 
**Descripción:** Define una función que retorna la cadena "CONSTANT". Incluye un bloque de ejecución principal que valida el retorno y muestra un mensaje de éxito o error. Sirve como utilidad de verificación simple.

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
**Descripción:** Crea el directorio "utils" si no existe y genera un archivo logger.js con un mensaje de consola específico. La función test_logger verifica que el archivo se haya creado correctamente y contenga el contenido esperado. Imprime "CRITERIO OK" si la validación es exitosa o un mensaje de error si falla.

```python
import os

def generar_logger():
    os.makedirs("utils", exist_ok=True)
    with open("utils/logger.js", "w") as f:
        f.write("console.log('CRITERIO OK');\n")

def test_logger():
    try:
        generar_logger()
        with open("utils/logger.js") as f:
            contenido = f.read().strip()
        if "console.log('CRITERIO OK');" in contenido:
            print("CRITERIO OK")
        else:
            print("CRITERIO FALLO: contenido incorrecto")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")

if __name__ == "__main__":
    test_logger()
```

## crearscriptschecksh.py
**Tarea:** Crear scripts/check.sh
**Criterio:** 
**Descripción:** Genera un script Bash en `scripts/check.sh` que imprime "CRITERIO OK". Ejecuta el script creado y verifica que su salida coincida exactamente con ese texto. Devuelve el resultado de la validación mediante códigos de salida del programa.

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
    try:
        result = subprocess.run(
            [script_path],
            capture_output=True,
            text=True,
            check=True
        )
        output = result.stdout.strip()
        if output == "CRITERIO OK":
            return True, None
        return False, f"Output inesperado: {output}"
    except subprocess.CalledProcessError as e:
        return False, f"Error de ejecución: {e}"
    except Exception as e:
        return False, str(e)

if __name__ == "__main__":
    script = generate_bash_script()
    passed, detail = test_script(script)
    if passed:
        print("CRITERIO OK")
        sys.exit(0)
    else:
        print(f"CRITERIO FALLO: {detail}")
        sys.exit(1)
```

## creardbinitsql.py
**Tarea:** Crear db/init.sql
**Criterio:** 
**Descripción:** Crea un archivo SQL en `db/init.sql` con una tabla `test` si no existe. Conecta a una base de datos en memoria, ejecuta el SQL y una inserción de prueba. Verifica que el registro se inserte correctamente imprimiendo el resultado.

```python
import os
import sqlite3

def crear_init_sql():
    db_dir = 'db'
    os.makedirs(db_dir, exist_ok=True)
    ruta = os.path.join(db_dir, 'init.sql')
    sql = """CREATE TABLE IF NOT EXISTS test (message TEXT);"""
    with open(ruta, 'w') as f:
        f.write(sql)

def test_init_sql():
    crear_init_sql()
    ruta_sql = 'db/init.sql'
    with open(ruta_sql, 'r') as f:
        sql_content = f.read().strip()

    conn = sqlite3.connect(':memory:')
    try:
        cursor = conn.cursor()
        cursor.execute(sql_content)
        conn.commit()

        cursor.execute("INSERT INTO test (message) VALUES ('CRITERIO OK');")
        conn.commit()

        cursor.execute("SELECT message FROM test;")
        rows = cursor.fetchall()
        if rows and len(rows[0]) > 0 and rows[0][0] == 'CRITERIO OK':
            print('CRITERIO OK')
        else:
            print(f'CRITERIO FALLO: resultado inesperado {rows}')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
    finally:
        conn.close()

if __name__ == '__main__':
    test_init_sql()
```

## crearmaincpp.py
**Tarea:** Crear main.cpp
**Criterio:** 
**Descripción:** Crea un archivo C++ que imprime "CRITERIO OK", lo compila con g++ y ejecuta el binario. Verifica que la salida coincida exactamente con el texto esperado. Finalmente, elimina los archivos generados para limpiar el entorno.

```python
import subprocess
import os
import sys

def main():
    cpp_code = '''#include <iostream>

int main() {
    std::cout << "CRITERIO OK" << std::endl;
    return 0;
}
'''
    with open("main.cpp", "w") as f:
        f.write(cpp_code)

    try:
        result_compile = subprocess.run(
            ["g++", "-std=c++17", "-o", "main", "main.cpp"],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"CRITERIO FALLO: {e.stderr.strip()}")
        return

    try:
        result_run = subprocess.run(
            ["./main"],
            capture_output=True,
            text=True,
            check=True
        )
        output = result_run.stdout.strip()
        if output == "CRITERIO OK":
            print("CRITERIO OK")
        else:
            print(f"CRITERIO FALLO: output inesperado '{output}'")
    except subprocess.CalledProcessError as e:
        print(f"CRITERIO FALLO: {e.stderr.strip() if e.stderr else 'ejecución fallida'}")
    finally:
        for f in ["main.cpp", "main"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

if __name__ == "__main__":
    main()
```
