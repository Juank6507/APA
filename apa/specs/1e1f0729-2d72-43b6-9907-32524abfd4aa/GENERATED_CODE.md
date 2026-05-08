# Código generado — 1e1f0729-2d72-43b6-9907-32524abfd4aa

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
**Descripción:** Crea un directorio "utils" y un archivo logger.js con un mensaje de consola específico. Luego verifica que el archivo exista y contenga el texto exacto, imprimiendo el resultado de la validación. El script ejecuta ambas acciones secuencialmente al ejecutarse.

```python
import os

def generar_logger():
    os.makedirs("utils", exist_ok=True)
    with open("utils/logger.js", "w", encoding="utf-8") as f:
        f.write("""// utils/logger.js
console.log('CRITERIO OK');
""")

def ejecutar_test():
    try:
        with open("utils/logger.js", encoding="utf-8") as f:
            contenido = f.read()
        if "console.log('CRITERIO OK');" in contenido:
            print("CRITERIO OK")
        else:
            print("CRITERIO FALLO: contenido incorrecto")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")

if __name__ == "__main__":
    generar_logger()
    ejecutar_test()
```

## crearscriptschecksh.py
**Tarea:** Crear scripts/check.sh
**Criterio:** 
**Descripción:** El script crea un archivo Bash llamado `check.sh` dentro del directorio `scripts`, asegurándose de que el directorio exista y otorgándole permisos de ejecución. Luego ejecuta ese script y verifica que su salida sea exactamente la cadena "CRITERIO OK", indicando éxito o fallo según el resultado. Si ocurre cualquier error durante la creación o la ejecución, se muestra un mensaje de fallo correspondiente.

```python
import os
import subprocess

def create_bash_script(file_path):
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    content = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "\n"
        "main() {\n"
        "    printf 'CRITERIO OK\\n'\n"
        "}\n"
        "\n"
        "main \"$@\"\n"
    )

    with open(file_path, 'w') as f:
        f.write(content)

    os.chmod(file_path, 0o755)

def test_script_functionality(file_path):
    if not os.path.exists(file_path):
        return False, "El archivo no existe."

    try:
        result = subprocess.run(
            [file_path],
            capture_output=True,
            text=True,
            check=True,
            shell=False
        )
        output = result.stdout.strip()
        if output == "CRITERIO OK":
            return True, ""
        return False, f"Salida inesperada: '{output}'"
    except subprocess.CalledProcessError as e:
        return False, f"El script falló con código de error {e.returncode}. Error: {e.stderr.strip()}"
    except Exception as e:
        return False, f"Error durante la ejecución: {str(e)}"

if __name__ == "__main__":
    target_file = "scripts/check.sh"
    try:
        create_bash_script(target_file)
        success, error_msg = test_script_functionality(target_file)
        if success:
            print("CRITERIO OK")
        else:
            print(f"CRITERIO FALLO: {error_msg}")
    except Exception as e:
        print(f"CRITERIO FALLO: Error en el proceso de creación: {str(e)}")
```

## creardbinitsql.py
**Tarea:** Crear db/init.sql
**Criterio:** 
**Descripción:** Crea una base de datos SQLite en memoria y ejecuta un script SQL que define una tabla, inserta un registro y realiza una consulta. Verifica que el resultado de la consulta sea la cadena 'CRITERIO OK'. Además, genera un archivo SQL de inicialización en el directorio 'db'.

```python
import os
import sqlite3

# Crear el directorio db si no existe
os.makedirs('db', exist_ok=True)

# SQL para crear la base de datos y la consulta que retorna 'CRITERIO OK'
sql_content = """
-- Crear una tabla de ejemplo
CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT);

-- Insertar un registro de prueba
INSERT OR IGNORE INTO test (id, name) VALUES (1, 'test');

-- Consulta que retorna 'CRITERIO OK'
SELECT 'CRITERIO OK' AS result;
"""

# Escribir el archivo SQL
with open('db/init.sql', 'w') as f:
    f.write(sql_content)

# Criterio de aceptación: ejecutar la consulta y verificar el resultado
try:
    # Leer y ejecutar el SQL en una base de datos temporal en memoria
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()

    # Dividir por ';' y ejecutar cada sentencia completa
    for statement in sql_content.strip().split(';'):
        statement = statement.strip()
        if statement:
            cursor.execute(statement)

    # Obtener el resultado de la consulta final
    result = cursor.fetchone()[0]
    conn.close()

    # Test: verificar que el resultado sea 'CRITERIO OK'
    if result == 'CRITERIO OK':
        print('CRITERIO OK')
    else:
        print(f'CRITERIO FALLO: resultado inesperado "{result}"')
except Exception as e:
    print(f'CRITERIO FALLO: {str(e)}')

if __name__ == '__main__':
    pass
```

## crearmaincpp.py
**Tarea:** Crear main.cpp
**Criterio:** 
**Descripción:** Crea un archivo con un programa C++ que imprime "CRITERIO OK", lo compila con g++ y ejecuta el binario. Verifica que la salida coincida exactamente con el texto esperado e imprime el resultado del criterio. Finalmente, elimina los archivos generados (main.cpp y el ejecutable).

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
    # Write the source file
    try:
        with open("main.cpp", "w", encoding="utf-8") as f:
            f.write(cpp_code)
    except OSError as e:
        print(f"CRITERIO FALLO: no se pudo escribir main.cpp: {e}")
        return

    # Compile
    try:
        compile_result = subprocess.run(
            ["g++", "-std=c++17", "-o", "main", "main.cpp"],
            capture_output=True,
            text=True,
            check=True
        )
    except FileNotFoundError:
        print("CRITERIO FALLO: g++ no encontrado")
        return
    except subprocess.CalledProcessError as e:
        print(f"CRITERIO FALLO: {e.stderr.strip()}")
        return

    # Run the compiled program
    try:
        run_result = subprocess.run(
            ["./main"],
            capture_output=True,
            text=True,
            check=True
        )
        output = run_result.stdout.strip()
        if output == "CRITERIO OK":
            print("CRITERIO OK")
        else:
            print(f"CRITERIO FALLO: output inesperado '{output}'")
    except FileNotFoundError:
        print("CRITERIO FALLO: ejecutable './main' no encontrado")
    except subprocess.CalledProcessError as e:
        print(f"CRITERIO FALLO: {e.stderr.strip()}")
    finally:
        # Clean up generated files
        for filename in ("main.cpp", "main"):
            try:
                os.remove(filename)
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"CRITERIO FALLO: no se pudo eliminar {filename}: {e}")

if __name__ == "__main__":
    main()
```
