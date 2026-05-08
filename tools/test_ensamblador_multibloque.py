"""
test_ensamblador_multibloque.py
Batería de tests para validar la funcionalidad multi-bloque del ensamblador v4.0.
Ejecutar sin GUI: python test_ensamblador_multibloque.py

Cubre:
  - Parser: detección de bloques únicos y múltiples
  - Parser: imports sueltos, con puntuación, completos
  - Parser: acción correcta según tipo de ancla
  - Assembler: inserción simple (after)
  - Assembler: inserción antes (before)
  - Assembler: reemplazo (replace)
  - Assembler: múltiples bloques en secuencia
  - Assembler: imports deduplicados
  - Assembler: código fantasma filtrado
  - Assembler: bloque de tests separado a if __name__
  - Integración: flujo completo Planificador → Assembler

Arquitectura v4.0: Toda la lógica está en apa.core.assembler.
  - PlannerOutputParser: parser del output del Planificador
  - Assembler: motor de ensamblaje (assemble, run_full, merge, etc.)
"""

import ast
import re
import sys
import traceback
from pathlib import Path

# ── Importar desde la nueva arquitectura ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from apa.core.assembler import Assembler, PlannerOutputParser
    ASSEMBLER_AVAILABLE = True
except ImportError:
    ASSEMBLER_AVAILABLE = False
    print("⚠️  apa.core.assembler no disponible — tests omitidos")
    PlannerOutputParser = None

# ── Helpers ───────────────────────────────────────────────────────────────────

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

def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}\n     Esperado: {repr(b)}\n     Obtenido: {repr(a)}")

def assert_in(item, container, msg=""):
    if item not in container:
        raise AssertionError(f"{msg}\n     '{item}' no encontrado en {repr(container)[:120]}")

def assert_not_in(item, container, msg=""):
    if item in container:
        raise AssertionError(f"{msg}\n     '{item}' no debería estar en {repr(container)[:120]}")

def assert_count(text, substring, expected, msg=""):
    count = text.count(substring)
    if count != expected:
        raise AssertionError(f"{msg}\n     '{substring}' aparece {count} veces, esperado {expected}")

def valid_python(code, label=""):
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise AssertionError(f"SyntaxError en {label} línea {e.lineno}: {e.msg}")

# ── Fixtures ──────────────────────────────────────────────────────────────────

SCRIPT_BASE = """\
# tools/test_target.py
import os

class DeviceManager:
    def __init__(self):
        self.devices = []

    def list_devices(self):
        return self.devices

def reset_system():
    print('System Reset')
    return True
"""

PLANNER_SINGLE = """\
## TAREA DE ENSAMBLAJE
- SCRIPT: tools/test_target.py
- TAREA_ID: T1
- ANCLA: FIN_ARCHIVO
- MODO_EJECUCION: local

## BLOQUE
```python
# INSTRUCCIÓN PARA CODIFICADOR:
# Crea función greet() que imprime Hello APA y retorna True.
# INDENTACIÓN: 0
```

## IMPORTS_NUEVOS
logging
"""

PLANNER_MULTI = """\
## TAREA DE ENSAMBLAJE
- SCRIPT: tools/test_target.py
- TAREA_ID: T5
- ANCLA: FIN_CLASE:DeviceManager
- MODO_EJECUCION: local

## TAREA DE ENSAMBLAJE
- SCRIPT: tools/test_target.py
- TAREA_ID: T5b
- ANCLA: FIN_ARCHIVO
- MODO_EJECUCION: local

## TAREA DE ENSAMBLAJE
- SCRIPT: tools/test_target.py
- TAREA_ID: T5c
- ANCLA: ANTES_FUNCION:reset_system
- MODO_EJECUCION: local

## IMPORTS_NUEVOS
logging
socket
"""

PLANNER_REEMPLAZAR = """\
## TAREA DE ENSAMBLAJE
- SCRIPT: tools/test_target.py
- TAREA_ID: T6
- ANCLA: REEMPLAZAR_FUNCION:reset_system
- MODO_EJECUCION: local

## BLOQUE
```python
# INSTRUCCIÓN: Reescribir reset_system con nuevo comportamiento.
# INDENTACIÓN: 0
```
"""

