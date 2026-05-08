# apa/core/spec_parser.py
import re
import os
import sys
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    from config.settings import settings
except ImportError:
    class _DummySettings:
        log_level = 'INFO'
    settings = _DummySettings()

from core.language_detector import LanguageDetector

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, getattr(settings, 'log_level', 'INFO').upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


def extract_imports_from_description(description: str) -> List[str]:
    """
    Analiza el texto de descripción para inferir imports necesarios.
    Busca referencias a archivos locales, sentencias de importación y módulos en backticks.
    """
    imports = []
    # 1. Buscar rutas de archivos python mencionadas explícitamente
    file_paths = re.findall(r'[\w/\\]+\.py', description)
    imports.extend(file_paths)

    # 2. Buscar imports explícitos en el texto
    import_matches = re.findall(r'^(?:from|import)\s+([\w.]+)', description, re.MULTILINE)
    imports.extend(import_matches)

    # 3. Buscar módulos mencionados en backticks
    bt_modules = re.findall(r'`([\w.]+)`', description)
    imports.extend(bt_modules)

    # Eliminar duplicados manteniendo orden
    seen = set()
    unique_imports = []
    for imp in imports:
        if imp not in seen:
            seen.add(imp)
            unique_imports.append(imp)

    return unique_imports


def infer_dependencies(files: List[Dict]) -> List[Dict]:
    """
    A partir de las descripciones e imports, detecta referencias a otros archivos definidos
    en la lista 'files' y las añade a 'depends_on'.
    """
    file_map = {f['path']: f for f in files}
    for current_file in files:
        depends_on = []
        description = current_file.get("description", "").lower()
        current_imports = [i.lower() for i in current_file.get("imports", [])]

        search_text = f"{description} {' '.join(current_imports)}"

        for other_file in files:
            if current_file['path'] == other_file['path']:
                continue

            other_path = other_file['path']
            basename = os.path.basename(other_path).lower()

            if other_path.lower() in search_text or (basename.endswith('.py') and basename in search_text):
                if other_path not in depends_on:
                    depends_on.append(other_path)

        current_file['depends_on'] = depends_on

    return files


