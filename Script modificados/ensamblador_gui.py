# tools/ensamblador_gui.py — Procesador de Prompts y Ensamblador Atómico (v3.0)

import ast
import json
import re
import os
import shutil
import subprocess
import threading
import tkinter as tk
import difflib

from tkinter import scrolledtext, messagebox, filedialog, ttk
from pathlib import Path
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apa.core.assembler import Assembler, AssemblyResult

try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    
# ─────────────────────────────────────────────────────────────────────────────
# Tooltip
# ─────────────────────────────────────────────────────────────────────────────

class ToolTip:
    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip = None
        self.after_id = None
        widget.bind("<Enter>", self.schedule, "+")
        widget.bind("<Leave>", self.hide, "+")
        widget.bind("<ButtonPress>", self.hide, "+")

    def schedule(self, _=None):
        self.hide()
        self.after_id = self.widget.after(self.delay, self.show)

    def hide(self, _=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def show(self, _=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tooltip, text=self.text, background="#ffffe0", foreground="#000",
                 font=("Segoe UI", 9), padx=8, pady=4,
                 relief="solid", borderwidth=1).pack()

# ─────────────────────────────────────────────────────────────────────────────
# Diálogo Estructura Duplicada (4 opciones)
# ─────────────────────────────────────────────────────────────────────────────

class DuplicateStructureDialog(tk.Toplevel):
    """Diálogo modal con 4 opciones para estructuras duplicadas.
    
    Retorna:
        'replace'  = Reemplazar estructura existente completa
        'modify'   = Modificar (merge inteligente: actualizar solo cambios internos)
        'discard'  = Descartar (considerar implementada)
        'cancel'   = Detener operación
    """
    def __init__(self, parent, title, message, has_class=False):
        super().__init__(parent)
        self.result = 'cancel'
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        
        # Configurar como modal
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        
        # Frame principal con padding
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Mensaje
        msg_label = ttk.Label(main_frame, text=message, justify=tk.LEFT, wraplength=450)
        msg_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Frame de botones
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)
        
        # Botones
        btn_replace = ttk.Button(btn_frame, text="Reemplazar", command=self._on_replace)
        btn_replace.pack(side=tk.LEFT, padx=3)
        ToolTip(btn_replace, "Elimina la estructura existente y la sustituye por la nueva")
        
        if has_class:
            btn_modify = ttk.Button(btn_frame, text="Modificar", command=self._on_modify)
            btn_modify.pack(side=tk.LEFT, padx=3)
            ToolTip(btn_modify, "Merge inteligente: mantiene la clase existente y actualiza solo los métodos que cambiaron")
        
        btn_discard = ttk.Button(btn_frame, text="Descartar", command=self._on_discard)
        btn_discard.pack(side=tk.LEFT, padx=3)
        ToolTip(btn_discard, "No aplicar cambios, considerar la estructura como ya implementada")
        
        btn_cancel = ttk.Button(btn_frame, text="Cancelar", command=self._on_cancel)
        btn_cancel.pack(side=tk.LEFT, padx=3)
        ToolTip(btn_cancel, "Detener toda la operación de ensamblaje")
        
        # Centrar en pantalla
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f'+{x}+{y}')
        
        # Esperar a que se cierre
        self.wait_window()
    
    def _on_replace(self):
        self.result = 'replace'
        self.destroy()
    
    def _on_modify(self):
        self.result = 'modify'
        self.destroy()
    
    def _on_discard(self):
        self.result = 'discard'
        self.destroy()
    
    def _on_cancel(self):
        self.result = 'cancel'
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
# Parser del output del Planificador (VERSIÓN ESTRUCTURAL AST)
# ─────────────────────────────────────────────────────────────────────────────