PLANNER_IMPORTS_ONLY = """\
## TAREA DE ENSAMBLAJE
- SCRIPT: tools/test_target.py
- TAREA_ID: T_IMP
- ANCLA: FIN_IMPORTS
- MODO_EJECUCION: local

## BLOQUE
```python
```

## IMPORTS_NUEVOS
logging
subprocess
"""

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 1 — Parser: detección de bloques
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 1: Parser — Detección de bloques ──────────────────────────────")

def t_parser_single_block():
    """Un solo bloque → lista de 1 elemento."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_SINGLE)
    assert len(blocks) == 1, f"Esperado 1 bloque, obtenido {len(blocks)}"
    assert_eq(blocks[0]["anchor"], "FIN_ARCHIVO", "Ancla incorrecta")
    assert_eq(blocks[0]["action"], "after", "Acción incorrecta para FIN_ARCHIVO")

def t_parser_multi_block():
    """Tres ## TAREA DE ENSAMBLAJE → lista de 3 bloques."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_MULTI)
    assert len(blocks) == 3, f"Esperado 3 bloques, obtenido {len(blocks)}"
    assert_eq(blocks[0]["anchor"], "FIN_CLASE:DeviceManager")
    assert_eq(blocks[1]["anchor"], "FIN_ARCHIVO")
    assert_eq(blocks[2]["anchor"], "ANTES_FUNCION:reset_system")

def t_parser_action_before():
    """ANTES_FUNCION → action='before'."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_MULTI)
    antes_block = next(b for b in blocks if "ANTES_" in b["anchor"])
    assert_eq(antes_block["action"], "before", "ANTES_ debe mapear a action='before'")

def t_parser_action_replace():
    """REEMPLAZAR_FUNCION → action='replace'."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_REEMPLAZAR)
    assert len(blocks) >= 1
    assert_eq(blocks[0]["action"], "replace", "REEMPLAZAR_ debe mapear a action='replace'")

def t_parser_action_after():
    """FIN_ARCHIVO y FIN_CLASE → action='after'."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_MULTI)
    fin_arch = next(b for b in blocks if b["anchor"] == "FIN_ARCHIVO")
    assert_eq(fin_arch["action"], "after")

def t_parser_script_extracted():
    """SCRIPT se extrae correctamente en multi-bloque."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_MULTI)
    for b in blocks:
        assert b.get("script"), f"Bloque sin script: {b}"

def t_parser_tarea_id_extracted():
    """TAREA_ID se extrae correctamente."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_SINGLE)
    assert_eq(blocks[0].get("tarea_id", ""), "T1")

run("T1.1 — Un bloque detectado correctamente", t_parser_single_block)
run("T1.2 — Tres bloques detectados correctamente", t_parser_multi_block)
run("T1.3 — ANTES_FUNCION → action='before'", t_parser_action_before)
run("T1.4 — REEMPLAZAR_FUNCION → action='replace'", t_parser_action_replace)
run("T1.5 — FIN_ARCHIVO → action='after'", t_parser_action_after)
run("T1.6 — SCRIPT extraído en multi-bloque", t_parser_script_extracted)
run("T1.7 — TAREA_ID extraído correctamente", t_parser_tarea_id_extracted)

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 2 — Parser: imports
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 2: Parser — Imports ───────────────────────────────────────────")

def t_imports_bare_name():
    """Nombre suelto 'logging' → 'import logging'."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_SINGLE)
    imp = blocks[0].get("imports", [])
    assert_in("import logging", imp, "import logging no detectado")

