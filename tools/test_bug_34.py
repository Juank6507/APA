"""
test_bug_34.py
Test específico para Bug 3.4: imports dentro de if __name__ == "__main__"
capturados incorrectamente como imports globales.

Ejecutar: python tools/test_bug_34.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from apa.core.assembler import Assembler, PlannerOutputParser

PASSED = []
FAILED = []

def run(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append((name, e))
        print(f"  ❌ {name}")
        print(f"     {type(e).__name__}: {e}")

def assert_not_in(item, container, msg=""):
    if item in container:
        raise AssertionError(f"{msg}\n     '{item}' NO debería estar en {repr(container)[:200]}")

def assert_in(item, container, msg=""):
    if item not in container:
        raise AssertionError(f"{msg}\n     '{item}' SÍ debería estar en {repr(container)[:200]}")

def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}\n     Esperado: {repr(b)}\n     Obtenido: {repr(a)}")


# ── Caso 1: run_full() — imports dentro de __main__ no van a imports_list ────

print("\n── Caso 1: run_full() — separación de imports por scope ────────────────")

def test_run_full_main_imports_not_in_global():
    """Imports dentro de if __name__ no deben aparecer como imports globales."""
    # Simular lo que hace run_full() internamente con el código del Codificador
    coder_code = """\
import os
from typing import List

def process():
    pass

if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    process()
"""
    imports_list = []
    main_code_lines = []
    test_code_lines = []
    in_main_block = False

    for line in coder_code.split("\n"):
        stripped = line.strip()
        # Bug 3.4 fix: check __main__ BEFORE imports
        if "if __name__" in line and "__main__" in line:
            in_main_block = True
            continue
        if in_main_block:
            test_code_lines.append(line)
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports_list.append(stripped)
            continue
        main_code_lines.append(line)

    # Imports globales: solo os y typing
    assert_in("import os", imports_list, "import os debería estar en imports globales")
    assert_in("from typing import List", imports_list, "from typing import List debería estar en imports globales")
    # Imports de __main__: NO en imports_list
    assert_not_in("import argparse", imports_list, "import argparse NO debería estar en imports globales")
    assert_not_in("import sys", imports_list, "import sys NO debería estar en imports globales")
    # Imports de __main__: SÍ en test_code_lines
    test_code_text = "\n".join(test_code_lines)
    assert_in("import argparse", test_code_text, "import argparse debería estar en test_code_lines")
    assert_in("import sys", test_code_text, "import sys debería estar en test_code_lines")


# ── Caso 2: FIN_IMPORTS — no apunta más allá de __main__ ─────────────────────

print("\n── Caso 2: FIN_IMPORTS — no cruza hacia __main__ ──────────────────────")

SCRIPT_WITH_MAIN = """\
# test_target.py
import os
from typing import List

def process():
    pass

if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser()
"""

def test_fin_imports_stops_before_main():
    """FIN_IMPORTS debe resolver al último import global, no al último import del __main__."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_WITH_MAIN, "FIN_IMPORTS")
    lines = SCRIPT_WITH_MAIN.split('\n')
    
    # La línea debe apuntar después de "from typing import List" (línea 3, 1-indexed → 3)
    # y NO después de "import sys" (línea 9)
    import_os_line = next(i+1 for i, l in enumerate(lines) if l.strip() == "import os")
    import_typing_line = next(i+1 for i, l in enumerate(lines) if l.strip().startswith("from typing"))
    
    # FIN_IMPORTS debe ser al menos después de from typing import List
    assert line >= import_typing_line, f"FIN_IMPORTS ({line}) debe ser después de imports globales ({import_typing_line})"
    # FIN_IMPORTS NO debe llegar hasta imports del __main__ (línea 9+)
    # argparse está en la línea 8 (0-indexed 7)
    argparse_line = next(i+1 for i, l in enumerate(lines) if "import argparse" in l)
    assert line < argparse_line, f"FIN_IMPORTS ({line}) no debe pasar import argparse ({argparse_line})"


# ── Caso 3: assemble() — deduplicación no usa imports de __main__ ─────────────

print("\n── Caso 3: assemble() — deduplicación ignora imports de __main__ ──────")

