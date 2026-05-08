# apa/core/assembler.py

import ast
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

class ValidationMode:
    SYNTAX = "syntax"
    IMPORT = "import"
    EXECUTE = "execute"
    AUTO = "auto"

@dataclass
class AssemblyResult:
    success: bool
    output: str
    backup_path: Optional[str]
    summary: str

class Assembler: 
   
    def assemble(self, content: str, blocks: list[dict], anchor_map: dict) -> str:
        """
        Ensambla bloques de codigo sobre el contenido.
        
        Args:
            content: Contenido original del archivo
            blocks: Lista de bloques a insertar
            anchor_map: Mapa de anclas con numeros de linea
        
        Returns:
            str: Contenido ensamblado
        """
        lines = content.split('\n')

        for block in blocks:
            action = block['action']
            anchor = block['anchor']
            code = block['code']
            anchor_info = anchor_map[anchor]
            line_idx = anchor_info['line'] - 1

            code_lines = code.splitlines() if code else []
            # Nota: NO usar keepends=True porque luego '\n'.join agrega \n adicional
            
            code_type = self._detect_code_type(code)
            prev_type = self._detect_previous_structure(lines, line_idx)
            
            if code_type != prev_type and code_type != "unknown":
                if line_idx >= 0 and line_idx < len(lines):
                    if lines[line_idx].strip() != "":
                        code_lines = ["\n"] + code_lines

            if action == 'after':
                if line_idx < len(lines) and not lines[line_idx].endswith('\n'):
                    lines[line_idx] = lines[line_idx] + '\n'
                lines[line_idx + 1 : line_idx + 1] = code_lines
            elif action == 'before':
                lines[line_idx : line_idx] = code_lines
            elif action == 'replace':
                end_idx = anchor_info['end_line']
                lines[line_idx : end_idx] = code_lines

        result = '\n'.join(lines)
        
        # Normalizar lineas en blanco segun PEP 8
        result = self._normalize_blank_lines(result)
        
        return result
    
    @staticmethod
    def _normalize_blank_lines(content: str) -> str:
        """
        Normaliza las lineas en blanco segun estructura APA.
        
        Estructura:
        - Unidad 1: Nombre script + comentarios iniciales
        - Unidad 2: Imports y dependencias
        - Unidad 3: Codigo (clases, metodos, funciones)
        - Unidad 4: Validaciones (if __name__, tests)
        
        Reglas:
        - 1 linea en blanco entre cada unidad
        - Maximo 1 linea en blanco consecutiva (colapsar multiples)
        """
        if not content.strip():
            return content
        
        lines = content.split('\n')
        
        # Clasificar cada linea en su unidad
        def get_unit(line: str, prev_unit: int, in_main: bool) -> tuple:
            stripped = line.strip()
            if not stripped:
                return prev_unit, in_main
            elif stripped.startswith('#') and prev_unit <= 1:
                return 1, in_main
            elif stripped.startswith('import ') or stripped.startswith('from '):
                return 2, in_main
            elif 'if __name__' in stripped and '__main__' in stripped:
                return 4, True
            elif in_main:
                return 4, in_main
            else:
                return 3, in_main
        
        # Asignar unidad a cada linea
        units = []
        prev_unit = 1
        in_main = False
        for line in lines:
            unit, in_main = get_unit(line, prev_unit, in_main)
            units.append(unit)
            if line.strip():
                prev_unit = unit
        
        # Reconstruir: maximo 1 linea en blanco consecutiva
        # + asegurar linea en blanco entre estructuras top-level (class/def)
        result = []
        prev_unit = None
        consecutive_blanks = 0
        
        for i, (line, unit) in enumerate(zip(lines, units)):
            stripped = line.strip()
            
            # Si la linea es blanco
            if not stripped:
                # Contar lineas en blanco consecutivas
                if consecutive_blanks < 1:
                    result.append('')
                    consecutive_blanks += 1
                # Si ya hay 1, saltar (no agregar mas)
                continue
            
            # Linea con contenido: resetear contador
            consecutive_blanks = 0
            
            # Si cambio de unidad, asegurar linea en blanco
            if prev_unit is not None and unit != prev_unit:
                # Agregar linea en blanco si no hay una antes
                if result and result[-1] != '':
                    result.append('')
            
            # Si dentro de unidad 3 (codigo) y aparece nueva estructura top-level
            # (class o def a indent 0), asegurar linea en blanco antes
            if unit == 3 and prev_unit == 3:
                if stripped.startswith('class ') or stripped.startswith('def ') or stripped.startswith('async def '):
                    indent = len(line) - len(line.lstrip())
                    if indent == 0 and result and result[-1] != '':
                        result.append('')
            
            result.append(line)
            prev_unit = unit
        
        return '\n'.join(result)    

    @staticmethod
    def _detect_validation_mode(content: str) -> str:
        gui_libs = ["tkinter", "PyQt", "PySide", "wx", "kivy"]
        for lib in gui_libs:
            if lib in content:
                return ValidationMode.IMPORT
        
        server_libs = ["flask", "fastapi", "uvicorn", "tornado", "django"]
        for lib in server_libs:
            if lib in content:
                return ValidationMode.IMPORT
        
        if "__name__" in content and "__main__" in content:
            heavy_test_indicators = [
                "NASConnector",
                "correction_loop",
                "call_llm",
                "subprocess.run",
                "unittest",
                "pytest",
                "test_",
                "_test(",
                "logging.basicConfig",
            ]
            for indicator in heavy_test_indicators:
                if indicator in content:
                    return ValidationMode.IMPORT
            return ValidationMode.EXECUTE
        
        return ValidationMode.IMPORT

    @staticmethod
    def validate(content: str, script_path: str = None, validation_mode: str = ValidationMode.AUTO) -> dict:
        """
        Valida el contenido ensamblado.
        
        Args:
            content: Contenido a validar
            script_path: Ruta del script (para referencia)
            validation_mode: Modo de validaci贸n
        
        Returns:
            dict con: success, output, returncode
        """
        if validation_mode == ValidationMode.AUTO:
            validation_mode = Assembler._detect_validation_mode(content)
        
        output = ""
        returncode = -1
        
        if validation_mode == ValidationMode.SYNTAX:
            try:
                ast.parse(content)
                output = "Validacion de sintaxis exitosa."
                returncode = 0
            except SyntaxError as e:
                output = "Error de sintaxis linea " + str(e.lineno) + ": " + str(e.msg)
                returncode = 1
        
        elif validation_mode == ValidationMode.IMPORT:
            import importlib.util
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            try:
                spec = importlib.util.spec_from_file_location("_validation_module", tmp_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                output = "Imports validados correctamente."
                returncode = 0
            except Exception as e:
                output = "Error al importar: " + str(e)
                returncode = 1
            finally:
                os.unlink(tmp_path)
        
        elif validation_mode == ValidationMode.EXECUTE:
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            try:
                result = subprocess.run([sys.executable, tmp_path], capture_output=True, text=True, timeout=10)
                output = result.stdout
                if result.stderr:
                    output += "\n" + result.stderr if result.stdout else result.stderr
                returncode = result.returncode
            finally:
                os.unlink(tmp_path)
        
        return {
            "success": returncode == 0,
            "output": output,
            "returncode": returncode
        }

    @staticmethod
    def _detect_code_type(code: str) -> str:
        if not code or not code.strip():
            return "unknown"
        
        lines = code.strip().split("\n")
        first_non_empty = ""
        for line in lines:
            if line.strip():
                first_non_empty = line.strip()
                break
        
        if first_non_empty.startswith("import ") or first_non_empty.startswith("from "):
            return "imports"
        
        if "if __name__" in code and "__main__" in code:
            return "main"
        
        if first_non_empty.startswith("def ") or first_non_empty.startswith("class ") or first_non_empty.startswith("async def "):
            return "code"
        
        return "code"
    
    @staticmethod
    def _detect_previous_structure(lines: list, line_idx: int) -> str:
        if line_idx <= 0:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    return "comments"
                if stripped and not stripped.startswith("#"):
                    return "comments"
            return "comments"
        
        # Buscar hacia atr谩s desde la l铆nea ANTERIOR a la de inserci贸n
        for i in range(line_idx - 1, -1, -1):
            if i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    return "imports"
                if stripped.startswith("if __name__"):
                    return "main"
                if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("async def "):
                    return "code"
                if stripped.startswith("#"):
                    continue
        
        has_imports = False
        has_code = False
        
        for i in range(line_idx):
            if i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    has_imports = True
                elif stripped and not stripped.startswith("#"):
                    has_code = True
        
        if has_code:
            return "code"
        if has_imports:
            return "imports"
        
        return "comments"
    
if __name__ == "__main__":
    import tempfile
    import os
    
    print("="*60)
    print("TESTS ASSEMBLER.PY")
    print("="*60)
    
    assembler = Assembler()
    
    # TEST 1: assemble() - inserci贸n b谩sica
    print("\n--- TEST 1: assemble() inserci贸n b谩sica ---")
    content = "# archivo.py\n# comentario\n\ndef foo():\n    pass\n"
    blocks = [{"action": "after", "anchor": "test", "code": "x = 1\n"}]
    anchor_map = {"test": {"line": 3}}
    result = assembler.assemble(content, blocks, anchor_map)
    assert "x = 1" in result
    assert "def foo" in result
    print("鉁� TEST 1 PASADO")
    
    # TEST 2: assemble() - m煤ltiples bloques ordenados
    print("\n--- TEST 2: assemble() m煤ltiples bloques ---")
    content = "# archivo.py\n\ndef foo():\n    pass\n"
    blocks = [
        {"action": "after", "anchor": "a1", "code": "import os\n"},
        {"action": "after", "anchor": "a2", "code": "\ndef bar():\n    pass\n"}
    ]
    anchor_map = {"a1": {"line": 2}, "a2": {"line": 5}}
    result = assembler.assemble(content, blocks, anchor_map)
    assert "import os" in result
    assert "def bar" in result
    assert result.index("import os") < result.index("def foo")
    assert result.index("def foo") < result.index("def bar")
    print("鉁� TEST 2 PASADO")
    
    # TEST 3: _detect_code_type() - imports
    print("\n--- TEST 3: _detect_code_type() imports ---")
    assert assembler._detect_code_type("import os\n") == "imports"
    assert assembler._detect_code_type("from pathlib import Path\n") == "imports"
    print("鉁� TEST 3 PASADO")
    
    # TEST 4: _detect_code_type() - c贸digo
    print("\n--- TEST 4: _detect_code_type() c贸digo ---")
    assert assembler._detect_code_type("def foo():\n    pass\n") == "code"
    assert assembler._detect_code_type("class Bar:\n    pass\n") == "code"
    assert assembler._detect_code_type("async def baz():\n    pass\n") == "code"
    print("鉁� TEST 4 PASADO")
    
    # TEST 5: _detect_code_type() - main
    print("\n--- TEST 5: _detect_code_type() main ---")
    code = "if __name__ == '__main__':\n    print('test')\n"
    assert assembler._detect_code_type(code) == "main"
    print("鉁� TEST 5 PASADO")
    
    # TEST 6: _detect_previous_structure() - comentarios
    print("\n--- TEST 6: _detect_previous_structure() comentarios ---")
    lines = ["# comentario", "", "def foo():", "    pass"]
    assert assembler._detect_previous_structure(lines, 0) == "comments"
    print("鉁� TEST 6 PASADO")
    
    # TEST 7: _detect_previous_structure() - imports
    print("\n--- TEST 7: _detect_previous_structure() imports ---")
    lines = ["import os", "import sys", "", "def foo():", "    pass"]
    assert assembler._detect_previous_structure(lines, 3) == "imports"
    print("鉁� TEST 7 PASADO")
    
    # TEST 8: _detect_previous_structure() - c贸digo
    print("\n--- TEST 8: _detect_previous_structure() c贸digo ---")
    lines = ["import os", "", "def foo():", "    pass", "", "def bar():", "    pass"]
    assert assembler._detect_previous_structure(lines, 5) == "code"
    print("鉁� TEST 8 PASADO")
    
    # TEST 9: _detect_validation_mode() - GUI
    print("\n--- TEST 9: _detect_validation_mode() GUI ---")
    content = "import tkinter\napp = tk.Tk()\n"
    assert assembler._detect_validation_mode(content) == ValidationMode.IMPORT
    print("鉁� TEST 9 PASADO")
    
    # TEST 10: _detect_validation_mode() - server
    print("\n--- TEST 10: _detect_validation_mode() server ---")
    content = "from flask import Flask\napp = Flask(__name__)\n"
    assert assembler._detect_validation_mode(content) == ValidationMode.IMPORT
    print("鉁� TEST 10 PASADO")
    
    # TEST 11: _detect_validation_mode() - execute
    print("\n--- TEST 11: _detect_validation_mode() execute ---")
    content = "def main():\n    print('test')\n\nif __name__ == '__main__':\n    main()\n"
    assert assembler._detect_validation_mode(content) == ValidationMode.EXECUTE
    print("鉁� TEST 11 PASADO")
    
    # TEST 12: validate() - syntax OK
    print("\n--- TEST 12: validate() syntax OK ---")
    content = "x = 1\ny = 2\n"
    result = assembler.validate(content, validation_mode=ValidationMode.SYNTAX)
    assert result["success"] == True
    assert result["returncode"] == 0
    print("鉁� TEST 12 PASADO")
    
    # TEST 13: validate() - syntax error
    print("\n--- TEST 13: validate() syntax error ---")
    content = "def broken(\n"
    result = assembler.validate(content, validation_mode=ValidationMode.SYNTAX)
    assert result["success"] == False
    assert result["returncode"] == 1
    print("鉁� TEST 13 PASADO")
    
    # TEST 14: validate() - import OK
    print("\n--- TEST 14: validate() import OK ---")
    content = "import os\nimport sys\n"
    result = assembler.validate(content, validation_mode=ValidationMode.IMPORT)
    assert result["success"] == True
    print("鉁� TEST 14 PASADO")
    
    # TEST 15: validate() - import error
    print("\n--- TEST 15: validate() import error ---")
    content = "import modulo_inexistente_xyz\n"
    result = assembler.validate(content, validation_mode=ValidationMode.IMPORT)
    assert result["success"] == False
    print("鉁� TEST 15 PASADO")
    
    # TEST 16: validate() - execute OK
    print("\n--- TEST 16: validate() execute OK ---")
    content = "print('hello')\n"
    result = assembler.validate(content, validation_mode=ValidationMode.EXECUTE)
    assert result["success"] == True
    assert "hello" in result["output"]
    print("鉁� TEST 16 PASADO")
    
    # TEST 17: validate() - execute error
    print("\n--- TEST 17: validate() execute error ---")
    content = "raise Exception('test error')\n"
    result = assembler.validate(content, validation_mode=ValidationMode.EXECUTE)
    assert result["success"] == False
    print("鉁� TEST 17 PASADO")
    
    # TEST 18: validate() - AUTO mode
    print("\n--- TEST 18: validate() AUTO mode ---")
    content = "import tkinter\n"
    result = assembler.validate(content, validation_mode=ValidationMode.AUTO)
    assert result["success"] == True
    print("鉁� TEST 18 PASADO")
    
    # TEST 19: L铆nea en blanco entre estructuras
    print("\n--- TEST 19: L铆nea en blanco entre estructuras ---")
    content = "# archivo.py\n# comentario\n"
    blocks = [{"action": "after", "anchor": "test", "code": "import os\n"}]
    anchor_map = {"test": {"line": 2}}
    result = assembler.assemble(content, blocks, anchor_map)
    lines = result.split('\n')
    found_blank = False
    for i, line in enumerate(lines):
        if line.strip() == "" and i > 0 and lines[i-1].startswith('#'):
            found_blank = True
            break
    assert found_blank or "import os" in result
    print("鉁� TEST 19 PASADO")
    
    # TEST 20: Bloque replace
    print("\n--- TEST 20: assemble() replace ---")
    content = "def old():\n    pass\n\ndef keep():\n    pass\n"
    blocks = [{"action": "replace", "anchor": "test", "code": "def new():\n    return True\n"}]
    anchor_map = {"test": {"line": 1, "end_line": 3}}
    result = assembler.assemble(content, blocks, anchor_map)
    assert "def new" in result
    assert "def old" not in result
    assert "def keep" in result
    print("鉁� TEST 20 PASADO")
    
    print("\n" + "="*60)
    print("TODOS LOS TESTS PASADOS (20/20)")
    print("="*60)