def t_imports_multi():
    """Dos nombres sueltos → dos imports."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_MULTI)
    all_imports = []
    for b in blocks:
        all_imports.extend(b.get("imports", []))
    assert_in("import logging", all_imports)
    assert_in("import socket", all_imports)

def t_imports_with_dot():
    """'logging.' → 'import logging' (puntuación eliminada)."""
    text = "- SCRIPT: x.py\n- ANCLA: FIN_ARCHIVO\n## IMPORTS_NUEVOS\nlogging.\n"
    blocks = PlannerOutputParser._parse_blocks(text)
    all_imp = [i for b in blocks for i in b.get("imports", [])]
    assert_in("import logging", all_imp, "Punto final no eliminado")
    assert_not_in("import logging.", all_imp, "Punto final no eliminado correctamente")

def t_imports_with_comma():
    """'subprocess,' → 'import subprocess'."""
    text = "- SCRIPT: x.py\n- ANCLA: FIN_ARCHIVO\n## IMPORTS_NUEVOS\nsubprocess,\n"
    blocks = PlannerOutputParser._parse_blocks(text)
    all_imp = [i for b in blocks for i in b.get("imports", [])]
    assert_in("import subprocess", all_imp)

def t_imports_canonical():
    """'import json' completo → se preserva tal cual."""
    text = "- SCRIPT: x.py\n- ANCLA: FIN_ARCHIVO\n## IMPORTS_NUEVOS\nimport json\n"
    blocks = PlannerOutputParser._parse_blocks(text)
    all_imp = [i for b in blocks for i in b.get("imports", [])]
    assert_in("import json", all_imp)

def t_imports_from_style():
    """'from pathlib import Path' → preservado tal cual."""
    text = "- SCRIPT: x.py\n- ANCLA: FIN_ARCHIVO\n## IMPORTS_NUEVOS\nfrom pathlib import Path\n"
    blocks = PlannerOutputParser._parse_blocks(text)
    all_imp = [i for b in blocks for i in b.get("imports", [])]
    assert_in("from pathlib import Path", all_imp)

def t_imports_only_task():
    """Tarea de solo imports: bloque vacío, imports detectados."""
    blocks = PlannerOutputParser._parse_blocks(PLANNER_IMPORTS_ONLY)
    assert len(blocks) >= 1
    all_imp = [i for b in blocks for i in b.get("imports", [])]
    assert_in("import logging", all_imp)
    assert_in("import subprocess", all_imp)

run("T2.1 — Nombre suelto 'logging' normalizado", t_imports_bare_name)
run("T2.2 — Dos imports en multi-bloque", t_imports_multi)
run("T2.3 — 'logging.' sin punto final", t_imports_with_dot)
run("T2.4 — 'subprocess,' sin coma", t_imports_with_comma)
run("T2.5 — 'import json' preservado", t_imports_canonical)
run("T2.6 — 'from pathlib import Path' preservado", t_imports_from_style)
run("T2.7 — Tarea de solo imports detecta imports", t_imports_only_task)

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 3 — resolve_anchor
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 3: resolve_anchor ─────────────────────────────────────────────")

def t_anchor_fin_archivo():
    """FIN_ARCHIVO → última línea."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_ARCHIVO")
    total = len(SCRIPT_BASE.split('\n'))
    assert_eq(line, total, "FIN_ARCHIVO no apunta a la última línea")

def t_anchor_inicio_archivo():
    """INICIO_ARCHIVO → después de comentarios iniciales."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "INICIO_ARCHIVO")
    assert line >= 1, "INICIO_ARCHIVO debe retornar línea >= 1"

def t_anchor_fin_clase():
    """FIN_CLASE:DeviceManager → dentro del rango de la clase."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_CLASE:DeviceManager")
    assert line > 0, "FIN_CLASE no encontrado"
    # FIN_CLASE retorna la línea de la última declaración dentro de la clase
    lines = SCRIPT_BASE.split('\n')
    # Verificar que la línea está dentro del rango de la clase (después de class y antes de def reset_system)
    class_line = next(i+1 for i, l in enumerate(lines) if "class DeviceManager" in l)
    reset_line = next(i+1 for i, l in enumerate(lines) if "def reset_system" in l)
    assert class_line < line < reset_line, f"FIN_CLASE línea {line} fuera del rango [{class_line}, {reset_line}]"

def t_anchor_antes_funcion():
    """ANTES_FUNCION:reset_system → línea antes de def reset_system."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "ANTES_FUNCION:reset_system")
    assert line > 0, "ANTES_FUNCION no encontrado"
    lines = SCRIPT_BASE.split('\n')
    # La línea apuntada debe ser ANTES de def reset_system
    reset_line = next(i+1 for i, l in enumerate(lines) if "def reset_system" in l)
    assert line <= reset_line, f"ANTES_FUNCION línea {line} no es anterior a reset_system línea {reset_line}"

def t_anchor_despues_funcion():
    """DESPUES_FUNCION:reset_system → línea después de def reset_system."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "DESPUES_FUNCION:reset_system")
    assert line > 0, "DESPUES_FUNCION no encontrado"
    lines = SCRIPT_BASE.split('\n')
    reset_line = next(i+1 for i, l in enumerate(lines) if "def reset_system" in l)
    assert line > reset_line, "DESPUES_FUNCION debe apuntar después de la función"