class PlannerOutputParser:
    # Regex para campos escalares (tolerantes a espacios y mayúsculas)
    _RE_INDENT       = re.compile(r'#*\s*(?:-|##)?\s*#\s*INDENTACIÓN\s*:\s*(\d+)', re.IGNORECASE)
    _RE_SCRIPT       = re.compile(r'#*\s*(?:-|##)?\s*SCRIPT\s*:\s*(.+)', re.IGNORECASE)
    _RE_TAREA_ID     = re.compile(r'#*\s*(?:-|##)?\s*TAREA_?ID\s*:\s*(\S+)', re.IGNORECASE)
    _RE_ANCLA        = re.compile(r'#*\s*(?:-|##)?\s*ANCLA\s*:\s*(.+)', re.IGNORECASE)
    _RE_MODO         = re.compile(r'#*\s*(?:-|##)?\s*MODO_?EJECUCION\s*:\s*(\S+)', re.IGNORECASE)
    _RE_CONTEXTO     = re.compile(r'#*\s*(?:-|##)?\s*CONTEXTO\s*:\s*(.+)', re.IGNORECASE)
    _RE_COINCIDENCIA = re.compile(r'#*\s*(?:-|##)?\s*COINCIDENCIA\s*:\s*(\S+)', re.IGNORECASE)
    _RE_LINEA        = re.compile(r'#*\s*(?:-|##)?\s*LINEA\s*:\s*(\d+)', re.IGNORECASE)
    _RE_RANGO        = re.compile(r'#*\s*(?:-|##)?\s*RANGO\s*:\s*(\d+)\s*-\s*(\d+)', re.IGNORECASE)
    
    @staticmethod    
    def _sanitize_module(name: str) -> str:
        """
        FIX P1 — Limpia un nombre de módulo de puntuación espuria.
        'logging.'  → 'logging'
        'logging, ' → 'logging'
        ' os '      → 'os'
        """
        return name.strip().rstrip('.,; \t')

    @staticmethod
    def _parse_method_reference(ref: str) -> tuple:
        """
        Parsea notación 'Clase.metodo' → ('Clase', 'metodo')
        Parsea 'metodo' → (None, 'metodo')
        
        Retorna: (nombre_clase, nombre_metodo)
        """
        if '.' in ref:
            parts = ref.split('.', 1)
            return parts[0].strip(), parts[1].strip()
        return None, ref.strip()
    
    @classmethod
    def _parse_imports(cls, text: str) -> list:
        """
        Parser robusto de imports.
        Acepta:
        - Nombres sueltos con prefijo '-': '- logging' → 'import logging'
        - Nombres con puntuación: 'logging.' → 'import logging'
        - Imports completos: 'import os' → 'import os'
        - From imports: 'from pathlib import Path'
        """
        imports = []

        # Buscar sección ## IMPORTS_NUEVOS
        marker = None

        marker = None
        for line in text.split('\n'):
            if re.search(r'##\s*IMPORTS_NUEVOS', line, re.IGNORECASE):
                marker = line
                break

        if marker is None:
            return imports

        # Todo lo que viene después del marcador hasta la siguiente sección ##
        after = text.split(marker, 1)[1]
        section_lines = []
        for line in after.split('\n'):
            if line.strip().startswith('##'):
                break
            section_lines.append(line)

        for line in section_lines:
            raw = line.strip()
            if not raw or raw.startswith('#'):
                continue

            # Quitar prefijo "-" si existe
            if raw.startswith('- '):
                raw = raw[2:].strip()
            elif raw.startswith('-'):
                raw = raw[1:].strip()
            
            if not raw:
                continue

            # Import completo: 'import x' o 'from x import y'
            if raw.startswith("import ") or raw.startswith("from "):
                canonical = raw
            else:
                # Nombre suelto: limpiar y construir import
                clean = cls._sanitize_module(raw)
                if not clean:
                    continue
                if not re.match(r'^[\w][\w\.]*$', clean):
                    continue
                canonical = "import " + clean

            if canonical not in imports:
                imports.append(canonical)

        return imports

    @classmethod
    def parse(cls, text: str) -> dict:
        result = {
            "script": "", 
            "tarea_id": "", 
            "ancla_raw": "",
            "modo": "local", 
            "imports_nuevos": [], 
            "errores": [],
            "contexto": "",
            "coincidencia": "PRIMERA",
            "linea": None,
            "rango_inicio": None,
            "rango_fin": None,
            "indentacion": 0,
        }

        for pattern, key in [
            (cls._RE_SCRIPT,       "script"),
            (cls._RE_TAREA_ID,     "tarea_id"),
            (cls._RE_ANCLA,        "ancla_raw"),
            (cls._RE_MODO,         "modo"),
            (cls._RE_CONTEXTO,     "contexto"),
            (cls._RE_COINCIDENCIA, "coincidencia"),
        ]:
            m = pattern.search(text)
            if m:
                result[key] = m.group(1).strip()

        # Parsear LINEA
        m = cls._RE_LINEA.search(text)
        if m:
            result["linea"] = int(m.group(1))

        # Parsear RANGO
        m = cls._RE_RANGO.search(text)
        if m:
            result["rango_inicio"] = int(m.group(1))
            result["rango_fin"] = int(m.group(2))

        # Parsear INDENTACIÓN
        m = cls._RE_INDENT.search(text)
        if m:
            result["indentacion"] = int(m.group(1))

        result["modo"] = "nas" if "nas" in result["modo"].lower() else "local"
        result["imports_nuevos"] = cls._parse_imports(text)

        if not result["script"]:
            result["errores"].append("Falta campo SCRIPT.")
        if not result["ancla_raw"]:
            result["errores"].append("Falta campo ANCLA.")

        return result        

    @classmethod
    def _parse_blocks(cls, text: str) -> list:
        """
        Extrae múltiples bloques del output del Planificador.
        
        Orden de detección:
        1. Formato ## BLOQUES (tiene prioridad)
        2. Múltiples ## TAREA DE ENSAMBLAJE
        3. Una sola tarea (fallback)
        """
        
        blocks = []
        
        # ═══════════════════════════════════════════════════════════════
        # PRIMERO: Verificar si existe ## BLOQUES (tiene prioridad)
        # ═══════════════════════════════════════════════════════════════
        
        blocks_section = ""
        in_blocks = False
        for line in text.split("\n"):
            if line.strip() == "## BLOQUES":
                in_blocks = True
                continue
            if in_blocks:
                if line.strip().startswith("## ") and "BLOQUES" not in line:
                    break
                blocks_section += line + "\n"
        
        if blocks_section.strip():
            current_block = None
            current_code_lines = []
            
            for line in blocks_section.split("\n"):
                if line.strip().startswith("### BLOQUE"):
                    if current_block:
                        current_block["code"] = "\n".join(current_code_lines).strip()
                        blocks.append(current_block)
                    current_block = {"anchor": "", "action": "after", "indent": 0, "code": "", "imports": [], "tarea_id": "", "script": ""}
                    current_code_lines = []
                elif current_block is not None:
                    if line.strip().startswith("- ANCLA:"):
                        current_block["anchor"] = line.split(":", 1)[1].strip()
                    elif line.strip().startswith("- ACCIÓN:"):
                        current_block["action"] = line.split(":", 1)[1].strip().lower()
                    elif line.strip().startswith("- INDENTACIÓN:"):
                        try:
                            current_block["indent"] = int(line.split(":")[1].strip())
                        except:
                            pass
                    elif line.strip().startswith("# INSTRUCCIÓN"):
                        continue
                    elif not line.strip().startswith("-") and not line.strip().startswith("###"):
                        current_code_lines.append(line)
            
            if current_block:
                current_block["code"] = "\n".join(current_code_lines).strip()
                blocks.append(current_block)
            
            imports = cls._parse_imports(text)
            if imports and blocks:
                blocks[0]["imports"] = imports
            
            if blocks:
                # Extraer script y tarea_id del texto
                m = cls._RE_SCRIPT.search(text)
                if m:
                    for b in blocks:
                        b["script"] = m.group(1).strip()
                m = cls._RE_TAREA_ID.search(text)
                if m:
                    for b in blocks:
                        b["tarea_id"] = m.group(1).strip()
                return blocks
        
        # ═══════════════════════════════════════════════════════════════
        # SEGUNDO: Múltiples ## TAREA DE ENSAMBLAJE
        # ═══════════════════════════════════════════════════════════════
        
        task_pattern = re.compile(r'^##\s*TAREA\s*DE\s*ENSAMBLAJE', re.MULTILINE)
        task_matches = list(task_pattern.finditer(text))
        
        if task_matches:
            for i, match in enumerate(task_matches):
                start = match.start()
                if i + 1 < len(task_matches):
                    end = task_matches[i + 1].start()
                else:
                    end = len(text)
                
                task_text = text[start:end]
                parsed = cls.parse(task_text)
                
                if parsed.get("ancla_raw"):
                    action = "after"
                    if "ANTES_" in parsed["ancla_raw"]:
                        action = "before"
                    elif "REEMPLAZAR_" in parsed["ancla_raw"]:
                        action = "replace"
                    
                    blocks.append({
                        "anchor": parsed["ancla_raw"],
                        "action": action,
                        "indent": parsed.get("indentacion", 0),
                        "code": "",
                        "imports": parsed.get("imports_nuevos", []),
                        "tarea_id": parsed.get("tarea_id", ""),
                        "script": parsed.get("script", "")
                    })
            
            if blocks:
                return blocks
        
        # ═══════════════════════════════════════════════════════════════
        # FALLBACK: Una sola tarea
        # ═══════════════════════════════════════════════════════════════
        
        parsed = cls.parse(text)
        if parsed.get("ancla_raw"):
            action = "replace"
            if "ANTES_" in parsed["ancla_raw"]:
                action = "before"
            elif "REEMPLAZAR_" not in parsed["ancla_raw"]:
                action = "after"
            blocks.append({
                "anchor": parsed["ancla_raw"],
                "action": action,
                "indent": parsed.get("indentacion", 0),
                "code": "",
                "imports": parsed.get("imports_nuevos", []),
                "tarea_id": parsed.get("tarea_id", ""),
                "script": parsed.get("script", "")
            })
        
        return blocks
    
    @staticmethod
    def resolve_anchor(content: str, anchor_raw: str) -> tuple:
        """
        Resuelve un ancla AST y retorna (line_number, line_content, end_line).
        line_number es 1-indexed.
        end_line es la línea final de la estructura (para REEMPLAZAR) o 0.
        Retorna (0, "", 0) si no puede resolver el ancla.
        """
        try:
            tree = ast.parse(content)
            lines = content.split('\n')
            
            if anchor_raw == "INICIO_ARCHIVO":
                last_comment_line = 0
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        last_comment_line = i + 1
                    elif stripped == "":
                        if last_comment_line > 0:
                            continue
                        continue
                    else:
                        break
                if last_comment_line > 0:
                    return last_comment_line, lines[last_comment_line - 1], 0
                return 1, lines[0] if lines else "", 0
            
            if anchor_raw == "FIN_ARCHIVO":
                return len(lines), lines[-1] if lines else "", 0
            
            if anchor_raw == "ARCHIVO_NUEVO":
                return -1, "", 0
            
            if anchor_raw.startswith("LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1].strip())
                    if 1 <= num <= len(lines):
                        return num, lines[num - 1], 0
                except ValueError:
                    pass
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1].strip())
                    if 1 <= num < len(lines):
                        return num + 1, lines[num], 0
                except ValueError:
                    pass
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1].strip())
                    if 1 <= num <= len(lines):
                        return num, lines[num - 2] if num > 1 else "", 0
                except ValueError:
                    pass
                return 0, "", 0
            
            if anchor_raw.startswith("RANGO_LINEAS:"):
                try:
                    parts = anchor_raw.split(":")[1].strip().split("-")
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    if 1 <= start <= end <= len(lines):
                        return start, lines[start - 1], end
                except (ValueError, IndexError):
                    pass
                return 0, "", 0
            
            if anchor_raw.startswith("LINEA_CONTIENE:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if search_text in line:
                        return i + 1, line, 0
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_LINEA_CONTIENE:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if search_text in line:
                        if i + 1 < len(lines):
                            return i + 2, lines[i + 1], 0
                        return i + 1, "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_LINEA_CONTIENE:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if search_text in line:
                        if i > 0:
                            return i + 1, lines[i - 1], 0
                        return 1, "", 0
                return 0, "", 0
            
            if anchor_raw == "FIN_IMPORTS":
                last_import_line = 0
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        last_import_line = i + 1
                    elif stripped and not stripped.startswith("#") and last_import_line > 0:
                        break
                if last_import_line > 0:
                    return last_import_line, lines[last_import_line - 1], 0
                last_comment_line = 0
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        last_comment_line = i + 1
                    elif stripped:
                        break
                if last_comment_line > 0:
                    return last_comment_line, lines[last_comment_line - 1], 0
                return len(lines), lines[-1] if lines else "", 0
            
            if anchor_raw.startswith("DESPUES_IMPORT:"):
                import_name = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("import ") and import_name in stripped:
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else "", 0
                    if stripped.startswith("from ") and import_name in stripped:
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else "", 0
                return 0, "", 0
            
            if anchor_raw == "ANTES_IMPORTS":
                first_import_line = 0
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        first_import_line = i + 1
                        break
                if first_import_line > 0:
                    return first_import_line, lines[first_import_line - 2] if first_import_line > 1 else "", 0
                return 1, lines[0] if lines else "", 0
            
            if anchor_raw.startswith("DESPUES_BLOQUE_IF:"):
                condition = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.If):
                        if condition in ast.unparse(node.test):
                            return node.end_lineno, lines[node.end_lineno - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_BLOQUE_FOR:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.For):
                        if var_name in ast.unparse(node.target):
                            return node.end_lineno, lines[node.end_lineno - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_BLOQUE_TRY:"):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Try):
                        return node.end_lineno, lines[node.end_lineno - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_BLOQUE_WITH:"):
                resource = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.With):
                        for item in node.items:
                            if resource in ast.unparse(item.context_expr):
                                return node.end_lineno, lines[node.end_lineno - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("EN_CLASE:"):
                parts = anchor_raw.split("|", 1)
                if len(parts) == 2:
                    class_part = parts[0].split(":", 1)[1].strip()
                    inner_anchor = parts[1].strip()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and node.name == class_part:
                            class_lines = lines[node.lineno - 1:node.end_lineno]
                            class_content = "\n".join(class_lines)
                            inner_line, inner_content, _ = PlannerOutputParser.resolve_anchor(class_content, inner_anchor)
                            if inner_line > 0:
                                return node.lineno - 1 + inner_line, inner_content, 0
                return 0, "", 0
            
            if anchor_raw.startswith("EN_FUNCION:"):
                parts = anchor_raw.split("|", 1)
                if len(parts) == 2:
                    func_part = parts[0].split(":", 1)[1].strip()
                    inner_anchor = parts[1].strip()
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_part:
                            func_lines = lines[node.lineno - 1:node.end_lineno]
                            func_content = "\n".join(func_lines)
                            inner_line, inner_content, _ = PlannerOutputParser.resolve_anchor(func_content, inner_anchor)
                            if inner_line > 0:
                                return node.lineno - 1 + inner_line, inner_content, 0
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_DECORADOR:"):
                dec_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        for dec in node.decorator_list:
                            dec_str = ast.unparse(dec)
                            if dec_name in dec_str:
                                return node.lineno - len(node.decorator_list), lines[node.lineno - len(node.decorator_list) - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_DECORADOR:"):
                dec_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        for i, dec in enumerate(node.decorator_list):
                            dec_str = ast.unparse(dec)
                            if dec_name in dec_str:
                                dec_line = node.lineno - len(node.decorator_list) + i
                                return dec_line + 1, lines[dec_line], 0
                return 0, "", 0
            
            if anchor_raw.startswith("REEMPLAZAR_DECORADOR:"):
                dec_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        for dec in node.decorator_list:
                            dec_str = ast.unparse(dec)
                            if dec_name in dec_str:
                                return dec.lineno, lines[dec.lineno - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_COMENTARIO:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if line.strip().startswith("#") and search_text.lower() in line.lower():
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_COMENTARIO:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if line.strip().startswith("#") and search_text.lower() in line.lower():
                        return i + 1, lines[i - 1] if i > 0 else "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("TODO:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("#") and "todo" in stripped.lower() and search_text.lower() in line.lower():
                        return i + 1, line, 0
                return 0, "", 0
            
            if anchor_raw == "INSERTAR_ANTES_MAIN":
                for i, line in enumerate(lines):
                    if line.strip().startswith("if __name__"):
                        return i, lines[i - 1] if i > 0 else "", 0
                return len(lines), lines[-1] if lines else "", 0
            
            if anchor_raw == "REEMPLAZAR_BLOQUE_MAIN":
                main_start = 0
                main_end = len(lines)
                for i, line in enumerate(lines):
                    if line.strip().startswith("if __name__"):
                        main_start = i + 1
                        break
                if main_start > 0:
                    base_indent = len(lines[main_start - 1]) - len(lines[main_start - 1].lstrip())
                    for i in range(main_start, len(lines)):
                        line = lines[i]
                        if line.strip() and not line.startswith(" " * (base_indent + 1)) and not line.startswith("\t"):
                            main_end = i
                            break
                    return main_start, lines[main_start - 1], main_end
                return 0, "", 0
            
            if anchor_raw.startswith("REEMPLAZAR_VARIABLE:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                pattern = re.compile(
                    rf'(\b{re.escape(var_name)}\b\s*[=:]|self\.{re.escape(var_name)}\s*=)',
                    re.IGNORECASE
                )
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        return i + 1, line, i + 2
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_VARIABLE:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                pattern = re.compile(
                    rf'(\b{re.escape(var_name)}\b\s*[=:]|self\.{re.escape(var_name)}\s*=)',
                    re.IGNORECASE
                )
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_VARIABLE:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                pattern = re.compile(
                    rf'(\b{re.escape(var_name)}\b\s*[=:]|self\.{re.escape(var_name)}\s*=)',
                    re.IGNORECASE
                )
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        return i, lines[i - 1] if i > 0 else "", 0
                return 0, "", 0
            
            target_node = None
            action = "DESPUES"
            
            if anchor_raw.startswith("INICIO_CLASE:"):
                class_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        return node.lineno + 1, lines[node.lineno] if node.lineno < len(lines) else "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_CLASE:"):
                class_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        return node.lineno, lines[node.lineno - 2] if node.lineno > 1 else "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("FIN_CLASE:"):
                class_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        target_node = node
                        action = "DESPUES"
                        break
            
            if anchor_raw.startswith("REEMPLAZAR_CLASE:"):
                class_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        return node.lineno, lines[node.lineno - 1], node.end_lineno
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_METODO:"):
                ref = anchor_raw.split(":", 1)[1].strip()
                class_name, method_name = PlannerOutputParser._parse_method_reference(ref)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == method_name:
                        if class_name:
                            for class_node in ast.walk(tree):
                                if isinstance(class_node, ast.ClassDef) and class_node.name == class_name:
                                    for item in class_node.body:
                                        if isinstance(item, ast.FunctionDef) and item.name == method_name:
                                            return item.end_lineno, lines[item.end_lineno - 1], 0
                        else:
                            target_node = node
                            action = "DESPUES"
                            break
                if target_node:
                    return target_node.end_lineno, lines[target_node.end_lineno - 1], 0
                return 0, "", 0
            
            if anchor_raw.startswith("ANTES_METODO:"):
                ref = anchor_raw.split(":", 1)[1].strip()
                class_name, method_name = PlannerOutputParser._parse_method_reference(ref)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == method_name:
                        if class_name:
                            for class_node in ast.walk(tree):
                                if isinstance(class_node, ast.ClassDef) and class_node.name == class_name:
                                    for item in class_node.body:
                                        if isinstance(item, ast.FunctionDef) and item.name == method_name:
                                            return item.lineno - 1, lines[item.lineno - 2] if item.lineno > 1 else "", 0
                        else:
                            target_node = node
                            action = "ANTES"
                            break
                if target_node:
                    return target_node.lineno - 1, lines[target_node.lineno - 2] if target_node.lineno > 1 else "", 0
                return 0, "", 0
            
            if anchor_raw.startswith("REEMPLAZAR_METODO:"):
                ref = anchor_raw.split(":", 1)[1].strip()
                class_name, method_name = PlannerOutputParser._parse_method_reference(ref)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == method_name:
                        if class_name:
                            for class_node in ast.walk(tree):
                                if isinstance(class_node, ast.ClassDef) and class_node.name == class_name:
                                    for item in class_node.body:
                                        if isinstance(item, ast.FunctionDef) and item.name == method_name:
                                            return item.lineno, lines[item.lineno - 1], item.end_lineno
                        else:
                            return node.lineno, lines[node.lineno - 1], node.end_lineno
                return 0, "", 0
            
            if anchor_raw.startswith("DESPUES_FUNCION:"):
                func_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                        target_node = node
                        action = "DESPUES"
                        break
            
            elif anchor_raw.startswith("ANTES_FUNCION:"):
                func_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                        target_node = node
                        action = "ANTES"
                        break
            
            elif anchor_raw.startswith("REEMPLAZAR_FUNCION:"):
                func_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                        return node.lineno, lines[node.lineno - 1], node.end_lineno
                return 0, "", 0
            
# INTERVENCIÓN 5: MODIFICAR PROCESAMIENTO DE target_node
# REEMPLAZAR POR:

            # Procesar target_node encontrado
            if target_node:
                end_line = target_node.end_lineno
                start_line = target_node.lineno
                
                if action == "REEMPLAZAR":
                    return start_line, lines[start_line - 1], end_line
                elif action == "ANTES":
                    before_line = start_line - 1
                    if before_line <= 0:
                        return 1, "", 0
                    return before_line, lines[before_line - 1], 0
                else:
                    return end_line, lines[end_line - 1], 0
        
        except Exception as e:
            print(f"Error AST resolutor: {e}")
        
        return 0, "", 0
          
    # ═══════════════════════════════════════════════════════════════════════════
    # MÉTODOS DE UTILIDAD (NUEVO FASE 4)
    # ═══════════════════════════════════════════════════════════════════════════
    
    @staticmethod
    def validate_anchor(content: str, anchor_raw: str) -> tuple:
        """
        Valida si un ancla puede resolverse.
        
        Retorna: (valid: bool, error_message: str)
        
        Ejemplo:
            valid, msg = PlannerOutputParser.validate_anchor(code, "DESPUES_FUNCION:main")
            if not valid:
                print(f"Error: {msg}")
        """
        if not anchor_raw or not anchor_raw.strip():
            return False, "Ancla vacía"
        
        if not content or not content.strip():
            return False, "Contenido vacío"
        
        # Intentar resolver
        line, _, _ = PlannerOutputParser.resolve_anchor(content, anchor_raw)
        
        if line == 0:
            # Analizar tipo de error
            if anchor_raw.startswith("DESPUES_FUNCION:") or anchor_raw.startswith("ANTES_FUNCION:") or anchor_raw.startswith("REEMPLAZAR_FUNCION:"):
                func_name = anchor_raw.split(":")[1]
                return False, f"Función '{func_name}' no encontrada"
            
            if anchor_raw.startswith("DESPUES_METODO:") or anchor_raw.startswith("ANTES_METODO:") or anchor_raw.startswith("REEMPLAZAR_METODO:"):
                ref = anchor_raw.split(":")[1]
                return False, f"Método '{ref}' no encontrado"
            
            if anchor_raw.startswith("INICIO_CLASE:") or anchor_raw.startswith("FIN_CLASE:") or anchor_raw.startswith("REEMPLAZAR_CLASE:"):
                class_name = anchor_raw.split(":")[1]
                return False, f"Clase '{class_name}' no encontrada"
            
            if anchor_raw.startswith("LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1])
                    total_lines = content.count('\n') + 1
                    if num > total_lines:
                        return False, f"Línea {num} fuera de rango (total: {total_lines})"
                except:
                    return False, "Formato de línea inválido"
            
            if anchor_raw.startswith("LINEA_CONTIENE:"):
                search = anchor_raw.split(":")[1]
                return False, f"Texto '{search}' no encontrado en ninguna línea"
            
            return False, f"Ancla '{anchor_raw}' no pudo resolverse"
        
        return True, f"Ancla válida - línea {line}"
    
    @staticmethod
    def list_available_anchors() -> list:
        """
        Retorna lista de todas las anclas disponibles con descripción.
        
        Retorna: list[dict] con keys: ancla, descripcion, ejemplo
        """
        return [
            # Archivo
            {"ancla": "INICIO_ARCHIVO", "descripcion": "Insertar al inicio del archivo", "ejemplo": "INICIO_ARCHIVO"},
            {"ancla": "FIN_ARCHIVO", "descripcion": "Insertar al final del archivo", "ejemplo": "FIN_ARCHIVO"},
            {"ancla": "ARCHIVO_NUEVO", "descripcion": "Crear archivo nuevo", "ejemplo": "ARCHIVO_NUEVO"},
            
            # Función
            {"ancla": "DESPUES_FUNCION:nombre", "descripcion": "Insertar después de función", "ejemplo": "DESPUES_FUNCION:main"},
            {"ancla": "ANTES_FUNCION:nombre", "descripcion": "Insertar antes de función", "ejemplo": "ANTES_FUNCION:main"},
            {"ancla": "REEMPLAZAR_FUNCION:nombre", "descripcion": "Reemplazar función completa", "ejemplo": "REEMPLAZAR_FUNCION:process"},
            
            # Clase
            {"ancla": "INICIO_CLASE:Nombre", "descripcion": "Insertar dentro de la clase (después de definición)", "ejemplo": "INICIO_CLASE:App"},
            {"ancla": "ANTES_CLASE:Nombre", "descripcion": "Insertar antes de la clase", "ejemplo": "ANTES_CLASE:App"},
            {"ancla": "FIN_CLASE:Nombre", "descripcion": "Insertar al final de la clase", "ejemplo": "FIN_CLASE:App"},
            {"ancla": "REEMPLAZAR_CLASE:Nombre", "descripcion": "Reemplazar clase completa", "ejemplo": "REEMPLAZAR_CLASE:App"},
            
            # Método
            {"ancla": "DESPUES_METODO:Clase.metodo", "descripcion": "Insertar después de método específico", "ejemplo": "DESPUES_METODO:App.__init__"},
            {"ancla": "ANTES_METODO:Clase.metodo", "descripcion": "Insertar antes de método específico", "ejemplo": "ANTES_METODO:App.run"},
            {"ancla": "REEMPLAZAR_METODO:Clase.metodo", "descripcion": "Reemplazar método específico", "ejemplo": "REEMPLAZAR_METODO:App.process"},
            
            # Variable
            {"ancla": "REEMPLAZAR_VARIABLE:nombre", "descripcion": "Reemplazar línea de variable", "ejemplo": "REEMPLAZAR_VARIABLE:config"},
            {"ancla": "DESPUES_VARIABLE:nombre", "descripcion": "Insertar después de variable", "ejemplo": "DESPUES_VARIABLE:self.config"},
            {"ancla": "ANTES_VARIABLE:nombre", "descripcion": "Insertar antes de variable", "ejemplo": "ANTES_VARIABLE:VERSION"},
            
            # Posicional
            {"ancla": "LINEA:num", "descripcion": "Insertar en línea exacta", "ejemplo": "LINEA:42"},
            {"ancla": "DESPUES_LINEA:num", "descripcion": "Insertar después de línea", "ejemplo": "DESPUES_LINEA:10"},
            {"ancla": "ANTES_LINEA:num", "descripcion": "Insertar antes de línea", "ejemplo": "ANTES_LINEA:10"},
            {"ancla": "RANGO_LINEAS:ini-fin", "descripcion": "Reemplazar rango de líneas", "ejemplo": "RANGO_LINEAS:10-20"},
            
            # Patrón
            {"ancla": "LINEA_CONTIENE:texto", "descripcion": "Primera línea que contiene texto", "ejemplo": "LINEA_CONTIENE:TODO"},
            {"ancla": "DESPUES_LINEA_CONTIENE:texto", "descripcion": "Después de línea que contiene texto", "ejemplo": "DESPUES_LINEA_CONTIENE:def main"},
            {"ancla": "ANTES_LINEA_CONTIENE:texto", "descripcion": "Antes de línea que contiene texto", "ejemplo": "ANTES_LINEA_CONTIENE:class App"},
            
            # Import
            {"ancla": "FIN_IMPORTS", "descripcion": "Al final de sección de imports", "ejemplo": "FIN_IMPORTS"},
            {"ancla": "DESPUES_IMPORT:modulo", "descripcion": "Después de import específico", "ejemplo": "DESPUES_IMPORT:os"},
            {"ancla": "ANTES_IMPORTS", "descripcion": "Antes de todos los imports", "ejemplo": "ANTES_IMPORTS"},
            
            # Bloque
            {"ancla": "DESPUES_BLOQUE_IF:condicion", "descripcion": "Después de bloque if", "ejemplo": "DESPUES_BLOQUE_IF:is None"},
            {"ancla": "DESPUES_BLOQUE_FOR:variable", "descripcion": "Después de bloque for", "ejemplo": "DESPUES_BLOQUE_FOR:item"},
            {"ancla": "DESPUES_BLOQUE_TRY:", "descripcion": "Después de bloque try/except", "ejemplo": "DESPUES_BLOQUE_TRY:"},
            {"ancla": "DESPUES_BLOQUE_WITH:recurso", "descripcion": "Después de bloque with", "ejemplo": "DESPUES_BLOQUE_WITH:open"},
            
            # Contextual
            {"ancla": "EN_CLASE:Nombre|ANCLA:...", "descripcion": "Ancla dentro de una clase específica", "ejemplo": "EN_CLASE:App|LINEA_CONTIENE:TODO"},
            {"ancla": "EN_FUNCION:nombre|ANCLA:...", "descripcion": "Ancla dentro de una función específica", "ejemplo": "EN_FUNCION:main|LINEA:5"},
            
            # Decorador
            {"ancla": "ANTES_DECORADOR:nombre", "descripcion": "Antes de decorador específico", "ejemplo": "ANTES_DECORADOR:cache"},
            {"ancla": "DESPUES_DECORADOR:nombre", "descripcion": "Después de decorador", "ejemplo": "DESPUES_DECORADOR:route"},
            {"ancla": "REEMPLAZAR_DECORADOR:nombre", "descripcion": "Reemplazar decorador", "ejemplo": "REEMPLAZAR_DECORADOR:deprecated"},
            
            # Comentario
            {"ancla": "DESPUES_COMENTARIO:texto", "descripcion": "Después de comentario que contiene texto", "ejemplo": "DESPUES_COMENTARIO:Configuración"},
            {"ancla": "ANTES_COMENTARIO:texto", "descripcion": "Antes de comentario específico", "ejemplo": "ANTES_COMENTARIO:TODO"},
            {"ancla": "TODO:texto", "descripcion": "Línea con comentario TODO", "ejemplo": "TODO:implementar"},
            
            # Especial
            {"ancla": "INSERTAR_ANTES_MAIN", "descripcion": "Insertar antes del bloque if __name__", "ejemplo": "INSERTAR_ANTES_MAIN"},
            {"ancla": "REEMPLAZAR_BLOQUE_MAIN", "descripcion": "Reemplazar bloque main completo", "ejemplo": "REEMPLAZAR_BLOQUE_MAIN"},
        ]
    
    @staticmethod
    def get_context_info(content: str, line_number: int) -> dict:
        """
        Obtiene información del contexto en una línea específica.
        
        Retorna dict con:
        - clase: nombre de clase si está dentro de una, o None
        - funcion: nombre de función si está dentro de una, o None
        - indentacion: nivel de indentación
        - linea_contenido: contenido de la línea
        """
        lines = content.split('\n')
        
        if line_number < 1 or line_number > len(lines):
            return {"error": "Número de línea fuera de rango"}
        
        line_content = lines[line_number - 1]
        indentation = len(line_content) - len(line_content.lstrip())
        
        result = {
            "clase": None,
            "funcion": None,
            "indentacion": indentation,
            "linea_contenido": line_content,
            "linea_numero": line_number,
        }
        
        try:
            tree = ast.parse(content)
            
            # Buscar clase contenedora
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if node.lineno <= line_number <= node.end_lineno:
                        result["clase"] = node.name
                        break
            
            # Buscar función contenedora
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.lineno <= line_number <= node.end_lineno:
                        result["funcion"] = node.name
                        break
        except:
            pass
        
        return result

    @staticmethod
    def generate_anchor_docs() -> str:
        """
        Genera documentación markdown completa de todas las anclas.
        Útil para proporcionar al Planificador como referencia.
        
        Retorna: string en formato markdown
        """
        anchors = PlannerOutputParser.list_available_anchors()
        
        doc = "# SISTEMA DE ANCLAS - APA v3.1\n\n"
        doc += "## Resumen\n\n"
        doc += "Sistema de localización de código para inserción, reemplazo y modificación controlada.\n\n"
        doc += "## Formato de Uso\n\n"
        doc += "- SCRIPT: nombre_archivo.py\n"
        doc += "- TAREA_ID: V01\n"
        doc += "- ANCLA: TIPO_ANCLA:valor\n\n"
        doc += "---\n\n"
        
        categories = {
            "ANCLAS DE ARCHIVO": [a for a in anchors if "ARCHIVO" in a["ancla"]],
            "ANCLAS DE FUNCIÓN": [a for a in anchors if "FUNCION" in a["ancla"]],
            "ANCLAS DE CLASE": [a for a in anchors if "CLASE" in a["ancla"] and "EN_CLASE" not in a["ancla"]],
            "ANCLAS DE MÉTODO": [a for a in anchors if "METODO" in a["ancla"]],
            "ANCLAS DE VARIABLE": [a for a in anchors if "VARIABLE" in a["ancla"]],
            "ANCLAS POSICIONALES": [a for a in anchors if ("LINEA" in a["ancla"] or "RANGO" in a["ancla"]) and "CONTIENE" not in a["ancla"]],
            "ANCLAS POR PATRÓN": [a for a in anchors if "CONTIENE" in a["ancla"]],
            "ANCLAS DE IMPORT": [a for a in anchors if "IMPORT" in a["ancla"]],
            "ANCLAS DE BLOQUE": [a for a in anchors if "BLOQUE" in a["ancla"]],
            "ANCLAS CONTEXTUALES": [a for a in anchors if "EN_CLASE" in a["ancla"] or "EN_FUNCION" in a["ancla"]],
            "ANCLAS DE DECORADOR": [a for a in anchors if "DECORADOR" in a["ancla"]],
            "ANCLAS DE COMENTARIO": [a for a in anchors if "COMENTARIO" in a["ancla"] or "TODO" in a["ancla"]],
            "ANCLAS ESPECIALES": [a for a in anchors if "MAIN" in a["ancla"]],
        }
        
        for cat, items in categories.items():
            if items:
                doc += f"## {cat}\n\n"
                doc += "| Ancla | Descripción | Ejemplo |\n"
                doc += "|-------|-------------|----------|\n"
                for item in items:
                    doc += f"| `{item['ancla']}` | {item['descripcion']} | `{item['ejemplo']}` |\n"
                doc += "\n"
        
        doc += "---\n\n"
        doc += "## Notas de Uso\n\n"
        doc += "1. **Funciones async**: Todas las anclas de función soportan `async def`\n"
        doc += "2. **Notación Clase.metodo**: Usar punto para especificar método de clase\n"
        doc += "3. **Contextuales**: Permiten combinar contexto con cualquier ancla\n"
        doc += "4. **Validación**: Usar `validate_anchor()` antes de insertar\n\n"
        doc += "---\n\n"
        doc += "**Generado automáticamente por APA v3.1**\n"
        
        return doc

    @classmethod
    def _split_code_by_structure(cls, code: str) -> list:
        """
        Divide el código del Codificador en bloques por estructura.
        
        Cada bloque mantiene su indentación original.
        
        Retorna lista de dicts con: type, code, indent, name
        """
        if not code or not code.strip():
            return []
        
        blocks = []
        lines = code.split('\n')
        
        # Detectar inicios de bloques estructurales
        structure_markers = []
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            
            indent = len(line) - len(line.lstrip())
            
            # Imports (indent 0)
            if re.match(r'^(import|from)\s', stripped):
                if not structure_markers or structure_markers[-1][1] != 'imports':
                    structure_markers.append((i, 'imports', indent, None))
            
            # Clase
            elif re.match(r'^class\s+(\w+)', stripped):
                match = re.match(r'^class\s+(\w+)', stripped)
                structure_markers.append((i, 'class', indent, match.group(1) if match else None))
            
            # Función (indent 0) o método (indent >= 4)
            elif re.match(r'^(async\s+)?def\s+(\w+)', stripped):
                match = re.match(r'^(async\s+)?def\s+(\w+)', stripped)
                name = match.group(2) if match else None
                struct_type = 'method' if indent >= 4 else 'function'
                structure_markers.append((i, struct_type, indent, name))
            
            # Variable global
            elif indent == 0 and re.match(r'^[A-Za-z_]\w*\s*=', stripped):
                match = re.match(r'^([A-Za-z_]\w*)\s*=', stripped)
                structure_markers.append((i, 'variable', indent, match.group(1) if match else None))
        
        # Limpiar métodos dentro de clases (mantener clase como bloque único)
        class_indices = []
        for i, (start, stype, indent, name) in enumerate(structure_markers):
            if stype == 'class':
                class_indices.append(i)
        
        for class_idx in reversed(class_indices):
            _, _, class_indent, _ = structure_markers[class_idx]
            class_end = len(lines)
            for j in range(class_idx + 1, len(structure_markers)):
                _, _, next_indent, _ = structure_markers[j]
                if next_indent <= class_indent:
                    class_end = structure_markers[j][0]
                    break
            remove = []
            for j in range(class_idx + 1, len(structure_markers)):
                if structure_markers[j][0] < class_end:
                    remove.append(j)
                else:
                    break
            for j in reversed(remove):
                structure_markers.pop(j)
        
        # Extraer cada bloque CON su indentación original
        for idx, (start, struct_type, base_indent, name) in enumerate(structure_markers):
            if idx + 1 < len(structure_markers):
                end = structure_markers[idx + 1][0]
            else:
                end = len(lines)
            
            # Ajustar fin según tipo de estructura
            if struct_type == 'imports':
                # Imports consecutivos
                for j in range(start + 1, end):
                    line_stripped = lines[j].strip()
                    if line_stripped and not line_stripped.startswith('#') and not re.match(r'^(import|from)\s', line_stripped):
                        end = j
                        break
            
            elif struct_type in ['class', 'function', 'method']:
                # Cuerpo del bloque: líneas con mayor indentación o vacías
                for j in range(start + 1, end):
                    if not lines[j].strip():
                        continue
                    line_indent = len(lines[j]) - len(lines[j].lstrip())
                    if line_indent < base_indent and lines[j].strip():
                        end = j
                        break
            
            # Extraer código MANTENIENDO indentación original
            block_lines = lines[start:end]
            block_code = '\n'.join(block_lines)
            
            if block_code.strip():
                blocks.append({
                    'type': struct_type,
                    'code': block_code,
                    'indent': base_indent,
                    'name': name
                })
        
        # Si no hay estructura, retornar código completo
        if not blocks and code.strip():
            # Detectar indentación base
            first_line = lines[0] if lines else ""
            base_indent = len(first_line) - len(first_line.lstrip()) if first_line.strip() else 0
            blocks.append({
                'type': 'code',
                'code': code,
                'indent': base_indent,
                'name': None
            })
        
        return blocks

    @classmethod
    def _associate_code_to_planner_blocks(cls, planner_blocks: list, code_blocks: list, existing_structures: set = None) -> list:
        """
        Asocia bloques de código con las tareas del Planificador.
        
        Estrategia:
        1. Imports → anclas de import
        2. Métodos (indent >= 4) → anclas de clase/método
        3. Clases → anclas de clase
        4. Funciones → anclas de función
        5. Fallback por orden
        
        Retorna lista de planner_blocks con código asignado y warnings.
        """
        if not planner_blocks:
            return []
        
        if not code_blocks:
            return planner_blocks
        
        result = []
        used = set()
        
        for i, p_block in enumerate(planner_blocks):
            anchor = p_block.get('anchor', '')
            expected_indent = p_block.get('indent', 0)
            
            # Copiar bloque del planificador
            new_block = dict(p_block)
            new_block['code'] = ''
            new_block['warning'] = None
            
            assigned = False
            
            # ═══════════════════════════════════════════════════════════
            # ESTRATEGIA 1: Imports → anclas de import
            # ═══════════════════════════════════════════════════════════
            
            if 'IMPORT' in anchor.upper() or anchor == 'INICIO_ARCHIVO':
                for j, c_block in enumerate(code_blocks):
                    if j not in used and c_block['type'] == 'imports':
                        new_block['code'] = c_block['code']
                        used.add(j)
                        assigned = True
                        break
                
                # FIX: Ancla de imports sin code_block tipo imports = tarea solo-imports
                # (BLOQUE vacío según metodología). No aplicar fallbacks.
                if not assigned:
                    assigned = True  # Marcar como manejado para saltar fallbacks
            
            # ═══════════════════════════════════════════════════════════
            # ESTRATEGIA 2: Métodos → anclas de clase/método
            # ═══════════════════════════════════════════════════════════
            
            elif 'CLASE' in anchor.upper() or 'METODO' in anchor.upper():
                if expected_indent >= 4:
                    # Buscar método con indentación exacta
                    for j, c_block in enumerate(code_blocks):
                        if j not in used and c_block['type'] == 'method':
                            if c_block['indent'] == expected_indent:
                                new_block['code'] = c_block['code']
                                used.add(j)
                                assigned = True
                                break
                    
                    # Si no hay match exacto, tomar cualquier método
                    if not assigned:
                        for j, c_block in enumerate(code_blocks):
                            if j not in used and c_block['type'] == 'method':
                                new_block['code'] = c_block['code']
                                used.add(j)
                                new_block['warning'] = 'Indent esperada {}, encontrada {}'.format(expected_indent, c_block['indent'])
                                assigned = True
                                break
                            
                            break
            
                    # ESTRATEGIA 7: Sin method blocks, extraer métodos nuevos de class block
                    if not assigned and existing_structures is not None:
                        class_name = None
                        if 'CLASE:' in anchor.upper():
                            idx = anchor.upper().find('CLASE:')
                            class_name = anchor[idx + 6:].strip()
                        
                        if class_name:
                            for j, c_block in enumerate(code_blocks):
                                if j not in used and c_block['type'] == 'class' and c_block.get('name') == class_name:
                                    class_lines = c_block['code'].split('\n')
                                    new_methods = []
                                    current_method_name = None
                                    current_method_lines = []
                                    
                                    for cline in class_lines:
                                        cstripped = cline.strip()
                                        cindent = len(cline) - len(cline.lstrip())
                                        
                                        if cindent >= 4 and (cstripped.startswith('def ') or cstripped.startswith('async def ')):
                                            if current_method_name is not None:
                                                method_code = '\n'.join(current_method_lines)
                                                if ('function', current_method_name) not in existing_structures:
                                                    new_methods.append(method_code)
                                            match = re.match(r'(?:async\s+)?def\s+(\w+)', cstripped)
                                            current_method_name = match.group(1) if match else None
                                            current_method_lines = [cline]
                                        elif current_method_name is not None:
                                            current_method_lines.append(cline)
                                    
                                    if current_method_name is not None:
                                        method_code = '\n'.join(current_method_lines)
                                        if ('function', current_method_name) not in existing_structures:
                                            new_methods.append(method_code)
                                    
                                    if new_methods:
                                        new_block['code'] = '\n'.join(new_methods)
                                        used.add(j)
                                        assigned = True
                                    break
                        
            # ═══════════════════════════════════════════════════════════
            # ESTRATEGIA 3: Clases
            # ═══════════════════════════════════════════════════════════
            
            elif 'CLASE' in anchor.upper():
                for j, c_block in enumerate(code_blocks):
                    if j not in used and c_block['type'] == 'class':
                        new_block['code'] = c_block['code']
                        used.add(j)
                        assigned = True
                        break
            
            # ═══════════════════════════════════════════════════════════
            # ESTRATEGIA 4: Funciones y clases (anclas ANTES/DESPUES_FUNCION
            # pueden insertar clases junto a funciones)
            # Asignar en ORDEN DE APARICIÓN del Codificador para preservar
            # la secuencia clase→función que usa la función.
            # ═══════════════════════════════════════════════════════════
            
            elif 'FUNCION' in anchor.upper():
                # Asignar primer code_block disponible (class o function)
                # en orden de aparición, sin priorizar tipos
                for j, c_block in enumerate(code_blocks):
                    if j not in used:
                        if c_block['type'] in ('function', 'class') and c_block['indent'] == expected_indent:
                            new_block['code'] = c_block['code']
                            used.add(j)
                            assigned = True
                            break
            
            # ═══════════════════════════════════════════════════════════
            # ESTRATEGIA 5: Fallback por indentación
            # ═══════════════════════════════════════════════════════════
            
            if not assigned:
                for j, c_block in enumerate(code_blocks):
                    if j not in used and c_block['indent'] == expected_indent:
                        new_block['code'] = c_block['code']
                        used.add(j)
                        assigned = True
                        break
            
            # ═══════════════════════════════════════════════════════════
            # ESTRATEGIA 6: Fallback por orden
            # ═══════════════════════════════════════════════════════════
            
            if not assigned:
                for j, c_block in enumerate(code_blocks):
                    if j not in used:
                        new_block['code'] = c_block['code']
                        used.add(j)
                        if c_block['indent'] != expected_indent:
                            new_block['warning'] = 'Indent esperada {}, encontrada {}'.format(expected_indent, c_block['indent'])
                        assigned = True
                        break
            
            result.append(new_block)
        
        # ═══════════════════════════════════════════════════════════════
        # Verificar código no asociado
        # ═══════════════════════════════════════════════════════════════
        
        for j, c_block in enumerate(code_blocks):
            if j not in used:
                if result:
                    prev_warning = result[-1].get('warning') or ''
                    result[-1]['warning'] = (prev_warning + ' | Código no asociado: ' + c_block['type']).strip(' |')
        
        return result

# ─────────────────────────────────────────────────────────────────────────────
# App principal
# ─────────────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        root.title("APA — Ensamblador Atómico v3.0")
        self._setup_dark_theme()
        w, h = 1200, 900
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        root.minsize(1000, 700)

        # ── Estado general ──────────────────────────────────────────────────
        self.current_file_name = None
        self.project_root = tk.StringVar()
        self.plan_path = None
        self.add_text = None
        self.add_btn = None
        self.add_mode = False
        self.done_task_id = None
        
        # ── Caché de configuración ─────────────────────────────────────────
        self.config_file = Path.home() / ".apa_config.json"
        if not self._load_config():
            self.auto_detect_project_root()
        self.project_root.trace_add("write", lambda *_: self._save_config())
        root_path = Path(self.project_root.get()) if self.project_root.get() else Path.cwd()
        plan_files = list(root_path.glob("PLAN_*.md"))
        if not plan_files:
            for subdir in root_path.iterdir():
                if subdir.is_dir():
                    plan_files.extend(subdir.glob("PLAN_*.md"))
        if plan_files:
            plan_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            self.plan_path = plan_files[0]
        
        # ── Estado del ensamblador ──────────────────────────────────────────
        self.asm_file_path    = tk.StringVar()   
        self.asm_task_id      = tk.StringVar()   
        self.asm_exec_mode    = tk.StringVar(value="local")
        self.asm_original_content = ""           
        self.asm_baseline_content = ""
        self.asm_undo_stack   = []               
        self.asm_redo_stack   = []               
        self.asm_backup_path  = None   
        self.assembler = Assembler()
        self.asm_last_result = None            
        self._parsed          = {}
        self.asm_replaced_lines = set()          

        # ── Notebooks ──────────────────────────────────────────────────────
        style = ttk.Style()
        style.configure("TNotebook.Tab", font=('Segoe UI', 11, 'bold'), padding=[20, 8])
        nb = ttk.Notebook(root, style="TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.notebook = nb

        self.tab_process = ttk.Frame(nb)
        nb.add(self.tab_process, text="⚡ Procesar Prompt")
        self._setup_process_tab()

        self.tab_plan = ttk.Frame(nb)
        nb.add(self.tab_plan, text="📋 Plan de Mejoras")
        self._setup_plan_tab()

        self.tab_assembler = ttk.Frame(nb)
        nb.add(self.tab_assembler, text="🧩 Ensamblador")
        self._setup_assembler_tab()

        self._setup_keyboard_shortcuts()
        
        # Evento de cierre para limpiar archivos temporales
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        self.project_root.trace_add("write", lambda *_: self.on_project_root_change())
        self.refresh_plan_view()

    # ─────────────────────────────────────────────────────────────────────────
    # Shortcuts & Setup Básico
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_keyboard_shortcuts(self):
        binds = {
            'a': self._on_plan_key_a,  'A': self._on_plan_key_a,
            'm': self._on_plan_key_m,  'M': self._on_plan_key_m,
            'r': self._on_plan_key_r,  'R': self._on_plan_key_r,
            'p': self._on_process_key_p, 'P': self._on_process_key_p,
            'v': self._on_process_key_v, 'V': self._on_process_key_v,
            'l': self._on_process_key_l, 'L': self._on_process_key_l,
            'o': self._on_process_key_o, 'O': self._on_process_key_o,
        }
        for key, cb in binds.items():
            self.root.bind(f'<KeyPress-{key}>', cb)

    def _tab(self): return self.notebook.index(self.notebook.select())
    
    def _focused_is_input(self):
        f = self.root.focus_get()
        return isinstance(f, (tk.Entry, tk.Text, scrolledtext.ScrolledText, ttk.Entry))

    def _on_plan_key_a(self, e):
        if self._tab() != 1: return
        if self.root.focus_get() == self.add_text: return
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry)): return "break"
        self.toggle_add_mode(); return "break"

    def _on_plan_key_m(self, e):
        if self._tab() == 1: self.complete_task(); return "break"

    def _on_plan_key_r(self, e):
        if self._tab() == 1 and not self._focused_is_input():
            self.refresh_plan_view(); return "break"

    def _on_process_key_p(self, e):
        if self._tab() == 0 and not self._focused_is_input():
            self.process(); return "break"

    def _on_process_key_v(self, e):
        if self._tab() == 0 and not self._focused_is_input():
            self.copy(); return "break"

    def _on_process_key_l(self, e):
        if self._tab() == 0 and not self._focused_is_input():
            self.clear(); return "break"

    def _on_process_key_o(self, e):
        if self._tab() == 0 and not self._focused_is_input():
            self.browse_project_root(); return "break"

    def handle_ctrl_enter(self, e):
        t = self.notebook.tab(self.notebook.select(), "text")
        if "Procesar" in t: self.process()
        elif "Plan" in t: self.toggle_add_mode()

    def on_project_root_change(self):
        if "Plan" in self.notebook.tab(self.notebook.select(), "text"):
            self.auto_detect_project_root()
            self.refresh_plan_view()
 
    def _on_close(self):
        """Limpia archivos temporales al cerrar la aplicación."""
        try:
            root_dir = self.get_source_root()
            # Buscar y eliminar archivos *_original*
            for backup_file in root_dir.rglob("*_original*"):
                if backup_file.is_file():
                    try:
                        backup_file.unlink()
                    except:
                        pass
        except:
            pass
        
        self.root.destroy()

    def _setup_dark_theme(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",          background="#1e1e1e")
        s.configure("TLabel",          background="#1e1e1e", foreground="#d4d4d4", font=('Segoe UI', 10))
        s.configure("TButton",         background="#3b82f6", foreground="#ffffff", font=('Segoe UI', 10, 'bold'), borderwidth=0, focuscolor='none', padding=8)
        s.map("TButton",               background=[('active','#2563eb'),('pressed','#1d4ed8')])
        s.configure("Big.TButton",     background="#3b82f6", foreground="#ffffff", font=('Segoe UI', 12, 'bold'), borderwidth=0, focuscolor='none', padding=12)
        s.map("Big.TButton",           background=[('active','#2563eb'),('pressed','#1d4ed8')])
        s.configure("Green.TButton",   background="#16a34a", foreground="#ffffff", font=('Segoe UI', 10, 'bold'), borderwidth=0, focuscolor='none', padding=8)
        s.map("Green.TButton",         background=[('active','#15803d'),('pressed','#166534')])
        s.configure("BigGreen.TButton",background="#16a34a", foreground="#ffffff", font=('Segoe UI', 12, 'bold'), borderwidth=0, focuscolor='none', padding=12)
        s.map("BigGreen.TButton",      background=[('active','#15803d'),('pressed','#166534')])
        s.configure("Red.TButton",     background="#dc2626", foreground="#ffffff", font=('Segoe UI', 10, 'bold'), borderwidth=0, focuscolor='none', padding=8)
        s.map("Red.TButton",           background=[('active','#b91c1c'),('pressed','#991b1b')])
        s.configure("TEntry",          fieldbackground="#2d2d2d", foreground="#d4d4d4", insertcolor="#ffffff", padding=5)
        s.configure("TLabelframe",     background="#1e1e1e", foreground="#3b82f6")
        s.configure("TLabelframe.Label", background="#1e1e1e", foreground="#3b82f6", font=('Segoe UI', 10, 'bold'))
        s.configure("TNotebook",       background="#1e1e1e", borderwidth=0)
        s.configure("TNotebook.Tab",   background="#2d2d2d", foreground="#d4d4d4")
        s.map("TNotebook.Tab", background=[("selected","#3b82f6")], foreground=[("selected","#ffffff")])
        s.configure("TCombobox",       fieldbackground="#2d2d2d", background="#2d2d2d", foreground="#d4d4d4")
        s.configure("TRadiobutton",    background="#1e1e1e", foreground="#d4d4d4")
        s.configure("TCheckbutton",    background="#1e1e1e", foreground="#d4d4d4")
        self.root.configure(bg="#1e1e1e")

    # ─────────────────────────────────────────────────────────────────────────
    # Tabs de Procesar y Plan (Se mantienen iguales visualmente)
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_process_tab(self):
        tab = self.tab_process
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=2)
        tab.rowconfigure(3, weight=2)

        cfg = ttk.LabelFrame(tab, text="📁 Configuración del proyecto", padding=10)
        cfg.grid(row=0, column=0, padx=10, pady=(10,5), sticky="ew")
        cfg.columnconfigure(1, weight=1)
        ttk.Label(cfg, text="Ruta raíz:").grid(row=0, column=0, sticky="w", padx=5)
        e = ttk.Entry(cfg, textvariable=self.project_root)
        e.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        e.bind("<Return>", lambda _: self.update_project_root())
        ToolTip(e, "Directorio raíz del proyecto APA")
        btn_examinar = ttk.Button(cfg, text="📂 Examinar", command=self.browse_project_root)
        btn_examinar.grid(row=0, column=2, padx=5)
        ToolTip(btn_examinar, "Abre diálogo para seleccionar directorio raíz")

        inp = ttk.LabelFrame(tab, text="📝 Prompt Base", padding=10)
        inp.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        inp.columnconfigure(0, weight=1)
        inp.rowconfigure(0, weight=1)
        self.input_text = scrolledtext.ScrolledText(inp, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.input_text.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.input_text, "Pega aquí el prompt base a procesar")

        btn_process = ttk.Button(tab, text="Procesar Prompt", command=self.process)
        btn_process.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        ToolTip(btn_process, "Procesa el prompt y reemplaza tags [INCRUSTAR: ruta]")
        
        out = ttk.LabelFrame(tab, text="✨ Prompt Procesado", padding=10)
        out.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)
        self.output_text = scrolledtext.ScrolledText(out, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.output_text, "Resultado del prompt procesado")

        act = ttk.Frame(tab, padding=5)
        act.grid(row=4, column=0, padx=10, pady=(5,10), sticky="ew")
        act.columnconfigure((0,1,2), weight=1)
        btn_copy = ttk.Button(act, text="Copiar",  command=self.copy)
        btn_copy.grid(row=0, column=0, padx=5)
        ToolTip(btn_copy, "Copia el resultado al portapapeles")
        
        btn_pdf = ttk.Button(act, text="PDF",     command=self.pdf)
        btn_pdf.grid(row=0, column=1, padx=5)
        ToolTip(btn_pdf, "Exporta el resultado a PDF")
        
        btn_clear = ttk.Button(act, text="Limpiar", command=self.clear)
        btn_clear.grid(row=0, column=2, padx=5)
        ToolTip(btn_clear, "Limpia ambos campos de texto")

    def _setup_plan_tab(self):
        tab = self.tab_plan
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=2)
        tab.rowconfigure(2, weight=1)

        pv = ttk.LabelFrame(tab, text="📄 Contenido del Plan", padding=10)
        pv.grid(row=0, column=0, padx=10, pady=(10,5), sticky="nsew")
        pv.columnconfigure(0, weight=1)
        pv.rowconfigure(0, weight=1)
        self.plan_text = scrolledtext.ScrolledText(pv, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", font=("Consolas", 9), relief="flat", padx=10, pady=10, state="disabled")
        self.plan_text.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.plan_text, "Contenido del archivo PLAN_*.md encontrado en el proyecto")

        ctrl = ttk.Frame(tab, padding=10)
        ctrl.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        ctrl.columnconfigure((0,1), weight=1)

        add = ttk.LabelFrame(ctrl, text="➕ Añadir Tarea", padding=10)
        add.grid(row=0, column=0, padx=5, sticky="ew")
        add.columnconfigure(0, weight=1)
        ttk.Label(add, text="Contenido a añadir:").grid(row=0, column=0, sticky="w")
        tf = ttk.Frame(add)
        tf.grid(row=1, column=0, sticky="ew", pady=4)
        tf.columnconfigure(0, weight=1)
        self.add_text = tk.Text(tf, height=5, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 9), relief="flat", padx=8, pady=8, state='disabled')
        self.add_text.grid(row=0, column=0, sticky="ew")
        ToolTip(self.add_text, "Escribe aquí la nueva tarea a añadir al plan")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.add_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.add_text.configure(yscrollcommand=sb.set)
        self.add_btn = ttk.Button(add, text="Añadir Tarea", command=self.toggle_add_mode)
        self.add_btn.grid(row=2, column=0, pady=10, sticky="ew")
        ToolTip(self.add_btn, "Activa el modo añadir y agrega la tarea al plan")

        done = ttk.LabelFrame(ctrl, text="✅ Completar Tarea", padding=10)
        done.grid(row=0, column=1, padx=5, sticky="ew")
        done.columnconfigure(0, weight=1)
        ttk.Label(done, text="ID de tarea (ej. V0):").grid(row=0, column=0, sticky="e")
        self.done_task_id = ttk.Entry(done)
        self.done_task_id.grid(row=1, column=0, sticky="ew", padx=5, pady=4)
        ToolTip(self.done_task_id, "ID de tarea a marcar como completada (ej: T1, Q1.2)")
        btn_complete = ttk.Button(done, text="Marcar Completada", command=self.complete_task)
        btn_complete.grid(row=2, column=0, pady=10, sticky="ew")
        ToolTip(btn_complete, "Marca la tarea con el ID indicado como completada")

        btn_reload = ttk.Button(tab, text="Recargar Plan", command=self.refresh_plan_view)
        btn_reload.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        ToolTip(btn_reload, "Recarga el archivo de plan desde disco")
        
    # ─────────────────────────────────────────────────────────────────────────
    # Tab 3 – Ensamblador (MODIFICADO V3.0)
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_assembler_tab(self):
        tab = self.tab_assembler
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        # Fila 0: Ruta
        cfg = ttk.LabelFrame(tab, text="📁 Ruta del Proyecto", padding=10)
        cfg.grid(row=0, column=0, padx=10, pady=(10,4), sticky="ew")
        cfg.columnconfigure(1, weight=1)
        ttk.Label(cfg, text="Raíz:").grid(row=0, column=0, sticky="w", padx=5)
        self.asm_root_entry = ttk.Entry(cfg, textvariable=self.project_root)
        self.asm_root_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ToolTip(self.asm_root_entry, "Directorio raíz del proyecto APA")
        btn_browse = ttk.Button(cfg, text="📂 Examinar", command=self.browse_project_root)
        btn_browse.grid(row=0, column=2, padx=5)
        ToolTip(btn_browse, "Selecciona el directorio raíz del proyecto")

        # Fila 1: Banner de estado
        banner = ttk.LabelFrame(tab, text="📊 Estado", padding=8)
        banner.grid(row=1, column=0, padx=10, pady=4, sticky="ew")
        banner.columnconfigure(0, weight=1)
        self.asm_status_lbl = ttk.Label(
            banner,
            text="⬇  PEGA Planificador y Codificador  →  🚀 ENSAMBLAR",
            foreground="#60a5fa", font=("Segoe UI", 10, "bold"))
        self.asm_status_lbl.grid(row=0, column=0, sticky="w")
        ToolTip(self.asm_status_lbl, "Estado actual del ensamblador")
        self.asm_parsed_lbl = ttk.Label(banner, text="", foreground="#888", font=("Segoe UI", 9))
        self.asm_parsed_lbl.grid(row=1, column=0, sticky="w", pady=(2,0))
        ToolTip(self.asm_parsed_lbl, "Información del parsing: script, ancla y contexto")

        # Fila 2: Área Central - Tres paneles horizontales
        work = ttk.Frame(tab)
        work.grid(row=2, column=0, padx=10, pady=4, sticky="nsew")
        work.columnconfigure(0, weight=2)    # Planificador
        work.columnconfigure(1, weight=2)    # Codificador
        work.columnconfigure(2, weight=1)    # Ensamblador (más ancho)
        work.rowconfigure(0, weight=1)

        # Panel 1: Planificador (izquierda)
        planner_frame = ttk.LabelFrame(work, text="📥 1. Output Planificador", padding=5)
        planner_frame.grid(row=0, column=0, padx=(0,2), sticky="nsew")
        planner_frame.columnconfigure(0, weight=1)
        planner_frame.rowconfigure(0, weight=1)
        self.asm_input = scrolledtext.ScrolledText(
            planner_frame, wrap=tk.NONE, bg="#1a2332", fg="#93c5fd",
            insertbackground="white", font=("Consolas", 10))
        self.asm_input.grid(row=0, column=0, sticky="nsew")
        self.asm_input.bind("<<Paste>>", lambda e: self.root.after(80, self._asm_on_paste))
        self.asm_input.bind("<KeyRelease>", lambda e: self.root.after(300, self._asm_on_paste))
        ToolTip(self.asm_input, "Pega aquí el output del Planificador (SCRIPT, ANCLA, IMPORTS_NUEVOS)")
        # Scrollbar horizontal
        h_scroll_p = ttk.Scrollbar(planner_frame, orient="horizontal", command=self.asm_input.xview)
        h_scroll_p.grid(row=1, column=0, sticky="ew")
        self.asm_input.configure(xscrollcommand=h_scroll_p.set)

        # Panel 2: Codificador (centro)
        coder_frame = ttk.LabelFrame(work, text="🧠 2. Código Codificador", padding=5)
        coder_frame.grid(row=0, column=1, padx=2, sticky="nsew")
        coder_frame.columnconfigure(0, weight=1)
        coder_frame.rowconfigure(0, weight=1)
        self.asm_coder_input = scrolledtext.ScrolledText(
            coder_frame, wrap=tk.NONE, bg="#1a2332", fg="#a7f3d0",
            insertbackground="white", font=("Consolas", 10))
        self.asm_coder_input.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.asm_coder_input, "Pega aquí el código Python del Codificador")
        # Scrollbar horizontal
        h_scroll_c = ttk.Scrollbar(coder_frame, orient="horizontal", command=self.asm_coder_input.xview)
        h_scroll_c.grid(row=1, column=0, sticky="ew")
        self.asm_coder_input.configure(xscrollcommand=h_scroll_c.set)

        # Panel 3: Script Ensamblado (derecha, más ancho)
        right = ttk.LabelFrame(work, text="📄 3. Script Ensamblado (Memoria)", padding=5)
        right.grid(row=0, column=2, padx=(2,0), sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        view_hdr = ttk.Frame(right)
        view_hdr.grid(row=0, column=0, sticky="ew")
        view_hdr.columnconfigure(0, weight=1)
        self.asm_edit_toggle = tk.BooleanVar(value=False)
        chk_edit = ttk.Checkbutton(view_hdr, text="✏️ Edición manual",
                        variable=self.asm_edit_toggle,
                        command=self._asm_toggle_edit)
        chk_edit.grid(row=0, column=0, sticky="w")
        ToolTip(chk_edit, "Activa/desactiva edición manual del código ensamblado")
        self.asm_lines_lbl = ttk.Label(view_hdr, text="", foreground="#888", font=("Segoe UI", 9))
        self.asm_lines_lbl.grid(row=0, column=1, sticky="e", padx=8)
        
        # Botón copiar código
        btn_copy_code = ttk.Button(view_hdr, text="📋 Código", command=self._asm_copy_code)
        btn_copy_code.grid(row=0, column=2)
        ToolTip(btn_copy_code, "Copia el código ensamblado al portapapeles")

        self.asm_view = scrolledtext.ScrolledText(
            right, wrap=tk.NONE, bg="#1a1a1a", fg="#a0a0a0",
            insertbackground="white", font=("Consolas", 9), state="disabled")
        self.asm_view.grid(row=1, column=0, sticky="nsew")
        self.asm_view.tag_configure("anchor_hl", background="#854d0e", foreground="#fef3c7")
        self.asm_view.tag_configure("changed", background="#4b1818", foreground="#ffcdd2")
        # Scrollbar horizontal
        h_scroll_e = ttk.Scrollbar(right, orient="horizontal", command=self.asm_view.xview)
        h_scroll_e.grid(row=2, column=0, sticky="ew")
        self.asm_view.configure(xscrollcommand=h_scroll_e.set)
        
        # Fila 3: Botones
        btn_main = ttk.Frame(tab, padding=(10,6))
        btn_main.grid(row=3, column=0, sticky="ew")
        btn_main.columnconfigure(0, weight=3)
        btn_main.columnconfigure((1,2,3,4,5), weight=1)

        self.asm_run_btn = ttk.Button(
            btn_main,
            text="🚀  ENSAMBLAR + EJECUTAR",
            style="Big.TButton",
            command=self._asm_run_full_auto)
        self.asm_run_btn.grid(row=0, column=0, padx=(0,6), sticky="ew")
        ToolTip(self.asm_run_btn, "Ensambla el código y ejecuta validación automática")
        
        btn_undo = ttk.Button(btn_main, text="↩ Deshacer",
                   command=self._asm_undo)
        btn_undo.grid(row=0, column=1, padx=3, sticky="ew")
        ToolTip(btn_undo, "Deshace el último cambio (mantiene historial)")
        
        btn_redo = ttk.Button(btn_main, text="↪ Rehacer",
                   command=self._asm_redo)
        btn_redo.grid(row=0, column=2, padx=3, sticky="ew")
        ToolTip(btn_redo, "Rehace el último cambio deshecho")
        
        btn_clear = ttk.Button(btn_main, text="🆕 Nueva tarea",
                   command=self._asm_clear_inputs)
        btn_clear.grid(row=0, column=3, padx=3, sticky="ew")
        ToolTip(btn_clear, "Limpia campos para iniciar nueva tarea")
        
        btn_reset = ttk.Button(btn_main, text="💣 Resetear", command=self._asm_reset_hard)
        btn_reset.grid(row=0, column=4, padx=3, sticky="ew")
        ToolTip(btn_reset, "Vacía completamente el workspace (sin guardar)")
        
        btn_anchors = ttk.Button(btn_main, text="❓ Anclas", command=self._show_anchors_help)
        btn_anchors.grid(row=0, column=5, padx=3, sticky="ew")
        ToolTip(btn_anchors, "Muestra la ayuda de todas las anclas disponibles")
        
        # Fila 4: Panel de output (compacto)
        out_frame = ttk.LabelFrame(tab, text="📊  Output de Validación", padding=5)
        out_frame.grid(row=4, column=0, padx=10, pady=4, sticky="ew")
        out_frame.columnconfigure(0, weight=1)
        self.asm_output = scrolledtext.ScrolledText(
            out_frame, height=2, wrap=tk.NONE, bg="#0d1117", fg="#c9d1d9",
            insertbackground="white", font=("Consolas", 9),
            relief="flat", state="disabled")
        self.asm_output.grid(row=0, column=0, sticky="ew")
        ToolTip(self.asm_output, "Output de validación: resultado de sintaxis, imports y ejecución")
        self.asm_syntax_lbl = ttk.Label(out_frame, text="", font=("Segoe UI", 9))
        self.asm_syntax_lbl.grid(row=1, column=0, sticky="w", pady=(2,0))
        ToolTip(self.asm_syntax_lbl, "Estado de validación de sintaxis Python")
        
        # Fila 5: Decisión final
        dec = ttk.Frame(tab, padding=(10,4))
        dec.grid(row=5, column=0, sticky="ew", pady=(0,8))
        dec.columnconfigure((0,1,2), weight=1)
        
        self.asm_approve_btn = ttk.Button(
            dec, text="✅  APROBAR — guardar", style="BigGreen.TButton", command=self._asm_approve)
        self.asm_approve_btn.grid(row=0, column=0, padx=6, sticky="ew")
        ToolTip(self.asm_approve_btn, "Guarda cambios en disco y crea backup del original")
        
        btn_reject = ttk.Button(dec, text="❌  RECHAZAR — restaurar", style="Red.TButton", command=self._asm_reject)
        btn_reject.grid(row=0, column=1, padx=6, sticky="ew")
        ToolTip(btn_reject, "Descarta cambios y restaura desde backup (elimina backup)")
        
        btn_copy_result = ttk.Button(dec, text="📋  Copiar resultado", command=self._asm_copy_summary)
        btn_copy_result.grid(row=0, column=2, padx=6, sticky="ew")
        ToolTip(btn_copy_result, "Copia resumen de validación al portapapeles para el Planificador")
            
    # ─────────────────────────────────────────────────────────────────────────
    # Lógica Ensamblador
    # ─────────────────────────────────────────────────────────────────────────

    def _asm_on_paste(self):
        raw = self.asm_input.get('1.0', 'end-1c')
        if not raw.strip(): return
        parsed = PlannerOutputParser.parse(raw)
        self._parsed = parsed
        
        # Mostrar errores de parseo
        if parsed["errores"]:
            self.asm_parsed_lbl.config(text=f"⚠️  Faltan: {' | '.join(parsed['errores'])}", foreground="#fbbf24")
            return
        
        # Validar ancla si hay script cargado
        ancla = parsed.get("ancla_raw", "")
        script = parsed.get("script", "")
        
        if ancla and self.asm_original_content:
            valid, msg = PlannerOutputParser.validate_anchor(self.asm_original_content, ancla)
            if valid:
                # Obtener información de contexto
                line, _, _ = PlannerOutputParser.resolve_anchor(self.asm_original_content, ancla)
                ctx = PlannerOutputParser.get_context_info(self.asm_original_content, line)
                ctx_info = ""
                if ctx.get("clase"):
                    ctx_info += f" | clase: {ctx['clase']}"
                if ctx.get("funcion"):
                    ctx_info += f" | función: {ctx['funcion']}"
                self.asm_parsed_lbl.config(
                    text=f"✅  {script}  |  {ancla[:30]}{'...' if len(ancla)>30 else ''}{ctx_info}", 
                    foreground="#4ade80"
                )
            else:
                self.asm_parsed_lbl.config(text=f"❌  {msg}", foreground="#f87171")
        else:
            self.asm_parsed_lbl.config(text=f"✅  script: {parsed['script']}  |  tarea: {parsed['tarea_id']}", foreground="#4ade80")

    def _asm_highlight_changes(self):
        """Resalta cambios, ignorando variaciones de saltos de línea al final."""
        self.asm_view.tag_remove("changed", "1.0", tk.END)
        
        current_lines = self.asm_view.get('1.0', 'end-1c').splitlines()
        baseline_lines = self.asm_baseline_content.splitlines()
        
        # PRIMERO: Marcar líneas que fueron explícitamente reemplazadas
        for line_num in self.asm_replaced_lines:
            if 0 < line_num <= len(current_lines):
                self._highlight_line(line_num)
        
        # Si ya marcamos reemplazo, no necesitamos diff adicional para esas líneas
        if self.asm_replaced_lines:
            return
        
        # SEGUNDO: Usar difflib para otros cambios (inserciones)
        matcher = difflib.SequenceMatcher(None, baseline_lines, current_lines)
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'insert':
                for i in range(j1, j2):
                    self._highlight_line(i+1)
            elif tag == 'replace':
                for k in range(j1, j2):
                    idx_base = i1 + (k - j1)
                    if idx_base < len(baseline_lines):
                        b_line = baseline_lines[idx_base].strip()
                        c_line = current_lines[k].strip()
                        if b_line != c_line:
                            self._highlight_line(k+1)
                    else:
                        self._highlight_line(k+1)
    
    def _highlight_line(self, line_num):
        """Helper para marcar una línea específica."""
        start_idx = f"{line_num}.0"
        end_idx = f"{line_num}.end"
        self.asm_view.tag_add("changed", start_idx, end_idx) 
    
    def _asm_set_view(self, content: str):
        was_disabled = self.asm_view.cget("state") == "disabled"
        self.asm_view.config(state="normal")
        self.asm_view.delete('1.0', tk.END)
        self.asm_view.insert('1.0', content)
        self.asm_lines_lbl.config(text=f"{content.count(chr(10))+1} líneas")
        
        # Resaltar cambios
        self._asm_highlight_changes()
        
        if was_disabled:
            self.asm_view.config(state="disabled")

    def _asm_clear_inputs(self):
        self.asm_input.delete("1.0", tk.END)
        self.asm_coder_input.delete("1.0", tk.END)
        self._asm_output_clear()
        self.asm_task_id.set("")
        self._parsed = {}
        self.asm_syntax_lbl.config(text="")
        self.asm_parsed_lbl.config(text="", foreground="#888")
        self.asm_last_result = None
        self.asm_status_lbl.config(text="Listo para siguiente tarea", foreground="#60a5fa")

    # ─────────────────────────────────────────────────────────────────────────
    # Merge inteligente para la opción MODIFICAR de estructuras duplicadas
    # ─────────────────────────────────────────────────────────────────────────
    
    def _merge_duplicate_structures(self, original_content, new_code, block_duplicates):
        """Merge inteligente de estructuras duplicadas.
        
        Para CLASES: mantiene la clase existente, actualiza métodos que cambiaron,
        añade métodos nuevos, conserva métodos que no están en el nuevo código.
        
        Para FUNCIONES: equivalente a reemplazar (no hay sub-estructura).
        
        Args:
            original_content: contenido actual del archivo
            new_code: código nuevo que el codificador entregó
            block_duplicates: set de (type, name) de estructuras duplicadas
            
        Returns:
            str: código mergeado, o None si el merge falla
        """
        try:
            for struct_type, struct_name in block_duplicates:
                if struct_type == "class":
                    return self._merge_class(original_content, new_code, struct_name)
                # Para funciones: el merge es equivalente a reemplazar
                # (no hay sub-estructura dentro de una función que merezca preservar)
            return None
        except Exception as e:
            self._log("_merge_duplicate_structures error: " + str(e))
            return None
    
    def _merge_class(self, original_content, new_code, class_name):
        """Merge de una clase: conserva métodos existentes no modificados,
        reemplaza métodos que existen en ambas versiones, añade métodos nuevos.
        
        Estrategia:
        1. Parsear ambas versiones con AST
        2. Extraer métodos de cada versión (nombre → código fuente)
        3. Para métodos que están en ambas: usar la versión nueva (modificada)
        4. Para métodos solo en la existente: conservarlos
        5. Para métodos solo en la nueva: añadirlos
        6. Reconstruir la clase con el orden: métodos existentes (actualizados o conservados)
           seguidos de métodos nuevos
        """
        try:
            orig_tree = ast.parse(original_content)
            new_tree = ast.parse(new_code)
        except SyntaxError:
            return None
        
        # Buscar la clase en el archivo original
        orig_class = None
        for node in ast.walk(orig_tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                orig_class = node
                break
        
        if orig_class is None:
            return None
        
        # Buscar la clase en el código nuevo
        new_class = None
        for node in ast.walk(new_tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                new_class = node
                break
        
        if new_class is None:
            return None
        
        # Extraer líneas fuente completas
        orig_lines = original_content.splitlines()
        new_lines = new_code.splitlines()
        
        # Obtener métodos de la clase original (nombre → (start, end, source_lines))
        orig_methods = {}
        orig_non_methods = []  # atributos de clase, no métodos
        
        for item in orig_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_source = "\n".join(orig_lines[item.lineno - 1 : item.end_lineno])
                orig_methods[item.name] = {
                    "source": method_source,
                    "lineno": item.lineno,
                    "end_lineno": item.end_lineno
                }
            else:
                # Atributos de clase, docstrings, etc.
                item_source = "\n".join(orig_lines[item.lineno - 1 : item.end_lineno])
                orig_non_methods.append({
                    "name": getattr(item, "name", None) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) else "__non_method__",
                    "source": item_source,
                    "lineno": item.lineno,
                    "end_lineno": item.end_lineno
                })
        
        # Obtener métodos de la clase nueva
        new_methods = {}
        new_non_methods = []
        
        for item in new_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_source = "\n".join(new_lines[item.lineno - 1 : item.end_lineno])
                new_methods[item.name] = {
                    "source": method_source,
                    "lineno": item.lineno,
                    "end_lineno": item.end_lineno
                }
            else:
                item_source = "\n".join(new_lines[item.lineno - 1 : item.end_lineno])
                new_non_methods.append({
                    "name": getattr(item, "name", None) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) else "__non_method__",
                    "source": item_source,
                    "lineno": item.lineno,
                    "end_lineno": item.end_lineno
                })
        
        # Construir la clase mergeada
        # Preservar decoradores: priorizar nueva versión si tiene
        orig_decorators = []
        if orig_class.decorator_list:
            for dec in orig_class.decorator_list:
                orig_decorators.append(orig_lines[dec.lineno - 1])
        
        new_decorators = []
        if new_class.decorator_list:
            for dec in new_class.decorator_list:
                new_decorators.append(new_lines[dec.lineno - 1])
        
        # Usar decoradores de la nueva versión si los hay, sino originales
        if new_decorators:
            decorators = new_decorators
        else:
            decorators = orig_decorators
        
        # Preservar la firma de la clase (herencia, etc.)
        class_header = orig_lines[orig_class.lineno - 1]
        
        # Si la nueva clase tiene diferente firma (herencia), usar la nueva
        new_class_header = new_lines[new_class.lineno - 1]
        if class_header.strip() != new_class_header.strip():
            # La firma cambió (ej: nueva herencia), usar la nueva
            class_header = new_class_header
        
        # Merge de métodos:
        # - Mantener orden original de los métodos existentes
        # - Métodos que existen en ambas: usar versión nueva
        # - Métodos solo en la nueva: añadir al final
        merged_body = []
        
        # Primero: no-métodos (atributos de clase, docstrings)
        # Priorizar los de la nueva versión (pueden haber cambiado)
        if new_non_methods:
            for nm in new_non_methods:
                merged_body.append(nm["source"])
        elif orig_non_methods:
            for nm in orig_non_methods:
                merged_body.append(nm["source"])
        
        # Segundo: métodos en orden de aparición original
        seen_methods = set()
        
        # Iterar en orden de aparición en la clase original
        for item in orig_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_name = item.name
                seen_methods.add(method_name)
                if method_name in new_methods:
                    # Método que existe en ambas versiones: usar la nueva (modificada)
                    merged_body.append(new_methods[method_name]["source"])
                else:
                    # Método que solo existe en la original: conservar
                    merged_body.append(orig_methods[method_name]["source"])
        
        # Añadir métodos nuevos que no existían en la original
        for item in new_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name not in seen_methods:
                    merged_body.append(new_methods[item.name]["source"])
                    seen_methods.add(item.name)
        
        # Reconstruir la clase completa
        result_lines = []
        for dec in decorators:
            result_lines.append(dec)
        result_lines.append(class_header)
        for body_item in merged_body:
            # Añadir línea en blanco entre métodos
            result_lines.append("")
            # Indentar cada línea del cuerpo al nivel de la clase (4 espacios)
            for line in body_item.split("\n"):
                # Si la línea ya está indentada, mantenerla
                # Si empieza con def/class, indentar a nivel 1 (4 espacios)
                stripped = line.lstrip()
                if stripped:
                    current_indent = len(line) - len(stripped)
                    # Las líneas fuente ya tienen la indentación del método
                    # Solo necesitamos asegurar que el primer nivel sea 4 espacios
                    result_lines.append("    " + line if current_indent == 0 else line)
                else:
                    result_lines.append("")
        
        result = "\n".join(result_lines)
        
        # Log del merge
        orig_method_names = set(orig_methods.keys())
        new_method_names = set(new_methods.keys())
        added = new_method_names - orig_method_names
        modified = orig_method_names & new_method_names
        preserved = orig_method_names - new_method_names
        
        self._log("Merge clase " + class_name + ": " +
                   str(len(modified)) + " modificados, " +
                   str(len(added)) + " nuevos, " +
                   str(len(preserved)) + " conservados")
        
        return result
    
    def _log(self, msg):
        """Escribe un mensaje en el log del ensamblador."""
        if hasattr(self, 'asm_log') and self.asm_log:
            self.asm_log.insert(tk.END, msg + "\n")
            self.asm_log.see(tk.END)
        else:
            # Fallback: imprimir a consola
            print("[ENSAMBLADOR] " + msg)

    def _asm_run_full_auto(self):
            raw_planner = self.asm_input.get("1.0", "end-1c").strip()
            raw_coder = self.asm_coder_input.get("1.0", "end-1c").strip()
            
            if not raw_planner:
                messagebox.showwarning("Advertencia", "El bloque del planificador esta vacio.")
                return

            parsed = PlannerOutputParser.parse(raw_planner)
            if parsed.get("errores"):
                messagebox.showerror("Error de parseo", "\n".join(parsed["errores"]))
                return

            blocks_data = PlannerOutputParser._parse_blocks(raw_planner)
            
            if not blocks_data:
                if not raw_coder.strip() and not parsed.get("imports_nuevos"):
                    messagebox.showerror("Error", "No hay bloques ni codigo para insertar.")
                    return
                action = "replace"
                if "ANTES_" in parsed.get("ancla_raw", ""):
                    action = "before"
                elif "REEMPLAZAR_" not in parsed.get("ancla_raw", ""):
                    action = "after"
                blocks_data = [{
                    "anchor": parsed.get("ancla_raw", ""),
                    "action": action,
                    "indent": parsed.get("indentacion", 0),
                    "code": raw_coder,
                    "imports": parsed.get("imports_nuevos", [])
                }]

            root_dir = self.get_source_root()
            script_name = parsed.get("script", "")
            
            try:
                found_path = self.find_file(root_dir, script_name)
                script_path = Path(found_path)
            except Exception:
                if blocks_data[0].get("anchor") == "ARCHIVO_NUEVO":
                    script_path = root_dir / script_name
                    script_path.parent.mkdir(parents=True, exist_ok=True)
                    script_path.write_text("", encoding="utf-8")
                else:
                    messagebox.showerror("Error", "Archivo " + script_name + " no encontrado.")
                    return

            self.asm_file_path.set(str(script_path))

            # Usar contenido en memoria si existe, sino leer del archivo
            if self.asm_original_content:
                original_content = self.asm_original_content
            else:
                original_content = ""
                if script_path.exists():
                    original_content = script_path.read_text(encoding="utf-8")

            # Guardar estado ANTES de cualquier modificación para undo correcto
            # (original_content se modifica más adelante al eliminar imports)
            pre_modification_content = original_content

            self.asm_baseline_content = original_content

            is_multitarea = len(blocks_data) > 1

            # GESTIONAR VALIDACIÓN EXISTENTE DE ESTA TAREA
            show_validation_notice = False
            validation_mode = "new"
            task_id_val = parsed.get("tarea_id", "")
            
            if task_id_val and "if __name__" in original_content and not is_multitarea:
                lines_orig = original_content.split("\n")
                pattern = re.compile(r'#\s*===\s*VALIDACIÓN\s+TAREA:\s*' + re.escape(task_id_val) + r'\s*===')
                
                marker_line = -1
                for i, line in enumerate(lines_orig):
                    if pattern.search(line):
                        marker_line = i
                        break
                
                if marker_line >= 0:
                    # Ya existe validación para esta tarea - preguntar al usuario
                    respuesta = messagebox.askyesno(
                        "Validación existente",
                        "Ya existe validación para " + task_id_val + "\n\n" +
                        "• SÍ = Sobrescribir (reemplazar existente)\n" +
                        "• NO = Implementar (agregar después de existente)"
                    )
                    
                    if respuesta:  # Sí = Sobrescribir
                        validation_mode = "overwrite"
                        # Eliminar validación existente
                        end_val_line = len(lines_orig)
                        next_marker = re.compile(r'#\s*===\s*VALIDACIÓN\s+TAREA:')
                        
                        for i in range(marker_line + 1, len(lines_orig)):
                            if next_marker.search(lines_orig[i]):
                                end_val_line = i
                                break
                        
                        lines_new = lines_orig[:marker_line] + lines_orig[end_val_line:]
                        original_content = "\n".join(lines_new)
                        self.asm_baseline_content = original_content
                    else:  # No = Implementar
                        validation_mode = "implement"
                        # NO eliminar, se agregará después de la existente
                else:
                    # No existe validación para esta tarea
                    validation_mode = "new"
                    show_validation_notice = True

            # Extraer imports existentes preservando orden
            existing_imports_list = []
            has_existing_imports = False
            for line in original_content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    existing_imports_list.append(stripped)
                    has_existing_imports = True

            has_main_block = "if __name__" in original_content
                            
            coder_code = raw_coder.strip() if raw_coder.strip() else ""
            
            coder_code = re.sub(r"^```python\s*\n?", "", coder_code, flags=re.IGNORECASE)
            coder_code = re.sub(r"\n?```\s*$", "", coder_code)
            
            script_name_only = Path(script_name).name
            code_lines = coder_code.split("\n")
            cleaned_lines = []
            for line in code_lines:
                stripped = line.strip()
                if stripped == "#" + script_name or stripped == "# " + script_name:
                    continue
                if stripped == "#" + script_name_only or stripped == "# " + script_name_only:
                    continue
                if re.match(r"^#\s*\w+[/\\]?\w*\.py$", stripped):
                    continue
                cleaned_lines.append(line)
            coder_code = "\n".join(cleaned_lines).strip()
            
            imports_list = []
            main_code_lines = []
            test_code_lines = []
            in_main_block = False
            
            for line in coder_code.split("\n"):
                stripped = line.strip()
                
                if stripped.startswith("import ") or stripped.startswith("from "):
                    imports_list.append(stripped)
                    continue
                
                if "if __name__" in line and "__main__" in line:
                    in_main_block = True
                    continue
                
                if in_main_block:
                    test_code_lines.append(line)
                else:
                    main_code_lines.append(line)
            
            existing_structures = set()
            try:
                tree = ast.parse(original_content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        existing_structures.add(("class", node.name))
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        existing_structures.add(("function", node.name))
            except:
                pass
            
            if is_multitarea:
                code_structures = PlannerOutputParser._split_code_by_structure("\n".join(main_code_lines))
                blocks_data = PlannerOutputParser._associate_code_to_planner_blocks(blocks_data, code_structures, existing_structures)
                
                code_structures = PlannerOutputParser._split_code_by_structure("\n".join(main_code_lines))
                blocks_data = PlannerOutputParser._associate_code_to_planner_blocks(blocks_data, code_structures)
                all_task_ids = []
                for bd in blocks_data:
                    tid = bd.get("tarea_id", "")
                    if tid and tid not in all_task_ids:
                        all_task_ids.append(tid)
                task_id_val = "_".join(all_task_ids) if all_task_ids else ""
            else:
                if blocks_data and not blocks_data[0].get("code", "").strip() and main_code_lines:
                    blocks_data[0]["code"] = "\n".join(main_code_lines).strip()
            
            planner_imports = [] if is_multitarea else (blocks_data[0].get("imports", []) if blocks_data else [])
            for imp in planner_imports:
                if imp.startswith("import ") or imp.startswith("from "):
                    canonical = imp
                else:
                    canonical = "import " + imp
                imports_list.append(canonical)
            
            # COMBINAR TODOS LOS IMPORTS (existentes + nuevos)
            all_imports = existing_imports_list + imports_list
            
            # DEDUPLICACIÓN INTELIGENTE
            from_modules = set()
            for imp in all_imports:
                if imp.startswith("from "):
                    match = re.match(r'from\s+(\S+)', imp)
                    if match:
                        from_modules.add(match.group(1).split('.')[0])
            
            deduped_imports = []
            seen = set()
            for imp in all_imports:
                if imp.startswith("import "):
                    match = re.match(r'import\s+(\S+)', imp)
                    if match:
                        module = match.group(1).split('.')[0]
                        if module not in from_modules and imp not in seen:
                            deduped_imports.append(imp)
                            seen.add(imp)
                else:
                    if imp not in seen:
                        deduped_imports.append(imp)
                        seen.add(imp)
            
            # ORDENAR: imports simples primero, from imports después
            simple_imports = [imp for imp in deduped_imports if imp.startswith("import ")]
            from_imports = [imp for imp in deduped_imports if imp.startswith("from ")]
            
            simple_imports.sort(key=lambda x: len(x))
            from_imports.sort(key=lambda x: len(x))
            
            imports_list = simple_imports + from_imports
            
            # Normalizar usos: si existe 'from X import Y' y el código usa 'X.Y', reemplazar por 'Y'
            from_import_map = {}
            for imp in from_imports:
                match = re.match(r'from\s+(\S+)\s+import\s+(.+)', imp)
                if match:
                    module = match.group(1).split('.')[0]
                    symbols = [s.strip() for s in match.group(2).split(',')]
                    from_import_map[module] = symbols
            
            for module, symbols in from_import_map.items():
                for sym in symbols:
                    pattern = re.compile(r'\b' + re.escape(module) + r'\.' + re.escape(sym) + r'\b')
                    for i, line in enumerate(main_code_lines):
                        if pattern.search(line):
                            main_code_lines[i] = pattern.sub(sym, line)
                    for i, line in enumerate(test_code_lines):
                        if pattern.search(line):
                            test_code_lines[i] = pattern.sub(sym, line)
                    # También reemplazar en blocks_data (multitarea usa blocks_data, no main_code_lines)
                    for bd in blocks_data:
                        bd_code = bd.get("code", "")
                        if bd_code and pattern.search(bd_code):
                            bd["code"] = pattern.sub(sym, bd_code)
            
            # Normalización inversa: 'import X' + usos 'X.Y()' → 'from X import Y'
            # Reglas:
            #   1. Si X.attr es reasignado (X.attr = ...) → mantener 'import X'
            #   2. Si solo hay llamadas X.Y() (1-2 atributos) → convertir a 'from X import Y'
            #   3. Si 3+ atributos distintos del mismo módulo → mantener 'import X' por legibilidad
            _IMPORT_SPEC_THRESHOLD = 3  # Umbral configurable: 3+ attrs → mantener genérico
            
            new_simple_imports = []
            converted_from_imports = []
            modules_to_remove = set()
            
            for imp in simple_imports:
                match = re.match(r'import\s+(\S+)', imp)
                if not match:
                    new_simple_imports.append(imp)
                    continue
                module = match.group(1)
                
                # Recolectar todos los usos X.attr en el código (main + test)
                all_code = "\n".join(main_code_lines + test_code_lines)
                
                # Verificar si hay reasignación: X.attr = valor
                assign_pattern = re.compile(r'\b' + re.escape(module) + r'\.\w+\s*=')
                if assign_pattern.search(all_code):
                    new_simple_imports.append(imp)
                    continue
                
                # Buscar todos los atributos usados: X.Y, X.Z, etc.
                usage_pattern = re.compile(r'\b' + re.escape(module) + r'\.(\w+)')
                attrs_used = set(usage_pattern.findall(all_code))
                
                if not attrs_used:
                    # No se usa en el código, mantenerlo (puede ser usado implícitamente)
                    new_simple_imports.append(imp)
                    continue
                
                if len(attrs_used) >= _IMPORT_SPEC_THRESHOLD:
                    # 3+ atributos → mantener import genérico por legibilidad
                    new_simple_imports.append(imp)
                    continue
                
                # 1-2 atributos → convertir a from X import Y
                attrs_sorted = sorted(attrs_used)
                from_imp = "from " + module + " import " + ", ".join(attrs_sorted)
                converted_from_imports.append(from_imp)
                modules_to_remove.add(module)
                
                # Reemplazar X.Y → Y en main_code_lines, test_code_lines Y blocks_data
                for attr in attrs_sorted:
                    replace_pattern = re.compile(r'\b' + re.escape(module) + r'\.' + re.escape(attr) + r'\b')
                    for i, line in enumerate(main_code_lines):
                        if replace_pattern.search(line):
                            main_code_lines[i] = replace_pattern.sub(attr, line)
                    for i, line in enumerate(test_code_lines):
                        if replace_pattern.search(line):
                            test_code_lines[i] = replace_pattern.sub(attr, line)
                    # También reemplazar en blocks_data (multitarea usa blocks_data, no main_code_lines)
                    for bd in blocks_data:
                        bd_code = bd.get("code", "")
                        if bd_code and replace_pattern.search(bd_code):
                            bd["code"] = replace_pattern.sub(attr, bd_code)
            
            # Reconstruir imports_list si hubo conversiones
            if modules_to_remove:
                simple_imports = new_simple_imports
                from_imports = from_imports + converted_from_imports
                imports_list = simple_imports + from_imports
            
            # ELIMINAR IMPORTS EXISTENTES DEL CONTENIDO ORIGINAL
            if imports_list and has_existing_imports:
                lines_content = original_content.split("\n")
                new_lines = []
                skip_blank_after_import = False
                
                for i, line in enumerate(lines_content):
                    stripped = line.strip()
                    
                    # Saltar líneas de import
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        skip_blank_after_import = True
                        continue
                    
                    # Saltar línea en blanco inmediatamente después de imports
                    if skip_blank_after_import and stripped == "":
                        skip_blank_after_import = False
                        continue
                    
                    skip_blank_after_import = False
                    new_lines.append(line)
                
                original_content = "\n".join(new_lines)
                
                # Actualizar baseline si estaba vacío
                if not self.asm_baseline_content:
                    self.asm_baseline_content = original_content
                
                # Ya no hay imports existentes
                has_existing_imports = False
                    
            # Validar que no existan las estructuras que vamos a insertar            
            final_blocks = []
            for bd in blocks_data:
                code_content = bd.get("code", "")
                if not code_content.strip():
                    continue
                
                block_structures = set()
                for line in code_content.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("class "):
                        match = re.match(r"class\s+(\w+)", stripped)
                        if match:
                            block_structures.add(("class", match.group(1)))
                    elif stripped.startswith("def ") or stripped.startswith("async def "):
                        match = re.match(r"(?:async\s+)?def\s+(\w+)", stripped)
                        if match:
                            block_structures.add(("function", match.group(1)))
                
                block_duplicates = block_structures & existing_structures
                if block_duplicates:
                    dup_list = [f"{t[0]} {t[1]}" for t in block_duplicates]
                    dup_str = "\n".join(dup_list)
                    bd_task = bd.get("tarea_id", "")
                    
                    # Detectar si hay clase entre los duplicados para ofrecer "Modificar"
                    has_class_dup = any(st == "class" for st, _ in block_duplicates)
                    
                    # Usar diálogo personalizado con 4 opciones
                    dlg = DuplicateStructureDialog(
                        self.root,
                        "Estructura duplicada - " + bd_task,
                        "Tarea: " + bd_task + "\n\n" +
                        "Ya existe en el archivo:\n" + dup_str + "\n\n" +
                        "Cambio solicitado:\n" + bd.get("anchor", "") + "\n\n" +
                        "¿Qué desea hacer?",
                        has_class=has_class_dup
                    )
                    answer = dlg.result
                    
                    if answer == 'cancel':
                        return
                    elif answer == 'discard':
                        continue
                    elif answer == 'modify':
                        # MODIFICAR: merge inteligente a nivel de métodos
                        merged_code = self._merge_duplicate_structures(
                            original_content, bd.get("code", ""), block_duplicates
                        )
                        if merged_code is not None:
                            bd["code"] = merged_code
                            # Para modificar clase: usar REEMPLAZAR_CLASE (reemplaza la clase
                            # entera por la versión mergeada que conserva métodos no cambiados)
                            for struct_type, struct_name in block_duplicates:
                                if struct_type == "class":
                                    bd["anchor"] = "REEMPLAZAR_CLASE:" + struct_name
                                    bd["action"] = "replace"
                                    break
                                elif struct_type == "function":
                                    bd["anchor"] = "REEMPLAZAR_FUNCION:" + struct_name
                                    bd["action"] = "replace"
                                    break
                        else:
                            # Si el merge falla, caer a reemplazo completo
                            self._log("Merge falló, usando reemplazo completo")
                            for struct_type, struct_name in block_duplicates:
                                if struct_type == "class":
                                    bd["anchor"] = "REEMPLAZAR_CLASE:" + struct_name
                                    bd["action"] = "replace"
                                else:
                                    bd["anchor"] = "REEMPLAZAR_FUNCION:" + struct_name
                                    bd["action"] = "replace"
                    else:  # answer == 'replace'
                        is_method = "CLASE" in bd.get("anchor", "").upper() or "METODO" in bd.get("anchor", "").upper()
                        for struct_type, struct_name in block_duplicates:
                            if struct_type == "class":
                                bd["anchor"] = "REEMPLAZAR_CLASE:" + struct_name
                                bd["action"] = "replace"
                            elif is_method:
                                class_match = re.search(r'CLASE:(\w+)', bd.get("anchor", ""))
                                if class_match:
                                    bd["anchor"] = "REEMPLAZAR_METODO:" + class_match.group(1) + "." + struct_name
                                else:
                                    bd["anchor"] = "REEMPLAZAR_FUNCION:" + struct_name
                                bd["action"] = "replace"
                            else:
                                bd["anchor"] = "REEMPLAZAR_FUNCION:" + struct_name
                                bd["action"] = "replace"
                
                final_blocks.append(bd)
            
            blocks_data = final_blocks
            
            blocks = []
            anchor_map = {}
                    
            # BLOQUE A: IMPORTS
            if imports_list:
                import_code = "\n".join(imports_list) + "\n"
                # Siempre usar INICIO_ARCHIVO ya que eliminamos los imports anteriores
                import_anchor = "INICIO_ARCHIVO"
                blocks.append({
                    "action": "after",
                    "anchor": import_anchor,
                    "code": import_code
                })
            
            # BLOQUE B: CODIGO PRINCIPAL - Iterar sobre todos los bloques
            if blocks_data:
                for bd in blocks_data:
                    code_anchor = bd.get("anchor", "FIN_ARCHIVO")
                    if not code_anchor:
                        code_anchor = "FIN_ARCHIVO"
                    code_action = bd.get("action", "after")
                    code_content = bd.get("code", "")
                    
                    if code_content:
                        blocks.append({
                            "action": code_action,
                            "anchor": code_anchor,
                            "code": code_content.rstrip() + "\n" if not code_content.endswith("\n") else code_content
                        })
            elif main_code_lines:
                main_code = "\n".join(main_code_lines).rstrip() + "\n"
                blocks.append({
                    "action": "after",
                    "anchor": "FIN_ARCHIVO",
                    "code": main_code
                })

            pending_validation_code = None

            pending_validation_code = None

            # BLOQUE C: TESTS - Validación por TAREA_ID
            if test_code_lines:
                has_marker = False
                for line in test_code_lines:
                    if "# === VALIDACIÓN TAREA:" in line:
                        has_marker = True
                        break
                
                non_empty_test = [l for l in test_code_lines if l.strip()]
                if non_empty_test:
                    min_indent_test = min(len(l) - len(l.lstrip()) for l in non_empty_test)
                else:
                    min_indent_test = 0
                
                test_code = ""
                if not has_marker:
                    marker = "# === VALIDACIÓN TAREA: " + task_id_val + " ==="
                    test_code += "    " + marker + "\n"
                
                for line in test_code_lines:
                    if line.strip():
                        relative_indent = len(line) - len(line.lstrip()) - min_indent_test
                        test_code += "    " + ("    " * (relative_indent // 4)) + line.lstrip() + "\n"
                
                if test_code.strip():
                    pending_validation_code = test_code
            
            # Asignar orden de creación
            for i, block in enumerate(blocks):
                block["_order"] = i
            
            for block in blocks:
                anchor_raw = block["anchor"]
                if anchor_raw and anchor_raw not in anchor_map:
                    line_num, _, end_line = PlannerOutputParser.resolve_anchor(original_content, anchor_raw)
                    
                    if anchor_raw == "FIN_ARCHIVO" and "if __name__" in original_content:
                        for i, line in enumerate(original_content.split("\n")):
                            if "if __name__" in line and "__main__" in line:
                                line_num = i
                                break
                    
                    anchor_map[anchor_raw] = {"line": line_num, "end_line": end_line if end_line > 0 else line_num + 1}
            
            # Ordenar: línea descendente, si iguales: orden inverso de creación
            blocks.sort(key=lambda b: (-anchor_map.get(b['anchor'], {}).get('line', 0), -b["_order"]))
            
            try:
                self._parsed = parsed
                
                # Guardar estado completo en pila antes de ensamblar
                # Usar pre_modification_content (antes de eliminar imports) para undo correcto
                current_state = {
                    "content": pre_modification_content,
                    "planner": self.asm_input.get("1.0", "end-1c"),
                    "coder": self.asm_coder_input.get("1.0", "end-1c")
                }
                self.asm_undo_stack.append(current_state)
                # Limpiar pila de redo al hacer nuevo cambio
                self.asm_redo_stack.clear()
                            
                assembled_content = self.assembler.assemble(
                    original_content, 
                    blocks, 
                    anchor_map
                )
                
                if pending_validation_code:
                    asm_lines = assembled_content.split("\n")
                    val_lines = pending_validation_code.split("\n")
                    
                    if validation_mode == "implement":
                        pattern_impl = re.compile(r'#\s*===\s*VALIDACIÓN\s+TAREA:\s*' + re.escape(task_id_val) + r'\s*===')
                        marker_idx = -1
                        for i, line in enumerate(asm_lines):
                            if pattern_impl.search(line):
                                marker_idx = i
                                break
                        
                        if marker_idx >= 0:
                            next_marker_pat = re.compile(r'#\s*===\s*VALIDACIÓN\s+TAREA:')
                            end_impl = len(asm_lines)
                            for i in range(marker_idx + 1, len(asm_lines)):
                                if next_marker_pat.search(asm_lines[i]):
                                    end_impl = i
                                    break
                            asm_lines = asm_lines[:end_impl] + val_lines + asm_lines[end_impl:]
                        else:
                            asm_lines.extend(val_lines)
                    else:
                        main_line_idx = -1
                        for i, line in enumerate(asm_lines):
                            if "if __name__" in line and "__main__" in line:
                                main_line_idx = i
                                break
                        if main_line_idx >= 0:
                            asm_lines.extend(val_lines)
                        else:
                            asm_lines.append("")
                            asm_lines.append("if __name__ == '__main__':")
                            asm_lines.extend(val_lines)
                    
                    assembled_content = "\n".join(asm_lines)
                                
                validation_result = self.assembler.validate(
                    assembled_content, 
                    str(script_path), 
                    validation_mode="auto"
                )
                
                self.asm_original_content = assembled_content
                self._asm_set_view(assembled_content)
                self._asm_output_clear()
                self._asm_output_append(validation_result.get("output", ""))

                if validation_result.get("success"):
                    # Limpiar inputs para siguiente tarea
                    self.asm_input.delete("1.0", tk.END)
                    self.asm_coder_input.delete("1.0", tk.END)
                    
                    if show_validation_notice:
                        messagebox.showinfo(
                            "Validación agregada",
                            "Se agregó validación al final del archivo.\n\n" +
                            "Si existe validación anterior similar, elimínela manualmente."
                        )
                        # Activar modo edición para que el usuario pueda hacer cambios
                        self.asm_edit_toggle.set(True)
                        self.asm_view.config(state="normal", bg="#2d2d2d", fg="#d4d4d4")
                        self.asm_status_lbl.config(
                            text="Modo edición activado - revise y guarde cambios",
                            foreground="#fbbf24"
                        )
                    else:
                        self.asm_status_lbl.config(
                            text="Exito - " + script_path.name + " - Validacion OK",
                            foreground="#4ade80"
                        )
                else:
                    self.asm_status_lbl.config(text="Fallo en validacion", foreground="#f87171")

                if self._validate_python_syntax(assembled_content, str(script_path)):
                    self.asm_syntax_lbl.config(text="Sintaxis valida", foreground="#4ade80")
                else:
                    self.asm_syntax_lbl.config(text="Error de sintaxis", foreground="#f87171")
                    
            except Exception as e:
                messagebox.showerror("Error critico", str(e))
                self._asm_output_clear()
                self._asm_output_append("Error: " + str(e))
                self.asm_status_lbl.config(text="Error inesperado", foreground="#f87171")  
                      
    def _asm_finish(self, stdout, stderr, rc, script_path, parsed):
        out = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}\nReturncode: {rc}\n" if (stdout or stderr) else "(sin output)\n"
        self._asm_output_append(out)
        
        # FIX: Verificar que script_path no es None
        script_name = script_path.name if script_path else "memoria"
        
        if rc == 0:
            self.asm_status_lbl.config(text=f"✅ Éxito — {script_name} — Revisa cambios (Rojo) y APROBAR", foreground="#4ade80")
        else:
            self.asm_status_lbl.config(text="❌ Errores en ejecución", foreground="#f87171")

    def _asm_approve(self):
        path = self.asm_file_path.get()
        if not path:
            messagebox.showwarning("Sin archivo", "No hay ruta de archivo definida.")
            return

        if not messagebox.askyesno("Confirmar", "Confirmar cambios en:\n" + path + "?"):
            return

        try:
            script_path = Path(path)
            task_id = self.asm_task_id.get().strip() or self._parsed.get("tarea_id", "N/A")
            
            # Crear backup con nombre fijo: nombre_original.ext
            backup_path = script_path.parent / f"{script_path.stem}_original{script_path.suffix}"
            
            # Crear/sobrescribir backup del archivo actual
            if script_path.exists():
                shutil.copy2(script_path, backup_path)
            
            # Guardar contenido del preview
            preview_content = self.asm_view.get('1.0', 'end-1c')
            script_path.write_text(preview_content, encoding="utf-8")
            
            # Actualizar baseline
            self.asm_baseline_content = preview_content
            self.asm_original_content = preview_content
            
            # Marcar tarea completada
            self._mark_task_complete_by_id(task_id)
            
            resumen = "Tarea: " + task_id + "\n"
            resumen += "Archivo: " + str(script_path) + "\n"
            resumen += "Backup: " + str(backup_path) + "\n"
            
            self.root.clipboard_clear()
            self.root.clipboard_append(resumen)
            
            messagebox.showinfo("Aprobado", resumen)
            self._asm_clear_inputs()
            self.refresh_plan_view()
            
        except Exception as e:
            messagebox.showerror("Error al aprobar", str(e))
    
    def _asm_reject(self):
        path = self.asm_file_path.get()
        if not path:
            messagebox.showwarning("Sin archivo", "No hay ruta de archivo definida.")
            return

        try:
            script_path = Path(path)
            backup_path = script_path.parent / f"{script_path.stem}_original{script_path.suffix}"
            
            if not backup_path.exists():
                messagebox.showwarning("Sin backup", "No existe archivo original para restaurar.")
                return
            
            # Restaurar desde el backup
            shutil.copy2(backup_path, script_path)
            
            # Eliminar el backup después de restaurar
            backup_path.unlink()
            
            # Actualizar contenido
            content = script_path.read_text(encoding="utf-8")
            self.asm_original_content = content
            self.asm_baseline_content = content
            self.asm_undo_stack.clear()
            self.asm_redo_stack.clear()
            self._asm_set_view(content)          # ← Muestra contenido original en vista
            self._asm_clear_inputs()             # ← Limpia inputs del formulario
            self.asm_status_lbl.config(text="RESTAURADO - archivo original recuperado", foreground="#fbbf24")
        
        except Exception as e:
            messagebox.showerror("Error al restaurar", str(e)) 
    
    def _show_anchors_help(self):
        """Muestra ventana con ayuda de anclas disponibles."""
        help_window = tk.Toplevel(self.root)
        help_window.title("Anclas Disponibles - Sistema APA v3.1")
        help_window.geometry("800x600")
        help_window.configure(bg="#1e1e1e")
        
        # Título
        ttk.Label(help_window, text="Sistema de Anclas - Referencia", 
                  font=("Segoe UI", 14, "bold")).pack(pady=10)
        
        # Área de texto con scroll
        text_frame = ttk.Frame(help_window)
        text_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        help_text = scrolledtext.ScrolledText(
            text_frame, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4",
            insertbackground="white", font=("Consolas", 10),
            relief="flat", padx=10, pady=10
        )
        help_text.pack(fill="both", expand=True)
        
        # Generar contenido
        anchors = PlannerOutputParser.list_available_anchors()
        
        content = "# ANCLAS DISPONIBLES\n\n"
        
        categories = {
            "Archivo": [],
            "Función": [],
            "Clase": [],
            "Método": [],
            "Variable": [],
            "Posicional": [],
            "Patrón": [],
            "Import": [],
            "Bloque": [],
            "Contextual": [],
            "Decorador": [],
            "Comentario": [],
            "Especial": [],
        }
        
        for a in anchors:
            ancla = a["ancla"]
            if "ARCHIVO" in ancla:
                categories["Archivo"].append(a)
            elif "FUNCION" in ancla:
                categories["Función"].append(a)
            elif "CLASE" in ancla:
                categories["Clase"].append(a)
            elif "METODO" in ancla:
                categories["Método"].append(a)
            elif "VARIABLE" in ancla:
                categories["Variable"].append(a)
            elif "LINEA" in ancla or "RANGO" in ancla:
                categories["Posicional"].append(a)
            elif "CONTIENE" in ancla:
                categories["Patrón"].append(a)
            elif "IMPORT" in ancla:
                categories["Import"].append(a)
            elif "BLOQUE" in ancla:
                categories["Bloque"].append(a)
            elif "EN_CLASE" in ancla or "EN_FUNCION" in ancla:
                categories["Contextual"].append(a)
            elif "DECORADOR" in ancla:
                categories["Decorador"].append(a)
            elif "COMENTARIO" in ancla or "TODO" in ancla:
                categories["Comentario"].append(a)
            else:
                categories["Especial"].append(a)
        
        for cat, items in categories.items():
            if items:
                content += f"## {cat}\n\n"
                for item in items:
                    content += f"### {item['ancla']}\n"
                    content += f"**Descripción:** {item['descripcion']}\n"
                    content += f"**Ejemplo:** `{item['ejemplo']}`\n\n"
        
        help_text.insert("1.0", content)
        help_text.config(state="disabled")
        
        # Botón copiar
        def copy_help():
            help_window.clipboard_clear()
            help_window.clipboard_append(content)
            messagebox.showinfo("Copiado", "Documentación copiada al portapapeles")
        
        ttk.Button(help_window, text="📋 Copiar documentación", 
                   command=copy_help).pack(pady=10)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers 
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_python_syntax(self, content: str, path: str) -> tuple:
        if not path.endswith(".py"): return True, ""
        try:
            ast.parse(content)
            return True, "✅ Sintaxis Python válida"
        except SyntaxError as e:
            return False, f"❌ SyntaxError línea {e.lineno}: {e.msg}"
 
    def _asm_undo(self):
        if not self.asm_undo_stack: return
        # Guardar estado actual en redo antes de deshacer
        current_state = {
            "content": self.asm_original_content,
            "planner": self.asm_input.get("1.0", "end-1c"),
            "coder": self.asm_coder_input.get("1.0", "end-1c")
        }
        self.asm_redo_stack.append(current_state)
        # Restaurar estado anterior
        prev = self.asm_undo_stack.pop()
        self.asm_original_content = prev["content"]
        self._asm_set_view(prev["content"])
        # Restaurar inputs
        self.asm_input.delete("1.0", tk.END)
        self.asm_input.insert("1.0", prev["planner"])
        self.asm_coder_input.delete("1.0", tk.END)
        self.asm_coder_input.insert("1.0", prev["coder"])
        self.asm_view.config(state="disabled")
        self.asm_status_lbl.config(text="↩ Deshecho", foreground="#fbbf24")    

    def _asm_redo(self):
        if not self.asm_redo_stack: return
        # Guardar estado actual en undo antes de rehacer
        current_state = {
            "content": self.asm_original_content,
            "planner": self.asm_input.get("1.0", "end-1c"),
            "coder": self.asm_coder_input.get("1.0", "end-1c")
        }
        self.asm_undo_stack.append(current_state)
        # Restaurar estado siguiente
        next_state = self.asm_redo_stack.pop()
        self.asm_original_content = next_state["content"]
        self._asm_set_view(next_state["content"])
        # Restaurar inputs
        self.asm_input.delete("1.0", tk.END)
        self.asm_input.insert("1.0", next_state["planner"])
        self.asm_coder_input.delete("1.0", tk.END)
        self.asm_coder_input.insert("1.0", next_state["coder"])
        self.asm_view.config(state="disabled")
        self.asm_status_lbl.config(text="↪ Rehecho", foreground="#4ade80")
 
    def _asm_reload_from_disk(self):
        path = self.asm_file_path.get()
        if not path: return
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.asm_original_content = content
            self.asm_baseline_content = content # Actualizar baseline al recargar manual
            self._asm_set_view(content)
            self.asm_view.config(state="disabled")
            self.asm_status_lbl.config(text=f"🔄 Recargado de disco", foreground="#60a5fa")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _asm_copy_summary(self):
        path     = self.asm_file_path.get()
        task_id  = self.asm_task_id.get().strip() or self._parsed.get("tarea_id", "N/A")
        output   = self.asm_output.get('1.0', 'end-1c').strip()
        status   = self.asm_status_lbl.cget("text")
        syntax   = self.asm_syntax_lbl.cget("text")
        approved = "GUARDADO" in status or "APROBADO" in status
        ts       = datetime.now().strftime("%Y-%m-%d %H:%M")
        content_in_memory = self.asm_view.get('1.0', 'end-1c')
        script_lines = content_in_memory.count('\n') + 1 if content_in_memory.strip() else 0

        summary = (
            f"{'═'*54}\n"
            f"RESULTADO DE VALIDACIÓN — {ts}\n"
            f"{'═'*54}\n"
            f"Tarea ID    : {task_id}\n"
            f"Script      : {path or 'N/A'}\n"
            f"Líneas      : {script_lines}\n"
            f"Estado      : {'✅ APROBADO' if approved else '⏳ PENDIENTE / ❌ RECHAZADO'}\n"
            f"Sintaxis    : {syntax or 'no verificada'}\n"
            f"{'─'*54}\n"
            f"OUTPUT DE EJECUCIÓN:\n"
            f"{output if output else '(no ejecutado)'}\n"
            f"{'─'*54}\n"
            f"ESTADO DE MEMORIA DEL PLANIFICADOR:\n"
            f"{'[X] Requiere actualización — actualiza tu mapa mental del script.' if approved else '[ ] Sin cambios (tarea no aprobada — mantén estado anterior).'}\n"
            f"{'─'*54}\n"
            f"Estado final: {status}\n"
            f"{'═'*54}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(summary)
        self.root.update()
        messagebox.showinfo("Copiado",
            "Resumen copiado al portapapeles.\n"
            "Pégalo en el chat del Planificador.")

    def _asm_output_clear(self):
        self.asm_output.config(state="normal")
        self.asm_output.delete('1.0', tk.END)
        self.asm_output.config(state="disabled")

    def _asm_output_append(self, text: str):
        self.asm_output.config(state="normal")
        self.asm_output.insert(tk.END, text)
        self.asm_output.see(tk.END)
        self.asm_output.config(state="disabled")

    def _get_existing_imports(self, content: str) -> list:
        return [l.strip() for l in content.split('\n') if l.strip().startswith("import ") or l.strip().startswith("from ")]

    def _asm_toggle_edit(self):
        if self.asm_edit_toggle.get():
            self.asm_view.config(state="normal", bg="#2d2d2d", fg="#d4d4d4")
        else:
            self.asm_original_content = self.asm_view.get('1.0', 'end-1c')
            self.asm_view.config(state="disabled", bg="#1a1a1a", fg="#a0a0a0")
            self._asm_highlight_changes() # Recalcular rojo al salir de edición

    def _asm_reset_hard(self):
        """Vacía completamente el workspace (vista, inputs y memoria)."""
        if not messagebox.askyesno("Resetear", "¿Vaciar todo el workspace?\nSe perderán los cambios no guardados."):
            return
        
        # 1. Limpiar vista de script (ponerla en blanco)
        self.asm_view.config(state="normal")
        self.asm_view.delete('1.0', tk.END)
        self.asm_view.config(state="disabled")
        
        # 2. Resetear variables de estado
        self.asm_file_path.set("")
        self.asm_task_id.set("")
        self.asm_original_content = ""
        self.asm_baseline_content = ""
        self.asm_undo_stack.clear()
        self.asm_redo_stack.clear()
        self.asm_backup_path = None
        
        # 3. Limpiar inputs y outputs
        self._asm_clear_inputs()
        
        # 4. Actualizar UI
        self.asm_lines_lbl.config(text="0 líneas")
        self.asm_status_lbl.config(text="💣 Workspace reseteado y vacío.", foreground="#fbbf24")
    
    def _asm_copy_code(self):
        """Copia el código del script ensamblado al portapapeles."""
        code = self.asm_view.get('1.0', 'end-1c')
        if code.strip():
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self.root.update()
            messagebox.showinfo("Copiado", "Código copiado al portapapeles.")
        else:
            messagebox.showwarning("Vacío", "No hay código para copiar.")   
 
    # ─────────────────────────────────────────────────────────────────────────
    # Plan helpers
    # ─────────────────────────────────────────────────────────────────────────

    def toggle_add_mode(self):
        if not self.add_mode:
            self.add_btn.configure(text="Aceptar")
            self.add_text.config(state='normal')
            self.add_mode = True
        else:
            self.add_btn.configure(text="Añadir Tarea")
            self.add_text.config(state='disabled')
            self.add_mode = False
            self._add_task()

    def _add_task(self):
        text = self.add_text.get('1.0', 'end-1c').strip()
        if not text: return
        if not self.plan_path or not self.plan_path.exists():
            messagebox.showerror("Error", "No hay plan cargado.")
            return
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            new_content = content.rstrip() + "\n" + text + "\n"
            self.plan_path.write_text(new_content, encoding="utf-8")
            self.refresh_plan_view()
            self.add_text.delete('1.0', tk.END)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def complete_task(self):
        task_id = self.done_task_id.get().strip()
        if not task_id:
            messagebox.showwarning("Input requerido", "Introduce un ID de tarea.")
            return
        self._mark_task_complete_by_id(task_id)
        self.done_task_id.delete(0, tk.END)

    def _mark_task_complete_by_id(self, task_id: str):
        if not self.plan_path or not self.plan_path.exists():
            return
        
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            lines = content.split('\n')
            modified = False
            for i, line in enumerate(lines):
                # Busca formato markdown task: - [ ]
                if task_id in line and "- [ ]" in line:
                    lines[i] = line.replace("- [ ]", "- [X]", 1)
                    modified = True
                    break
            
            if modified:
                self.plan_path.write_text("\n".join(lines), encoding="utf-8")
                self.refresh_plan_view()
        except Exception as e:
            print(f"Error actualizando plan: {e}")

    def refresh_plan_view(self):
        if not self.plan_path or not self.plan_path.exists():
            self.plan_text.config(state="normal")
            self.plan_text.delete("1.0", tk.END)
            self.plan_text.insert("1.0", "⚠️ No se encontró archivo PLAN_*.md")
            self.plan_text.config(state="disabled")
            return
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            self.plan_text.config(state="normal")
            self.plan_text.delete("1.0", tk.END)
            self.plan_text.insert("1.0", content)
            self.plan_text.config(state="disabled")
            self._scroll_to_priority_task(content)
            self._auto_select_and_highlight_after_load(content)  # AGREGAR ESTA LÍNEA
        except Exception as e:
            messagebox.showerror("Error", str(e))   
      
    def _scroll_to_priority_task(self, content: str):
        """Scroll automático robusto hacia tarea Actual/Próxima/Alta pendiente."""
        lines = content.split('\n')
        target_line = None
        candidate_proxima = None
        candidate_alta = None
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("### "):
                task_line = i + 1
                priority_value = None
                status_value = None
                for j in range(i + 1, min(i + 16, len(lines))):
                    next_line = lines[j].strip()
                    if next_line.startswith("### "):
                        break
                    if "**Prioridad:**" in next_line:
                        parts = next_line.split("**Prioridad:**", 1)
                        if len(parts) > 1:
                            priority_value = parts[1].strip().rstrip('-').strip()
                    if "**Estado:**" in next_line or "- **Estado:**" in next_line:
                        if "[ ]" in next_line:
                            status_value = "pending"
                        elif "[x]" in next_line:
                            status_value = "completed"
                if priority_value:
                    if "/ Actual" in priority_value:
                        target_line = task_line
                        break
                    elif "/ Próxima" in priority_value and candidate_proxima is None:
                        candidate_proxima = task_line
                    elif priority_value.startswith("Alta") and candidate_alta is None:
                        if status_value == "pending" or status_value is None:
                            candidate_alta = task_line
            i += 1
        if target_line is None:
            if candidate_proxima is not None:
                target_line = candidate_proxima
            elif candidate_alta is not None:
                target_line = candidate_alta
        if target_line is not None:
            self.plan_text.see(f"{target_line}.0")    
    
    def _auto_select_and_highlight_after_load(self, content: str):
        """Selecciona y resalta tarea prioritaria."""
        lines = content.split('\n')
        selected = None
        actual_task_line = None
        
        for idx, line in enumerate(lines):
            if line.strip().startswith("- [ ]") and "/ Actual" in line:
                match = re.search(r'-\s*\[\s*\]\s*(\w+\d+)\s*[–-]', line)
                if match:
                    selected = match.group(1)
                    actual_task_line = idx
                    break
        
        if not selected:
            for line in lines:
                if line.strip().startswith("- [ ]") and "/ Próxima" in line:
                    match = re.search(r'-\s*\[\s*\]\s*(\w+\d+)\s*[–-]', line)
                    if match:
                        selected = match.group(1)
                        break
        
        if not selected:
            for line in lines:
                if line.strip().startswith("- [ ]") and "Alta" in line:
                    match = re.search(r'-\s*\[\s*\]\s*(\w+\d+)\s*[–-]', line)
                    if match:
                        selected = match.group(1)
                        break
        
        if selected and self.done_task_id:
            self.done_task_id.delete(0, tk.END)
            self.done_task_id.insert(0, selected)
        
        if actual_task_line is not None:
            self.plan_text.tag_configure("actual_task", background="#3b82f6", foreground="white")
            self.plan_text.tag_add("actual_task", f"{actual_task_line + 1}.0", f"{actual_task_line + 1}.end")
        
    def complete_task(self):
        """Marca una tarea como completada."""
        task_id_input = self.done_task_id.get().strip() if self.done_task_id else ""
        if not task_id_input:
            return messagebox.showwarning("Campo vacío", "Ingrese un ID de tarea (ej. Q1.2).")
        
        plan_path = self.plan_path
        if not plan_path or not plan_path.exists():
            return messagebox.showerror("Error", f"Plan no encontrado.")
        
        try:
            content = plan_path.read_text(encoding="utf-8")
            lines = content.split('\n')
            task_line_idx = -1
            pat_task = re.compile(rf'^###\s+{re.escape(task_id_input)}\b')
            
            for idx, line in enumerate(lines):
                if pat_task.match(line.strip()):
                    task_line_idx = idx
                    break
            
            if task_line_idx < 0:
                return messagebox.showerror("No hallada", f"No se encontró la tarea '{task_id_input}'.")
            
            for k in range(task_line_idx + 1, min(task_line_idx + 15, len(lines))):
                if lines[k].strip().startswith("### "):
                    break
                if "**Estado:**" in lines[k] or "- **Estado:**" in lines[k]:
                    lines[k] = re.sub(r'\[ \]', '[x]', lines[k])
                    if "Completada" not in lines[k]:
                        lines[k] = lines[k].replace("Pendiente", "Completada")
                if "**Prioridad:**" in lines[k]:
                    lines[k] = re.sub(r"\*\*Prioridad:\*\*\s*.+?(?:\s*$)", "**Prioridad:** X / Completada", lines[k])
            
            plan_path.write_text('\n'.join(lines), encoding="utf-8")
            self.refresh_plan_view()
            
            line_num = task_line_idx + 1
            self.plan_text.after(200, lambda: self.plan_text.see(f"{line_num}.0"))
            
            if self.done_task_id:
                self.done_task_id.delete(0, tk.END)
            
            messagebox.showinfo("Éxito", f"Tarea {task_id_input} marcada como completada.")
            
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo completar: {e}")    
    
    # ─────────────────────────────────────────────────────────────────────────
    # Helper generales
    # ─────────────────────────────────────────────────────────────────────────

    def get_source_root(self):
        return Path(self.project_root.get())

    def find_file(self, root: Path, relative_path: str) -> Path:
        full = root / relative_path
        if full.exists(): return full
        
        name = Path(relative_path).name
        matches = list(root.rglob(name))
        if matches: return matches[0]
        
        raise FileNotFoundError(f"Archivo no encontrado: {relative_path}")

    def auto_detect_project_root(self):
        # Si ya hay valor y es válido, no hacer nada
        if self.project_root.get() and Path(self.project_root.get()).exists():
            return
        
        cwd = Path.cwd()
        # Buscar indicadores de proyecto (carpeta apa, .git, PLAN.md)
        if (cwd / "apa").is_dir() or (cwd / "PLAN.md").is_file() or (cwd / ".git").is_dir():
            self.project_root.set(str(cwd))
        else:
            # Si no, intentar con el padre
            parent = cwd.parent
            if (parent / "apa").is_dir():
                self.project_root.set(str(parent))

    def browse_project_root(self):
        curr = self.project_root.get()
        init = curr if curr and Path(curr).exists() else str(Path.cwd())
        dir_ = filedialog.askdirectory(initialdir=init, title="Seleccionar raíz del proyecto")
        if dir_:
            self.project_root.set(dir_)

    def update_project_root(self):
        p = self.project_root.get()
        if not Path(p).exists():
            messagebox.showwarning("Ruta inválida", f"La ruta {p} no existe.")

    # ─────────────────────────────────────────────────────────────────────────
    # Configuración y Caché
    # ─────────────────────────────────────────────────────────────────────────

    def _load_config(self):
        """Carga la última ruta de proyecto. Devuelve True si tuvo éxito."""
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                last_path = data.get("last_project_root")
                if last_path and Path(last_path).exists():
                    self.project_root.set(last_path)
                    return True
            except Exception:
                pass
        return False

    def _save_config(self):
        """Guarda la ruta actual en el archivo JSON."""
        current_path = self.project_root.get()
        if current_path:
            try:
                data = {"last_project_root": current_path}
                self.config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Pestaña Procesar Prompt
    # ─────────────────────────────────────────────────────────────────────────

    def process(self):
        # Lógica básica de procesamiento de prompts (placeholder o simple)
        text = self.input_text.get('1.0', 'end-1c')
        # Ejemplo simple: pasar tal cual o procesar tags [INCRUSTAR]
        # Por ahora solo copia al output para ejemplo
        processed = text # Lógica real iría aquí
        
        # Buscar tags [INCRUSTAR: ruta]
        import re
        pattern = re.compile(r"\[INCRUSTAR:\s*(.+?)\]")
        matches = pattern.findall(text)
        
        result = text
        for match in matches:
            try:
                root = self.get_source_root()
                file_path = self.find_file(root, match)
                content = file_path.read_text(encoding="utf-8")
                # Reemplazo simple
                result = result.replace(f"[INCRUSTAR: {match}]", f"\n---\n# {match}\n{content}\n---\n")
            except Exception as e:
                result = result.replace(f"[INCRUSTAR: {match}]", f"\n[ERROR: {e}]\n")

        self.output_text.delete('1.0', tk.END)
        self.output_text.insert('1.0', result)

    def copy(self):
        text = self.output_text.get('1.0', 'end-1c')
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()

    def clear(self):
        self.input_text.delete('1.0', tk.END)
        self.output_text.delete('1.0', tk.END)

    def pdf(self):
        if not PDF_AVAILABLE:
            messagebox.showwarning("Dependencia", "Se necesita la librería fpdf.")
            return
        
        text = self.output_text.get('1.0', 'end-1c')
        if not text: return
        
        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=10)
            # Manejo básico de encoding
            safe_text = text.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 5, safe_text)
            
            f = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
            if f: pdf.output(f)
        except Exception as e:
            messagebox.showerror("Error PDF", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
    