def parse_multi_file_spec(spec_path: str) -> Dict[str, Any]:
    """
    Parsea una especificación markdown que puede definir múltiples archivos.
    """
    logger.info(f"Parsing multi-file spec: {spec_path}")
    try:
        path_obj = Path(spec_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        # Lectura robusta de encoding: intenta UTF-8 primero, fallback a latin-1 (Windows/cp1252 compatible)
        try:
            raw_content = path_obj.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            raw_content = path_obj.read_text(encoding='latin-1')
            logger.warning("Fallback a encoding latin-1 por fallo en UTF-8")

        result = {
             "project_name": "Unknown Project",
             "description": "",
             "files": [],
             "global_acceptance": "",
             "raw_spec": raw_content
        }

        match_h1 = re.search(r'^#\s*(?:Proyecto:\s*)?(.+)$', raw_content, re.MULTILINE)
        if match_h1:
            result["project_name"] = match_h1.group(1).strip()

        lines = raw_content.split('\n')
        in_file_section = False
        current_file_obj = None
        current_desc_lines = []
        file_blocks = []

        for line in lines:
            h2_file_match = re.match(r'^##\s*Archivo:\s*(.+)$', line.strip())
            h2_global_match = re.match(r'^##\s*(?:Criterios de aceptación globales|Criterios Globales).*$', line.strip(), re.IGNORECASE)

            if h2_file_match:
                if current_file_obj is not None:
                    current_file_obj['description'] = '\n'.join(current_desc_lines).strip()
                    file_blocks.append(current_file_obj)

                current_path = h2_file_match.group(1).strip()
                current_file_obj = {
                    "path": current_path,
                    "description": "",
                    "imports": [],
                    "depends_on": [],
                    "functions": [],
                    "acceptance_criteria": ""
                }
                current_desc_lines = []
                in_file_section = True

            elif h2_global_match and in_file_section:
                if current_file_obj is not None:
                    current_file_obj['description'] = '\n'.join(current_desc_lines).strip()
                    file_blocks.append(current_file_obj)
                    current_file_obj = None
                in_file_section = False
                current_desc_lines = []

            elif in_file_section:
                current_desc_lines.append(line)
            else:
                stripped = line.strip()
                if not re.match(r'^#\s*(?:Proyecto:\s*)?(.+)$', stripped):
                     result["description"] += line + "\n"

        if current_file_obj is not None:
            current_file_obj['description'] = '\n'.join(current_desc_lines).strip()
            file_blocks.append(current_file_obj)

        # Instanciar detector de lenguaje
        detector = LanguageDetector()

        files_data = []
        for block in file_blocks:
            path = block['path']
            desc = block['description']
            imports = extract_imports_from_description(desc)

            # Inferir lenguaje del archivo
            try:
                language = detector.detect(desc, path).name
            except Exception:
                language = "python"  # fallback por defecto
            logger.debug(f"Detected language for {path}: {language}")

            funcs_found = []
            defs = re.findall(r'def\s+(\w+)\s*\(', desc)
            for d in defs:
                funcs_found.append({"name": d, "type": "function"})

            backtick_funcs = re.findall(r'`(\w+)\s*\([^`]*\)`', desc)
            for bf in backtick_funcs:
                if not any(f["name"] == bf for f in funcs_found):
                    funcs_found.append({"name": bf, "type": "function"})

            # A2b: Añadida clave target_path explícita para compatibilidad con resolve_target_path
            files_data.append({
                 "path": path,
                 "target_path": path,
                 "language": language,  # <-- NUEVO: campo language inferido
                 "description": desc,
                 "imports": imports,
                 "depends_on": [],
                 "functions": funcs_found,
                 "acceptance_criteria": ""
            })

        files_data = infer_dependencies(files_data)
        result["files"] = files_data

        logger.info(f"Spec parsed successfully. Project: {result['project_name']}, Files: {len(files_data)}")

    except Exception as e:
        logger.error(f"Error parsing spec: {e}", exc_info=True)
        return {
             "error": str(e),
             "files": []
        }

    return result


if __name__ == "__main__":
    import tempfile

    print("=== INICIO PRUEBA T12 ===")

    spec_content = """
# Proyecto: Calculadora API

Este proyecto implementa una API REST de calculadora sencilla.

## Archivo: app/main.py
Debe contener una aplicación FastAPI con endpoints:
- POST /sumar -> recibe JSON {a, b} y retorna {resultado}
- GET /health -> retorna {"status": "ok"}

Importa las funciones `sumar` y `restar` desde `app/operaciones.py`.

## Archivo: app/operaciones.py
Define funciones `sumar(a, b)` y `restar(a, b)`.
Utiliza el módulo estándar `math` para operaciones avanzadas.

## Criterios de aceptación globales
- Todos los endpoints deben manejar errores.
"""
    # CORRECCIÓN T12: forzar encoding='utf-8' en la creación del archivo temporal
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write(spec_content)
        temp_path = f.name

    try:
        res = parse_multi_file_spec(temp_path)

        assert res.get("project_name") == "Calculadora API", f"Nombre incorrecto: {res.get('project_name')}"
        assert len(res.get("files", [])) == 2, f"Esperados 2 archivos, encontrados {len(res.get('files', []))}"

        main_file = next((f for f in res.get("files", []) if f["path"] == "app/main.py"), None)
        assert main_file is not None, "Falta app/main.py"
        assert main_file.get("target_path") == main_file["path"], "target_path no coincide con path en main_file"
        assert "app/operaciones.py" in main_file["imports"], "No se detectó el import de operaciones"
        assert "app/operaciones.py" in main_file["depends_on"], "No se detectó dependencia de main sobre operaciones"
        assert "language" in main_file, "Falta campo language en main_file"

        ops_file = next((f for f in res.get("files", []) if f["path"] == "app/operaciones.py"), None)
        assert ops_file is not None, "Falta app/operaciones.py"
        assert ops_file.get("target_path") == ops_file["path"], "target_path no coincide con path en ops_file"
        assert "math" in ops_file["imports"], "No se detectó import math"
        assert "language" in ops_file, "Falta campo language en ops_file"

        funcs = [f['name'] for f in ops_file['functions']]
        assert 'sumar' in funcs, "No se detectó función sumar"

        local_deps = [d for d in ops_file["depends_on"] if d in [f["path"] for f in res.get("files", [])]]
        assert "app/main.py" not in local_deps, "Dependencia circular incorrecta detectada"

        print(f"✅ Proyecto: {res['project_name']}")
        print(f"✅ Archivos detectados: {len(res['files'])}")
        for f in res["files"]:
            deps_str = ", ".join(f["depends_on"]) if f["depends_on"] else "ninguna"
            print(f"   - {f['path']} (target: {f['target_path']}, lang: {f['language']}, depende de: {deps_str})")
            print(f"     Imports: {f['imports']}")

        print("✅ Prueba multi-archivo pasada")
    except Exception as e:
        print(f"❌ Fallo en prueba: {e}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    print("=== FIN PRUEBA T12 ===")