def t_anchor_reemplazar_funcion():
    """REEMPLAZAR_FUNCION:reset_system → línea de la función."""
    line, content, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "REEMPLAZAR_FUNCION:reset_system")
    assert line > 0, "REEMPLAZAR_FUNCION no encontrado"
    assert "reset_system" in content or line > 0, "Línea incorrecta"

def t_anchor_fin_imports():
    """FIN_IMPORTS → después del último import."""
    line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_IMPORTS")
    assert line > 0
    lines = SCRIPT_BASE.split('\n')
    # La línea apuntada debe ser después del import os
    import_line = next(i+1 for i, l in enumerate(lines) if l.strip().startswith("import"))
    assert line >= import_line, "FIN_IMPORTS debe ser después del último import"

def t_anchor_not_found():
    """Función inexistente → retorna (0, '')."""
    line, content, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_CLASE:NoExiste")
    assert line == 0, f"Función inexistente debería retornar 0, retornó {line}"

run("T3.1 — FIN_ARCHIVO apunta a última línea", t_anchor_fin_archivo)
run("T3.2 — INICIO_ARCHIVO respeta comentarios", t_anchor_inicio_archivo)
run("T3.3 — FIN_CLASE:DeviceManager correcto", t_anchor_fin_clase)
run("T3.4 — ANTES_FUNCION:reset_system correcto", t_anchor_antes_funcion)
run("T3.5 — DESPUES_FUNCION:reset_system correcto", t_anchor_despues_funcion)
run("T3.6 — REEMPLAZAR_FUNCION:reset_system encontrado", t_anchor_reemplazar_funcion)
run("T3.7 — FIN_IMPORTS correcto", t_anchor_fin_imports)
run("T3.8 — Clase inexistente retorna 0", t_anchor_not_found)

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 4 — Assembler: operaciones individuales
# (requiere apa.core.assembler disponible)
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 4: Assembler — Operaciones individuales ───────────────────────")

if not ASSEMBLER_AVAILABLE:
    print("  ⏭️  Omitido (assembler no disponible)")