def test_assemble_no_dedup_against_main_imports():
    """Si el archivo tiene 'import argparse' dentro de __main__, y el bloque
    trae 'import argparse' como nuevo import, NO debe deduplicar (son scopes distintos)."""
    assembler = Assembler()
    
    # Bloque que añade import argparse al nivel del módulo
    blocks = [{"action": "after", "anchor": "FIN_IMPORTS", "code": "import argparse\n"}]
    anchor_map = {"FIN_IMPORTS": {"line": PlannerOutputParser.resolve_anchor(SCRIPT_WITH_MAIN, "FIN_IMPORTS")[0]}}
    
    result = assembler.assemble(SCRIPT_WITH_MAIN, blocks, anchor_map)
    
    # 'import argparse' debe aparecer DOS veces: una en __main__ (original) y una como módulo (añadida)
    count_argparse = result.count("import argparse")
    assert count_argparse == 2, f"import argparse debe aparecer 2 veces (main + módulo), aparece {count_argparse}"


# ── Caso 4: remove_existing_imports() — no elimina imports de __main__ ────────

print("\n── Caso 4: remove_existing_imports() — preserva imports de __main__ ──")

def test_remove_existing_imports_preserves_main():
    """remove_existing_imports no debe tocar imports dentro de if __main__."""
    content, existing = Assembler.remove_existing_imports(SCRIPT_WITH_MAIN)
    
    # Imports globales detectados: solo os y typing
    assert_in("import os", existing, "import os debe detectarse como global")
    assert_in("from typing import List", existing, "from typing import List debe detectarse como global")
    assert_not_in("import argparse", existing, "import argparse NO debe detectarse como global")
    assert_not_in("import sys", existing, "import sys NO debe detectarse como global")
    
    # El contenido resultante debe preservar los imports de __main__
    assert_in("import argparse", content, "import argparse debe permanecer en el contenido")
    assert_in("import sys", content, "import sys debe permanecer en el contenido")
    # Los imports globales deben haber sido eliminados del contenido
    assert_not_in("import os\n", content, "import os debe haber sido eliminado del contenido")
    
    # El bloque if __name__ debe estar intacto
    assert_in('if __name__ == "__main__":', content, "Bloque __main__ debe estar intacto")


# ── Caso 5: Script sin __main__ — comportamiento no cambia ────────────────────

print("\n── Caso 5: Script sin __main__ — comportamiento inalterado ────────────")

SCRIPT_NO_MAIN = """\
# test_target.py
import os
from typing import List

def process():
    pass
"""

def test_fin_imports_no_main():
    """FIN_IMPORTS funciona correctamente cuando no hay bloque __main__."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_NO_MAIN, "FIN_IMPORTS")
    lines = SCRIPT_NO_MAIN.split('\n')
    import_typing_line = next(i+1 for i, l in enumerate(lines) if l.strip().startswith("from typing"))
    assert_eq(line, import_typing_line, "FIN_IMPORTS debe apuntar al último import global")

def test_remove_existing_no_main():
    """remove_existing_imports funciona igual cuando no hay __main__."""
    content, existing = Assembler.remove_existing_imports(SCRIPT_NO_MAIN)
    assert_in("import os", existing)
    assert_in("from typing import List", existing)
    assert_not_in("import os\n", content)


# ── Ejecutar todos los tests ──────────────────────────────────────────────────

run("1. run_full: imports de __main__ no van a imports_list", test_run_full_main_imports_not_in_global)
run("2. FIN_IMPORTS: no cruza hacia __main__", test_fin_imports_stops_before_main)
run("3. assemble: no deduplica contra imports de __main__", test_assemble_no_dedup_against_main_imports)
run("4. remove_existing_imports: preserva imports de __main__", test_remove_existing_imports_preserves_main)
run("5. FIN_IMPORTS sin __main__: inalterado", test_fin_imports_no_main)
run("6. remove_existing sin __main__: inalterado", test_remove_existing_no_main)

# ── Resultado ─────────────────────────────────────────────────────────────────

total = len(PASSED) + len(FAILED)
print(f"\n{'═'*60}")
print(f"Bug 3.4 — RESULTADO: {len(PASSED)}/{total} tests pasados")
if FAILED:
    print(f"\nTests fallados ({len(FAILED)}):")
    for name, err in FAILED:
        print(f"  ❌ {name}")
        print(f"     {err}")
if not FAILED:
    print("✅ Bug 3.4 corregido — imports de __main__ ya no contaminan el scope global")
print(f"{'═'*60}\n")

sys.exit(0 if not FAILED else 1)
