content = """# tools/test_target.py
# Archivo de prueba

def greet():
    pass
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from apa.core.assembler import Assembler

# Simular resolve_anchor
lines = content.split('\n')
last_import_line = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("import ") or stripped.startswith("from "):
        last_import_line = i + 1

print(f"last_import_line: {last_import_line}")

# Si no hay imports, buscar comentarios
last_comment_line = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("#"):
        last_comment_line = i + 1
    elif stripped:
        break

print(f"last_comment_line: {last_comment_line}")
print(f"FIN_IMPORTS retornaría línea: {last_comment_line if last_import_line == 0 else last_import_line}")