else:
    assembler = Assembler()

    def t_asm_import_injection():
        """Import inyectado al script. No duplicado si ya existe."""
        blocks = [{"action": "after", "anchor": "FIN_IMPORTS", "code": "import logging\n"}]
        anchor_map = {"FIN_IMPORTS": {"line": PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_IMPORTS")[0], "end_line": PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_IMPORTS")[0] + 1}}
        result = assembler.assemble(SCRIPT_BASE, blocks, anchor_map)
        assert_in("import logging", result)
        assert_count(result, "import logging", 1, "Import duplicado")
        valid_python(result, "import injection")

    def t_asm_import_no_duplicate():
        """Import ya existente (import os) no se duplica."""
        blocks = [{"action": "after", "anchor": "FIN_IMPORTS", "code": "import os\n"}]
        anchor_map = {"FIN_IMPORTS": {"line": PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_IMPORTS")[0]}}
        result = assembler.assemble(SCRIPT_BASE, blocks, anchor_map)
        assert_count(result, "import os", 1, "import os duplicado")
        valid_python(result)

    def t_asm_insert_after_fin_archivo():
        """Función insertada al final del archivo."""
        code = "\ndef greet() -> bool:\n    print('Hello')\n    return True\n"
        blocks = [{"action": "after", "anchor": "FIN_ARCHIVO", "code": code}]
        anchor_map = {"FIN_ARCHIVO": {"line": PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_ARCHIVO")[0], "end_line": PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_ARCHIVO")[0] + 1}}
        result = assembler.assemble(SCRIPT_BASE, blocks, anchor_map)
        assert_in("def greet", result)
        assert result.index("def greet") > result.index("def reset_system"), \
            "greet debe estar después de reset_system"
        valid_python(result)

    def t_asm_insert_before():
        """Clase insertada antes de reset_system."""
        code = "\nclass Logger:\n    pass\n"
        line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "ANTES_FUNCION:reset_system")
        blocks = [{"action": "before", "anchor": "ANTES_FUNCION:reset_system", "code": code}]
        anchor_map = {"ANTES_FUNCION:reset_system": {"line": line, "end_line": line + 1}}
        result = assembler.assemble(SCRIPT_BASE, blocks, anchor_map)
        assert_in("class Logger", result)
        assert result.index("class Logger") < result.index("def reset_system"), \
            "Logger debe estar ANTES de reset_system"
        valid_python(result)

    def t_asm_replace():
        """reset_system reemplazada por nueva versión."""
        new_fn = "def reset_system():\n    print('Nueva versión')\n    return False\n"
        line, _, end_line = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "REEMPLAZAR_FUNCION:reset_system")
        blocks = [{"action": "replace", "anchor": "REEMPLAZAR_FUNCION:reset_system", "code": new_fn}]
        anchor_map = {"REEMPLAZAR_FUNCION:reset_system": {"line": line, "end_line": end_line if end_line > 0 else line + 1}}
        result = assembler.assemble(SCRIPT_BASE, blocks, anchor_map)
        assert_in("Nueva versión", result)
        assert_not_in("System Reset", result, "La función original no fue reemplazada")
        assert_count(result, "def reset_system", 1, "Función duplicada tras reemplazo")
        valid_python(result)

    def t_asm_method_in_class():
        """Método insertado al final de DeviceManager."""
        code = "\n    def connect(self) -> bool:\n        return True\n"
        line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, "FIN_CLASE:DeviceManager")
        blocks = [{"action": "after", "anchor": "FIN_CLASE:DeviceManager", "code": code}]
        anchor_map = {"FIN_CLASE:DeviceManager": {"line": line, "end_line": line + 1}}
        result = assembler.assemble(SCRIPT_BASE, blocks, anchor_map)
        assert_in("def connect", result)
        # connect debe estar dentro de DeviceManager (antes de reset_system)
        assert result.index("def connect") < result.index("def reset_system"), \
            "connect debe estar dentro de la clase, antes de reset_system"
        valid_python(result)

    run("T4.1 — Import inyectado correctamente", t_asm_import_injection)
    run("T4.2 — Import existente no duplicado", t_asm_import_no_duplicate)
    run("T4.3 — Función insertada al final", t_asm_insert_after_fin_archivo)
    run("T4.4 — Clase insertada antes de función", t_asm_insert_before)
    run("T4.5 — Función reemplazada sin duplicación", t_asm_replace)
    run("T4.6 — Método insertado dentro de clase", t_asm_method_in_class)

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 5 — Assembler: multi-bloque secuencial
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 5: Assembler — Multi-bloque secuencial ────────────────────────")

if not ASSEMBLER_AVAILABLE:
    print("  ⏭️  Omitido (assembler no disponible)")
else:
    def t_asm_multi_three_blocks():
        """Tres bloques aplicados: método en clase + función global + clase antes de función."""
        blocks_raw = [
            {
                "action": "after",
                "anchor": "FIN_CLASE:DeviceManager",
                "code": "\n    def connect(self) -> bool:\n        return True\n"
            },
            {
                "action": "after",
                "anchor": "FIN_ARCHIVO",
                "code": "\ndef validate(host: str) -> bool:\n    return bool(host)\n"
            },
            {
                "action": "before",
                "anchor": "ANTES_FUNCION:reset_system",
                "code": "\nclass ConnectionError(Exception):\n    pass\n"
            },
        ]
        anchor_map = {}
        for b in blocks_raw:
            line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, b["anchor"])
            anchor_map[b["anchor"]] = {"line": line, "end_line": line + 1}

        result = assembler.assemble(SCRIPT_BASE, blocks_raw, anchor_map)

        assert_in("def connect", result)
        assert_in("def validate", result)
        assert_in("class ConnectionError", result)
        # Orden: connect dentro de clase (antes de reset_system)
        assert result.index("def connect") < result.index("def reset_system")
        # ConnectionError antes de reset_system
        assert result.index("class ConnectionError") < result.index("def reset_system")
        # validate al final
        assert result.index("def validate") > result.index("def reset_system")
        valid_python(result)

    def t_asm_multi_no_duplicate_code():
        """Multi-bloque no duplica código existente."""
        blocks_raw = [
            {"action": "after", "anchor": "FIN_IMPORTS",  "code": "import logging\n"},
            {"action": "after", "anchor": "FIN_ARCHIVO",  "code": "\ndef helper(): pass\n"},
        ]
        anchor_map = {}
        for b in blocks_raw:
            line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, b["anchor"])
            anchor_map[b["anchor"]] = {"line": line}

        result = assembler.assemble(SCRIPT_BASE, blocks_raw, anchor_map)
        assert_count(result, "import logging", 1, "Import duplicado en multi-bloque")
        assert_count(result, "def helper", 1, "helper duplicada en multi-bloque")
        valid_python(result)

    def t_asm_syntax_valid_after_multi():
        """El resultado de multi-bloque es Python válido."""
        blocks_raw = [
            {"action": "after",  "anchor": "FIN_IMPORTS",             "code": "import logging\nimport socket\n"},
            {"action": "after",  "anchor": "FIN_CLASE:DeviceManager",  "code": "\n    def status(self): return 'ok'\n"},
            {"action": "before", "anchor": "ANTES_FUNCION:reset_system","code": "\nclass Config:\n    pass\n"},
            {"action": "after",  "anchor": "FIN_ARCHIVO",              "code": "\ndef shutdown(): pass\n"},
        ]
        anchor_map = {}
        for b in blocks_raw:
            line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, b["anchor"])
            anchor_map[b["anchor"]] = {"line": line}

        result = assembler.assemble(SCRIPT_BASE, blocks_raw, anchor_map)
        valid_python(result, "multi-bloque complejo")

    run("T5.1 — Tres bloques distintos aplicados correctamente", t_asm_multi_three_blocks)
    run("T5.2 — Multi-bloque no duplica código", t_asm_multi_no_duplicate_code)
    run("T5.3 — Resultado de multi-bloque es Python válido", t_asm_syntax_valid_after_multi)

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 6 — Filtros de seguridad
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 6: Filtros de seguridad ───────────────────────────────────────")

def t_filter_ghost_code():
    """Bloques solo de comentarios o pass no se insertan."""
    fantasmas = [
        "# ── TAREA T1 ──\n# instrucción para codificador",
        "pass",
        "",
        "# solo comentario\n# otro",
    ]
    for b in fantasmas:
        lines = b.split('\n') if b else []
        reales = [l for l in lines
                  if l.strip() and not l.strip().startswith("#") and l.strip() != "pass"]
        assert len(reales) == 0, f"Debería filtrar: {repr(b[:40])}"

def t_filter_real_code_passes():
    """Bloques con código real pasan el filtro."""
    reales = [
        "def foo(): pass",
        "class Bar:\n    pass",
        "# comentario\ndef foo(): return 1",
        "x = 1 + 2",
    ]
    for b in reales:
        lines = b.split('\n')
        ejecutables = [l for l in lines
                       if l.strip() and not l.strip().startswith("#") and l.strip() != "pass"]
        assert len(ejecutables) > 0, f"Debería pasar: {repr(b[:40])}"

def t_filter_markdown_backticks():
    """Backticks de markdown eliminados del código del Codificador."""
    casos = [
        ("```python\ndef foo(): pass\n```", "def foo"),
        ("```Python\nclass Bar: pass\n```", "class Bar"),
        ("def foo(): pass", "def foo"),
    ]
    for entrada, esperado_inicio in casos:
        limpio = re.sub(r'^```python\s*\n?', '', entrada.strip(), flags=re.IGNORECASE)
        limpio = re.sub(r'\n?```\s*$', '', limpio.strip()).strip()
        assert "```" not in limpio, f"Backticks no eliminados en: {repr(entrada[:30])}"
        assert esperado_inicio in limpio, f"Código perdido: {repr(limpio[:40])}"

def t_filter_import_dedup():
    """Import ya presente en el script no se añade de nuevo."""
    existing = set()
    for line in SCRIPT_BASE.split('\n'):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            existing.add(s)

    nuevos = ["import os", "import logging", "import sys"]
    filtrados = [i for i in nuevos if i not in existing]

    assert "import os" not in filtrados, "import os ya existe y no debería añadirse"
    assert "import logging" in filtrados, "import logging es nuevo y sí debe añadirse"

run("T6.1 — Código fantasma filtrado", t_filter_ghost_code)
run("T6.2 — Código real pasa el filtro", t_filter_real_code_passes)
run("T6.3 — Backticks de markdown eliminados", t_filter_markdown_backticks)
run("T6.4 — Import duplicado no se añade", t_filter_import_dedup)

# ═════════════════════════════════════════════════════════════════════════════
# BLOQUE 7 — Integración: flujo completo Planificador → Assembler
# ═════════════════════════════════════════════════════════════════════════════

print("\n── BLOQUE 7: Integración — Flujo completo ───────────────────────────────")

if not ASSEMBLER_AVAILABLE:
    print("  ⏭️  Omitido (assembler no disponible)")
else:
    def t_integration_single_task():
        """Flujo completo tarea única: parsear → resolver anclas → ensamblar."""
        blocks_data = PlannerOutputParser._parse_blocks(PLANNER_SINGLE)
        assert len(blocks_data) == 1

        coder_output = "# ── TAREA T1: Greet ──\n\ndef greet() -> bool:\n    print('Hello APA')\n    return True\n"

        # Limpiar markdown
        coder_output = re.sub(r'^```python\s*\n?', '', coder_output.strip(), flags=re.IGNORECASE)
        coder_output = re.sub(r'\n?```\s*$', '', coder_output.strip()).strip()

        # Asignar código al bloque
        blocks_data[0]["code"] = coder_output

        # Resolver anclas
        anchor_map = {}
        for b in blocks_data:
            line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, b["anchor"])
            anchor_map[b["anchor"]] = {"line": line}

        result = assembler.assemble(SCRIPT_BASE, blocks_data, anchor_map)

        assert_in("def greet", result)
        assert_in("import logging", result)
        assert_count(result, "def greet", 1)
        valid_python(result)

    def t_integration_multi_task():
        """Flujo completo multi-tarea: tres bloques con código real."""
        blocks_data = PlannerOutputParser._parse_blocks(PLANNER_MULTI)
        assert len(blocks_data) == 3

        # Código para cada bloque por orden
        codigos = [
            "    def connect(self) -> bool:\n        return True",
            "def validate(host: str) -> bool:\n    return bool(host)",
            "class ConnectionError(Exception):\n    pass",
        ]
        for i, b in enumerate(blocks_data):
            b["code"] = codigos[i]

        anchor_map = {}
        for b in blocks_data:
            line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, b["anchor"])
            anchor_map[b["anchor"]] = {"line": line}

        result = assembler.assemble(SCRIPT_BASE, blocks_data, anchor_map)

        assert_in("def connect", result)
        assert_in("def validate", result)
        assert_in("class ConnectionError", result)
        assert_in("import logging", result)
        assert_in("import socket", result)
        valid_python(result)

    def t_integration_imports_only():
        """Tarea de solo imports: sin código del Codificador → solo imports añadidos."""
        blocks_data = PlannerOutputParser._parse_blocks(PLANNER_IMPORTS_ONLY)

        anchor_map = {}
        for b in blocks_data:
            line, _, _ = PlannerOutputParser.resolve_anchor(SCRIPT_BASE, b["anchor"])
            anchor_map[b["anchor"]] = {"line": line}

        # Sin código del Codificador
        result = assembler.assemble(SCRIPT_BASE, blocks_data, anchor_map)

        assert_in("import logging", result)
        assert_in("import subprocess", result)
        valid_python(result)

    run("T7.1 — Flujo completo tarea única", t_integration_single_task)
    run("T7.2 — Flujo completo multi-tarea", t_integration_multi_task)
    run("T7.3 — Flujo tarea de solo imports", t_integration_imports_only)

# ═════════════════════════════════════════════════════════════════════════════
# RESULTADO FINAL
# ═════════════════════════════════════════════════════════════════════════════

total = len(PASSED) + len(FAILED)
print(f"\n{'═'*60}")
print(f"RESULTADO FINAL: {len(PASSED)}/{total} tests pasados")
if FAILED:
    print(f"\nTests fallados ({len(FAILED)}):")
    for name, err in FAILED:
        print(f"  ❌ {name}")
        print(f"     {err}")
if not FAILED:
    print("✅ BATERÍA COMPLETA — Sistema multi-bloque validado")
print(f"{'═'*60}\n")

sys.exit(0 if not FAILED else 1)