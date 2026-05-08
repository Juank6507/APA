# tools/ensamblador_gui.py — Procesador de Prompts y Ensamblador Atómico (v3.0)
# Cambios: Resaltado de diferencias (Rojo), Persistencia de Vista, Limpieza Inteligente.

import ast
import json
import re
import shutil
import subprocess
import threading
import tkinter as tk
import difflib

from tkinter import scrolledtext, messagebox, filedialog, ttk
from pathlib import Path
from datetime import datetime

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
# Parser del output del Planificador (VERSIÓN ESTRUCTURAL AST)
# ─────────────────────────────────────────────────────────────────────────────

class PlannerOutputParser:
    # Regex para campos escalares (tolerantes a espacios y mayúsculas)
    _RE_SCRIPT       = re.compile(r'-\s*SCRIPT\s*:\s*(.+)', re.IGNORECASE)
    _RE_TAREA_ID     = re.compile(r'-\s*TAREA_?ID\s*:\s*(\S+)', re.IGNORECASE)
    _RE_ANCLA        = re.compile(r'-\s*ANCLA\s*:\s*(.+)', re.IGNORECASE)
    _RE_MODO         = re.compile(r'-\s*MODO_?EJECUCION\s*:\s*(\S+)', re.IGNORECASE)
    _RE_CONTEXTO     = re.compile(r'-\s*CONTEXTO\s*:\s*(.+)', re.IGNORECASE)
    _RE_COINCIDENCIA = re.compile(r'-\s*COINCIDENCIA\s*:\s*(\S+)', re.IGNORECASE)
    _RE_LINEA        = re.compile(r'-\s*LINEA\s*:\s*(\d+)', re.IGNORECASE)
    _RE_RANGO        = re.compile(r'-\s*RANGO\s*:\s*(\d+)\s*-\s*(\d+)', re.IGNORECASE)
    _RE_INDENT       = re.compile(r'#\s*INDENTACIÓN\s*:\s*(\d+)', re.IGNORECASE)
    

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
        FIX P2 — Parser robusto basado en split, no en regex compleja.
        Localiza la sección ## IMPORTS_NUEVOS dividiendo el texto por esa cabecera,
        luego procesa línea a línea con limpieza de módulos.
        Acepta:
          - Nombres sueltos:           'logging'  → 'import logging'
          - Nombres con puntuación:    'logging.' → 'import logging'
          - Imports completos:         'import os' → 'import os'
          - From imports:              'from pathlib import Path'
        """
        imports = []

        # Buscar sección ## IMPORTS_NUEVOS de forma tolerante
        marker = None
        for line in text.split('\n'):
            if re.match(r'##\s*IMPORTS_NUEVOS', line, re.IGNORECASE):
                marker = line
                break

        if marker is None:
            return imports  # Sección no presente — válido, no es error

        # Todo lo que viene después del marcador hasta la siguiente sección ##
        after = text.split(marker, 1)[1]
        section_lines = []
        for line in after.split('\n'):
            if line.strip().startswith('##'):  # nueva sección → parar
                break
            section_lines.append(line)

        for line in section_lines:
            raw = line.strip()
            if not raw or raw.startswith('#'):
                continue

            # Import completo: 'import x' o 'from x import y'
            if raw.startswith("import ") or raw.startswith("from "):
                # Sanitizar el módulo dentro del import completo
                canonical = raw
            else:
                # Nombre suelto: limpiar y construir import
                clean = cls._sanitize_module(raw)
                if not clean:
                    continue
                # Validar que es un identificador Python válido
                # (evita meter basura como "---" o lineas de guiones)
                if not re.match(r'^[\w][\w\.]*$', clean):
                    continue
                canonical = f"import {clean}"

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

    @staticmethod
    def resolve_anchor(content: str, anchor_raw: str) -> tuple:
        """
        Resuelve un ancla AST y retorna (line_number, line_content).
        line_number es 1-indexed.
        Retorna (0, "") si no puede resolver el ancla.
        
        Soporta:
        - Anclas de archivo: INICIO_ARCHIVO, FIN_ARCHIVO, ARCHIVO_NUEVO
        - Anclas de función: DESPUES_FUNCION, ANTES_FUNCION, REEMPLAZAR_FUNCION
        - Anclas de clase: INICIO_CLASE, ANTES_CLASE, FIN_CLASE, REEMPLAZAR_CLASE
        - Anclas de método: DESPUES_METODO, ANTES_METODO, REEMPLAZAR_METODO
        - Anclas de variable: REEMPLAZAR_VARIABLE, DESPUES_VARIABLE, ANTES_VARIABLE
        - Anclas especiales: INSERTAR_ANTES_MAIN, REEMPLAZAR_BLOQUE_MAIN
        - Soporta funciones async (async def)
        """
        try:
            tree = ast.parse(content)
            lines = content.split('\n')
            
            # Anclas básicas de archivo
            if anchor_raw == "INICIO_ARCHIVO":
                return 1, lines[0] if lines else ""
            if anchor_raw == "FIN_ARCHIVO":
                return len(lines), lines[-1] if lines else ""
            if anchor_raw == "ARCHIVO_NUEVO":
                return -1, ""  # Código especial: crear archivo nuevo
            
            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS POSICIONALES (NUEVO FASE 2)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw.startswith("LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1].strip())
                    if 1 <= num <= len(lines):
                        return num, lines[num - 1]
                except ValueError:
                    pass
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1].strip())
                    if 1 <= num < len(lines):
                        return num + 1, lines[num]
                except ValueError:
                    pass
                return 0, ""
            
            if anchor_raw.startswith("ANTES_LINEA:"):
                try:
                    num = int(anchor_raw.split(":")[1].strip())
                    if 1 <= num <= len(lines):
                        return num, lines[num - 2] if num > 1 else ""
                except ValueError:
                    pass
                return 0, ""
            
            if anchor_raw.startswith("RANGO_LINEAS:"):
                try:
                    parts = anchor_raw.split(":")[1].strip().split("-")
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    if 1 <= start <= end <= len(lines):
                        return start, lines[start - 1]
                except (ValueError, IndexError):
                    pass
                return 0, ""
            
            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS POR PATRÓN (NUEVO FASE 2)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw.startswith("LINEA_CONTIENE:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if search_text in line:
                        return i + 1, line
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_LINEA_CONTIENE:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if search_text in line:
                        if i + 1 < len(lines):
                            return i + 2, lines[i + 1]
                        return i + 1, ""
                return 0, ""
            
            if anchor_raw.startswith("ANTES_LINEA_CONTIENE:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if search_text in line:
                        # Retornar línea antes de la encontrada (i+1 para 1-indexed)
                        if i > 0:
                            return i + 1, lines[i - 1]
                        return 1, ""
                return 0, ""
            
            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS DE IMPORT (NUEVO FASE 2)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw == "FIN_IMPORTS":
                last_import_line = 0
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        last_import_line = i + 1
                    elif stripped and not stripped.startswith("#") and last_import_line > 0:
                        break
                if last_import_line > 0:
                    return last_import_line, lines[last_import_line - 1]
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_IMPORT:"):
                import_name = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("import ") and import_name in stripped:
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else ""
                    if stripped.startswith("from ") and import_name in stripped:
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else ""
                return 0, ""
            
            if anchor_raw == "ANTES_IMPORTS":              
                first_import_line = 0
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("import ") or stripped.startswith("from "):
                        first_import_line = i + 1
                        break
                if first_import_line > 0:
                    return first_import_line, lines[first_import_line - 2] if first_import_line > 1 else ""
                return 1, lines[0] if lines else ""            

            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS DE BLOQUE (NUEVO FASE 3)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw.startswith("DESPUES_BLOQUE_IF:"):
                condition = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.If):
                        # Buscar if con la condición especificada
                        if condition in ast.unparse(node.test):
                            return node.end_lineno, lines[node.end_lineno - 1]
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_BLOQUE_FOR:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.For):
                        if var_name in ast.unparse(node.target):
                            return node.end_lineno, lines[node.end_lineno - 1]
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_BLOQUE_TRY:"):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Try):
                        return node.end_lineno, lines[node.end_lineno - 1]
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_BLOQUE_WITH:"):
                resource = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.With):
                        # Buscar with con el recurso especificado
                        for item in node.items:
                            if resource in ast.unparse(item.context_expr):
                                return node.end_lineno, lines[node.end_lineno - 1]
                return 0, ""
            
            # Anclas especiales de main
            
            
            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS CONTEXTUALES (NUEVO FASE 3)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw.startswith("EN_CLASE:"):
                # Formato: EN_CLASE:Nombre|ANCLA:tipo:valor
                parts = anchor_raw.split("|", 1)
                if len(parts) == 2:
                    class_part = parts[0].split(":", 1)[1].strip()
                    inner_anchor = parts[1].strip()
                    # Buscar la clase y resolver ancla dentro de ella
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and node.name == class_part:
                            # Extraer código de la clase
                            class_lines = lines[node.lineno - 1:node.end_lineno]
                            class_content = "\n".join(class_lines)
                            # Resolver ancla interna (recursivo)
                            inner_line, inner_content = PlannerOutputParser.resolve_anchor(class_content, inner_anchor)
                            if inner_line > 0:
                                # Ajustar número de línea al archivo original
                                return node.lineno - 1 + inner_line, inner_content
                return 0, ""
            
            if anchor_raw.startswith("EN_FUNCION:"):
                # Formato: EN_FUNCION:nombre|ANCLA:tipo:valor
                parts = anchor_raw.split("|", 1)
                if len(parts) == 2:
                    func_part = parts[0].split(":", 1)[1].strip()
                    inner_anchor = parts[1].strip()
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_part:
                            func_lines = lines[node.lineno - 1:node.end_lineno]
                            func_content = "\n".join(func_lines)
                            inner_line, inner_content = PlannerOutputParser.resolve_anchor(func_content, inner_anchor)
                            if inner_line > 0:
                                return node.lineno - 1 + inner_line, inner_content
                return 0, ""
            
            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS DE DECORADOR (NUEVO FASE 3)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw.startswith("ANTES_DECORADOR:"):
                dec_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        for dec in node.decorator_list:
                            dec_str = ast.unparse(dec)
                            if dec_name in dec_str:
                                # Retornar línea antes del decorador
                                return node.lineno - len(node.decorator_list), lines[node.lineno - len(node.decorator_list) - 1]
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_DECORADOR:"):
                dec_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        for i, dec in enumerate(node.decorator_list):
                            dec_str = ast.unparse(dec)
                            if dec_name in dec_str:
                                # Retornar línea después del decorador (puede haber más decoradores)
                                dec_line = node.lineno - len(node.decorator_list) + i
                                return dec_line + 1, lines[dec_line]
                return 0, ""
            
            if anchor_raw.startswith("REEMPLAZAR_DECORADOR:"):
                dec_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        for dec in node.decorator_list:
                            dec_str = ast.unparse(dec)
                            if dec_name in dec_str:
                                # Retornar línea del decorador
                                return dec.lineno, lines[dec.lineno - 1]
                return 0, ""
            
            # ═══════════════════════════════════════════════════════════════════
            # ANCLAS DE COMENTARIO (NUEVO FASE 3)
            # ═══════════════════════════════════════════════════════════════════
            if anchor_raw.startswith("DESPUES_COMENTARIO:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if line.strip().startswith("#") and search_text.lower() in line.lower():
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else ""
                return 0, ""
            
            if anchor_raw.startswith("ANTES_COMENTARIO:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    if line.strip().startswith("#") and search_text.lower() in line.lower():
                        return i + 1, lines[i - 1] if i > 0 else ""
                return 0, ""
            
            if anchor_raw.startswith("TODO:"):
                search_text = anchor_raw.split(":", 1)[1].strip()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("#") and "todo" in stripped.lower() and search_text.lower() in line.lower():
                        return i + 1, line
                return 0, ""            
            
            if anchor_raw == "INSERTAR_ANTES_MAIN":
                for i, line in enumerate(lines):
                    if line.strip().startswith("if __name__"):
                        return i, lines[i - 1] if i > 0 else ""
                return len(lines), lines[-1] if lines else ""
            
            if anchor_raw == "REEMPLAZAR_BLOQUE_MAIN":
                main_start = 0
                main_end = len(lines)
                for i, line in enumerate(lines):
                    if line.strip().startswith("if __name__"):
                        main_start = i + 1  # 1-indexed
                        break
                if main_start > 0:
                    base_indent = len(lines[main_start - 1]) - len(lines[main_start - 1].lstrip())
                    for i in range(main_start, len(lines)):
                        line = lines[i]
                        if line.strip() and not line.startswith(" " * (base_indent + 1)) and not line.startswith("\t"):
                            main_end = i
                            break
                    return main_start, lines[main_start - 1]
                return 0, ""
            
            # Anclas de variable
            if anchor_raw.startswith("REEMPLAZAR_VARIABLE:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                # Soporta: variable =, self.variable =, variable: tipo =
                pattern = re.compile(
                    rf'(\b{re.escape(var_name)}\b\s*[=:]|self\.{re.escape(var_name)}\s*=)',
                    re.IGNORECASE
                )
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        return i + 1, line
                return 0, ""
            
            if anchor_raw.startswith("DESPUES_VARIABLE:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                pattern = re.compile(
                    rf'(\b{re.escape(var_name)}\b\s*[=:]|self\.{re.escape(var_name)}\s*=)',
                    re.IGNORECASE
                )
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        return i + 2, lines[i + 1] if i + 1 < len(lines) else ""
                return 0, ""
            
            if anchor_raw.startswith("ANTES_VARIABLE:"):
                var_name = anchor_raw.split(":", 1)[1].strip()
                pattern = re.compile(
                    rf'(\b{re.escape(var_name)}\b\s*[=:]|self\.{re.escape(var_name)}\s*=)',
                    re.IGNORECASE
                )
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        return i, lines[i - 1] if i > 0 else ""
                return 0, ""
            
            target_node = None
            action = "DESPUES"
            
            # Anclas de CLASE
            if anchor_raw.startswith("INICIO_CLASE:"):
                class_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        # Insertar después de la línea de definición de clase
                        return node.lineno + 1, lines[node.lineno] if node.lineno < len(lines) else ""
                return 0, ""
            
            if anchor_raw.startswith("ANTES_CLASE:"):
                class_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == class_name:
                        return node.lineno, lines[node.lineno - 2] if node.lineno > 1 else ""
                return 0, ""
            
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
                        target_node = node
                        action = "REEMPLAZAR"
                        break
            
            # Anclas de MÉTODO (notación Clase.metodo)
            if anchor_raw.startswith("DESPUES_METODO:"):
                ref = anchor_raw.split(":", 1)[1].strip()
                class_name, method_name = PlannerOutputParser._parse_method_reference(ref)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == method_name:
                        # Si se especifica clase, verificar que está dentro de esa clase
                        if class_name:
                            # Buscar la clase padre
                            for class_node in ast.walk(tree):
                                if isinstance(class_node, ast.ClassDef) and class_node.name == class_name:
                                    # Verificar si el método está en esta clase
                                    for item in class_node.body:
                                        if isinstance(item, ast.FunctionDef) and item.name == method_name:
                                            return item.end_lineno, lines[item.end_lineno - 1]
                        else:
                            # Método global (sin clase específica)
                            target_node = node
                            action = "DESPUES"
                            break
                if target_node:
                    return target_node.end_lineno, lines[target_node.end_lineno - 1]
                return 0, ""
            
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
                                            return item.lineno - 1, lines[item.lineno - 2] if item.lineno > 1 else ""
                        else:
                            target_node = node
                            action = "ANTES"
                            break
                if target_node:
                    return target_node.lineno - 1, lines[target_node.lineno - 2] if target_node.lineno > 1 else ""
                return 0, ""
            
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
                                            return item.lineno, lines[item.lineno - 1]
                        else:
                            target_node = node
                            action = "REEMPLAZAR"
                            break
                if target_node:
                    return target_node.lineno, lines[target_node.lineno - 1]
                return 0, ""
            
            # Anclas de FUNCIÓN (soporta async)
            if anchor_raw.startswith("FIN_CLASE:"):
                # Ya manejado arriba
                pass
            
            elif anchor_raw.startswith("DESPUES_FUNCION:"):
                func_name = anchor_raw.split(":", 1)[1].strip()
                for node in ast.walk(tree):
                    # Soporta funciones normales y async
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
                        target_node = node
                        action = "REEMPLAZAR"
                        break

            # Procesar target_node encontrado
            if target_node:
                end_line = target_node.end_lineno
                start_line = target_node.lineno
                
                if action == "REEMPLAZAR":
                    return start_line, lines[start_line - 1]
                elif action == "ANTES":
                    before_line = start_line - 1
                    if before_line <= 0:
                        return 1, ""
                    return before_line, lines[before_line - 1]
                else:  # DESPUES
                    return end_line, lines[end_line - 1]

        except Exception as e:
            print(f"Error AST resolutor: {e}")
                
        return 0, ""

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
        line, _ = PlannerOutputParser.resolve_anchor(content, anchor_raw)
        
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
        self.asm_backup_path  = None             
        self._parsed          = {}
        self.asm_replaced_lines = set()  # ← NUEVO: líneas que fueron reemplazadas              

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
        ToolTip(e, "Directorio raíz del proyecto APA.")
        ttk.Button(cfg, text="📂 Examinar", command=self.browse_project_root).grid(row=0, column=2, padx=5)

        inp = ttk.LabelFrame(tab, text="📝 Prompt Base", padding=10)
        inp.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        inp.columnconfigure(0, weight=1)
        inp.rowconfigure(0, weight=1)
        self.input_text = scrolledtext.ScrolledText(inp, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.input_text.grid(row=0, column=0, sticky="nsew")

        ttk.Button(tab, text="Procesar Prompt", command=self.process).grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        out = ttk.LabelFrame(tab, text="✨ Prompt Procesado", padding=10)
        out.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)
        self.output_text = scrolledtext.ScrolledText(out, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.output_text.grid(row=0, column=0, sticky="nsew")

        act = ttk.Frame(tab, padding=5)
        act.grid(row=4, column=0, padx=10, pady=(5,10), sticky="ew")
        act.columnconfigure((0,1,2), weight=1)
        ttk.Button(act, text="Copiar",  command=self.copy).grid(row=0, column=0, padx=5)
        ttk.Button(act, text="PDF",     command=self.pdf).grid(row=0, column=1, padx=5)
        ttk.Button(act, text="Limpiar", command=self.clear).grid(row=0, column=2, padx=5)

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
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.add_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.add_text.configure(yscrollcommand=sb.set)
        self.add_btn = ttk.Button(add, text="Añadir Tarea", command=self.toggle_add_mode)
        self.add_btn.grid(row=2, column=0, pady=10, sticky="ew")

        done = ttk.LabelFrame(ctrl, text="✅ Completar Tarea", padding=10)
        done.grid(row=0, column=1, padx=5, sticky="ew")
        done.columnconfigure(0, weight=1)
        ttk.Label(done, text="ID de tarea (ej. V0):").grid(row=0, column=0, sticky="e")
        self.done_task_id = ttk.Entry(done)
        self.done_task_id.grid(row=1, column=0, sticky="ew", padx=5, pady=4)
        ttk.Button(done, text="Marcar Completada", command=self.complete_task).grid(row=2, column=0, pady=10, sticky="ew")

        ttk.Button(tab, text="Recargar Plan", command=self.refresh_plan_view).grid(row=3, column=0, padx=10, pady=10, sticky="ew")

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
        ttk.Button(cfg, text="📂 Examinar", command=self.browse_project_root).grid(row=0, column=2, padx=5)

        # Fila 1: Banner de estado
        banner = ttk.LabelFrame(tab, text="📊 Estado", padding=8)
        banner.grid(row=1, column=0, padx=10, pady=4, sticky="ew")
        banner.columnconfigure(0, weight=1)
        self.asm_status_lbl = ttk.Label(
            banner,
            text="⬇  PEGA Planificador y Codificador  →  🚀 ENSAMBLAR",
            foreground="#60a5fa", font=("Segoe UI", 10, "bold"))
        self.asm_status_lbl.grid(row=0, column=0, sticky="w")
        self.asm_parsed_lbl = ttk.Label(banner, text="", foreground="#888", font=("Segoe UI", 9))
        self.asm_parsed_lbl.grid(row=1, column=0, sticky="w", pady=(2,0))

        # Fila 2: Área Central
        work = ttk.Frame(tab)
        work.grid(row=2, column=0, padx=10, pady=4, sticky="nsew")
        work.columnconfigure(0, weight=1)
        work.columnconfigure(1, weight=1)
        work.rowconfigure(0, weight=1)

        # Panel izquierdo — INPUTS SEPARADOS
        left_container = ttk.Frame(work)
        left_container.grid(row=0, column=0, padx=(0,4), sticky="nsew")
        left_container.columnconfigure(0, weight=1)
        left_container.rowconfigure(0, weight=1)
        left_container.rowconfigure(1, weight=1)

        # Input 1: Planificador
        planner_frame = ttk.LabelFrame(left_container, text="📥 1. Output Planificador", padding=5)
        planner_frame.grid(row=0, column=0, sticky="nsew", pady=(0,2))
        planner_frame.columnconfigure(0, weight=1)
        planner_frame.rowconfigure(0, weight=1)
        self.asm_input = scrolledtext.ScrolledText(
            planner_frame, bg="#1a2332", fg="#93c5fd",
            insertbackground="white", font=("Consolas", 10))
        self.asm_input.grid(row=0, column=0, sticky="nsew")
        self.asm_input.bind("<<Paste>>", lambda e: self.root.after(80, self._asm_on_paste))
        self.asm_input.bind("<KeyRelease>", lambda e: self.root.after(300, self._asm_on_paste))

        # Input 2: Codificador
        coder_frame = ttk.LabelFrame(left_container, text="🧠 2. Código Codificador", padding=5)
        coder_frame.grid(row=1, column=0, sticky="nsew", pady=(2,0))
        coder_frame.columnconfigure(0, weight=1)
        coder_frame.rowconfigure(0, weight=1)
        self.asm_coder_input = scrolledtext.ScrolledText(
            coder_frame, bg="#1a2332", fg="#a7f3d0",
            insertbackground="white", font=("Consolas", 10))
        self.asm_coder_input.grid(row=0, column=0, sticky="nsew")

        # Panel derecho — Vista del script en memoria
        right = ttk.LabelFrame(work, text="📄  Script Ensamblado (Memoria)", padding=5)
        right.grid(row=0, column=1, padx=(4,0), sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        view_hdr = ttk.Frame(right)
        view_hdr.grid(row=0, column=0, sticky="ew")
        view_hdr.columnconfigure(0, weight=1)
        self.asm_edit_toggle = tk.BooleanVar(value=False)
        ttk.Checkbutton(view_hdr, text="✏️ Edición manual",
                        variable=self.asm_edit_toggle,
                        command=self._asm_toggle_edit).grid(row=0, column=0, sticky="w")
        self.asm_lines_lbl = ttk.Label(view_hdr, text="", foreground="#888", font=("Segoe UI", 9))
        self.asm_lines_lbl.grid(row=0, column=1, sticky="e", padx=8)
        
        # Botones de acción en la vista (Refrescar y Copiar Código)
        ttk.Button(view_hdr, text="🔄", command=self._asm_reload_from_disk).grid(row=0, column=2)
        ttk.Button(view_hdr, text="📋 Código", command=self._asm_copy_code).grid(row=0, column=3, padx=(5,0))

        self.asm_view = scrolledtext.ScrolledText(
            right, bg="#1a1a1a", fg="#a0a0a0",
            insertbackground="white", font=("Consolas", 9), state="disabled")
        self.asm_view.grid(row=1, column=0, sticky="nsew")
        self.asm_view.tag_configure("anchor_hl", background="#854d0e", foreground="#fef3c7")
        self.asm_view.tag_configure("changed", background="#4b1818", foreground="#ffcdd2") 

        # Fila 3: Botones
        btn_main = ttk.Frame(tab, padding=(10,6))
        btn_main.grid(row=3, column=0, sticky="ew")
        btn_main.columnconfigure(0, weight=3)
        btn_main.columnconfigure((1,2,3,4), weight=1)

        self.asm_run_btn = ttk.Button(
            btn_main,
            text="🚀  ENSAMBLAR + EJECUTAR",
            style="Big.TButton",
            command=self._asm_run_full_auto)
        self.asm_run_btn.grid(row=0, column=0, padx=(0,6), sticky="ew")
        
        ttk.Button(btn_main, text="↩ Deshacer",
                   command=self._asm_undo).grid(row=0, column=1, padx=3, sticky="ew")
        ttk.Button(btn_main, text="🗑 Limpiar",
                   command=self._asm_clear_inputs).grid(row=0, column=2, padx=3, sticky="ew")
        ttk.Button(btn_main, text="💣 Resetear", command=self._asm_reset_hard).grid(row=0, column=3, padx=3, sticky="ew")
        ttk.Button(btn_main, text="❓ Anclas", command=self._show_anchors_help).grid(row=0, column=4, padx=3, sticky="ew")

        # Fila 4: Panel de output
        out_frame = ttk.LabelFrame(tab, text="📊  Output de Validación", padding=8)
        out_frame.grid(row=4, column=0, padx=10, pady=(4,4), sticky="ew")
        out_frame.columnconfigure(0, weight=1)
        self.asm_output = scrolledtext.ScrolledText(
            out_frame, height=8, bg="#0d1117", fg="#c9d1d9",
            insertbackground="white", font=("Consolas", 9),
            relief="flat", state="disabled")
        self.asm_output.grid(row=0, column=0, sticky="ew")
        self.asm_syntax_lbl = ttk.Label(out_frame, text="", font=("Segoe UI", 9))
        self.asm_syntax_lbl.grid(row=1, column=0, sticky="w", pady=(4,0))

        # Fila 5: Decisión final
        dec = ttk.Frame(tab, padding=(10,4))
        dec.grid(row=5, column=0, sticky="ew", pady=(0,8))
        dec.columnconfigure((0,1,2), weight=1)
        
        self.asm_approve_btn = ttk.Button(
            dec, text="✅  APROBAR — guardar", style="BigGreen.TButton", command=self._asm_approve)
        self.asm_approve_btn.grid(row=0, column=0, padx=6, sticky="ew")
        
        ttk.Button(dec, text="❌  RECHAZAR — restaurar", style="Red.TButton", command=self._asm_reject).grid(row=0, column=1, padx=6, sticky="ew")
        ttk.Button(dec, text="📋  Copiar resultado", command=self._asm_copy_summary).grid(row=0, column=2, padx=6, sticky="ew")
    
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
                line, _ = PlannerOutputParser.resolve_anchor(self.asm_original_content, ancla)
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
        """Limpia solo los campos de entrada, manteniendo el script visible."""
        self.asm_input.delete('1.0', tk.END)
        self.asm_coder_input.delete('1.0', tk.END)
        self._asm_output_clear()
        self.asm_task_id.set("")
        self._parsed = {}
        self.asm_syntax_lbl.config(text="")
        self.asm_parsed_lbl.config(text="", foreground="#888")
        self.asm_status_lbl.config(text="⬇  Listo para siguiente tarea", foreground="#60a5fa")

    def _asm_run_full_auto(self):
        # Limpiar registro de líneas reemplazadas
        self.asm_replaced_lines = set()
        
        # 1. Inputs
        raw_planner = self.asm_input.get('1.0', 'end-1c').strip()
        raw_coder = self.asm_coder_input.get('1.0', 'end-1c').strip()

        if not raw_planner:
            messagebox.showwarning("Sin input", "Pega el output del Planificador.")
            return

        # 2. Parseo
        parsed = PlannerOutputParser.parse(raw_planner)
        self._parsed = parsed

        if parsed["errores"]:
            err_txt = "\n".join(f"  • {e}" for e in parsed["errores"])
            messagebox.showerror("Output incompleto", f"Faltan datos:\n\n{err_txt}")
            return

        bloque = raw_coder
        if not bloque and not parsed["imports_nuevos"]:
            messagebox.showerror("Sin acción", "No hay código ni imports.")
            return
        if not bloque: bloque = ""

        # ═══════════════════════════════════════════════════════════════════
        # CASO ESPECIAL: ARCHIVO_NUEVO
        # ═══════════════════════════════════════════════════════════════════
        
        if parsed["ancla_raw"] == "ARCHIVO_NUEVO":
            # Crear archivo nuevo directamente
            script_path = None
            root_dir = self.get_source_root()
            requested_script = parsed["script"]
            
            try:
                # Construir ruta completa
                script_path = root_dir / requested_script
                # Crear directorios padres si no existen
                script_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"No pude crear ruta: {requested_script}\n\n{e}")
                return
            
            # Limpiar markdown del código
            bloque = re.sub(r'^```python\s*\n?', '', bloque, flags=re.IGNORECASE)
            bloque = re.sub(r'\n?```\s*$', '', bloque)
            bloque = bloque.strip()
            
            # Construir contenido con imports
            final_content = ""
            
            # (El Codificador ya incluye imports en el código)
            
            # Añadir código del codificador
            final_content += bloque + "\n"
            
            # Guardar en memoria para vista
            self.asm_original_content = final_content
            self.asm_baseline_content = ""
            self.asm_file_path.set(str(script_path))
            
            # Mostrar en vista
            self._asm_set_view(final_content)
            self.asm_view.config(state="disabled")
            
            # Validar sintaxis
            syntax_ok, syntax_msg = self._validate_python_syntax(final_content, str(script_path))
            self.asm_syntax_lbl.config(text=syntax_msg, foreground="#4ade80" if syntax_ok else "#f87171")
            
            if syntax_ok:
                self.asm_status_lbl.config(
                    text=f"✅ Archivo nuevo listo: {requested_script} — APROBAR para guardar",
                    foreground="#4ade80"
                )
            else:
                self.asm_status_lbl.config(text="❌ Error de sintaxis", foreground="#f87171")
            
            self.asm_parsed_lbl.config(
                text=f"📄 ARCHIVO_NUEVO: {requested_script}",
                foreground="#60a5fa"
            )
            return

        # Limpieza de markdown
        bloque = re.sub(r'^```python\s*\n?', '', bloque, flags=re.IGNORECASE)
        bloque = re.sub(r'\n?```\s*$', '', bloque)
        bloque = bloque.strip()

        # ── FIX: APLICAR INDENTACIÓN DEL PLANIFICADOR ──
        indent_match = re.search(r'#\s*INDENTACIÓN\s*:\s*(\d+)', raw_planner, re.IGNORECASE)
        target_indent = int(indent_match.group(1)) if indent_match else 0
        
        if bloque:
            code_lines = bloque.split('\n')
            
            # 1. Encontrar la línea con 'def' o 'class' como referencia
            def_line_idx = -1
            def_indent = 0
            for i, line in enumerate(code_lines):
                stripped = line.strip()
                if stripped.startswith('def ') or stripped.startswith('class ') or stripped.startswith('async def '):
                    def_line_idx = i
                    def_indent = len(line) - len(line.lstrip())
                    break
            
            if def_line_idx >= 0:
                # 2. Detectar indentación del cuerpo (primera línea después de def)
                body_indent = 0
                for i in range(def_line_idx + 1, len(code_lines)):
                    line = code_lines[i]
                    if line.strip():
                        body_indent = len(line) - len(line.lstrip())
                        break
                
                # 3. Calcular indentación relativa esperada (Python estándar = 4)
                # Si el cuerpo tiene 8, 12, 16... el Codificador duplicó/triplicó
                expected_relative = 4
                actual_relative = body_indent - def_indent
                
                if actual_relative > expected_relative and actual_relative % expected_relative == 0:
                    # El Codificador duplicó la indentación
                    factor = actual_relative // expected_relative
                else:
                    factor = 1
                
                # 4. Normalizar y aplicar target_indent
                normalized = []
                for line in code_lines:
                    if line.strip():
                        current_indent = len(line) - len(line.lstrip())
                        relative_indent = current_indent - def_indent
                        if relative_indent < 0:
                            relative_indent = 0
                        # Corregir duplicación
                        corrected_relative = relative_indent // factor
                        content = line.lstrip()
                        new_indent = target_indent + corrected_relative
                        normalized.append(" " * new_indent + content)
                    else:
                        normalized.append("")
                
                bloque = "\n".join(normalized)
            elif target_indent > 0:
                # No hay def/class, aplicar indentación simple
                normalized = []
                for line in code_lines:
                    if line.strip():
                        content = line.lstrip()
                        normalized.append(" " * target_indent + content)
                    else:
                        normalized.append("")
                bloque = "\n".join(normalized)

        # 3. ACUMULACIÓN: Cargar Script
        working = self.asm_original_content
        script_path = None
        
        # Verificar si el script solicitado coincide con el archivo en memoria
        requested_script = parsed["script"]
        
        if working:
            current_script = self.asm_file_path.get()
            if current_script:
                current_rel = Path(current_script).name
                requested_rel = Path(requested_script).name
                if current_rel != requested_rel:
                    # Script diferente - limpiar memoria y cargar nuevo
                    working = ""
                    self.asm_original_content = ""
                    self.asm_baseline_content = ""
        
        if not working:
            try:
                root_dir = self.get_source_root()
                script_path = self.find_file(root_dir, requested_script)
                working = script_path.read_text(encoding="utf-8")
                if not self.asm_baseline_content:
                    self.asm_baseline_content = working
            except Exception as e:
                messagebox.showerror("Error", f"No encuentro script: {requested_script}\n\n{e}")
                return
        else:
            try:
                root_dir = self.get_source_root()
                script_path = self.find_file(root_dir, requested_script)
            except:
                pass

        if script_path: self.asm_file_path.set(str(script_path))
        self.asm_task_id.set(parsed["tarea_id"])
        
        self.asm_undo_stack.append(working)

        # 4. Imports (el Codificador los incluye en el código)
        self._asm_output_clear()

        # 5. Ancla AST y detección de REEMPLAZO
        anchor_raw = parsed["ancla_raw"]
        line_num, _ = PlannerOutputParser.resolve_anchor(working, anchor_raw)

        is_replace = anchor_raw.startswith("REEMPLAZAR_FUNCION:")
        replace_start = 0
        replace_end = 0
        
        if is_replace:
            func_name = anchor_raw.split(":")[1].strip()
            try:
                tree = ast.parse(working)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == func_name:
                        replace_start = node.lineno
                        replace_end = node.end_lineno
                        break
            except Exception as e:
                messagebox.showerror("Error AST", f"No pude encontrar función '{func_name}': {e}")
                return
            
            if replace_start == 0:
                messagebox.showerror("Función no encontrada", f"No existe la función: {func_name}")
                return
            
            line_num = replace_start

        if line_num == 0:
            if anchor_raw == "INICIO_ARCHIVO": 
                line_num = 1
            elif anchor_raw == "FIN_ARCHIVO": 
                line_num = len(working.split('\n'))
            elif anchor_raw.startswith("ANTES_FUNCION:"):
                line_num = 0
            else:
                messagebox.showerror("Ancla no encontrada", f"No pude resolver: {anchor_raw}")
                return

        # 6. Inserción o REEMPLAZO
        lines = working.split('\n')
        
        if anchor_raw == "FIN_ARCHIVO":
            insert_index = len(lines)
        elif is_replace:
            # REEMPLAZO: eliminar función antigua
            insert_index = replace_start - 1
            
            # Registrar líneas que serán reemplazadas (para marcar en rojo)
            for i in range(replace_start, replace_end + 1):
                self.asm_replaced_lines.add(i)
            
            # Eliminar la función antigua
            del lines[replace_start - 1:replace_end]
        else:
            insert_index = line_num

        new_lines = bloque.split('\n') if bloque else []
        
        # Filtrar basura visual
        clean_lines = []
        started = False
        for l in new_lines:
            if l.strip().startswith("# ── TAREA"):
                continue
            if not started and not l.strip():
                continue
            started = True
            clean_lines.append(l)
        
        lineas_reales = [l for l in clean_lines if l.strip() and not l.strip().startswith("#") and l.strip() != "pass"]
        
        if lineas_reales or is_replace:
            # Línea en blanco por ENCIMA (solo si NO es reemplazo)
            if not is_replace:
                needs_gap_above = True
                if insert_index > 0:
                    prev_line = lines[insert_index - 1].strip() if insert_index > 0 else ""
                    if not prev_line:
                        needs_gap_above = False
                
                if needs_gap_above:
                    clean_lines.insert(0, "")

            # Línea en blanco por DEBAJO (para ANTES_FUNCION)
            needs_gap_below = False
            if anchor_raw.startswith("ANTES_FUNCION:"):
                next_line_idx = insert_index
                if next_line_idx < len(lines):
                    next_line = lines[next_line_idx].strip()
                    if next_line:
                        needs_gap_below = True
            
            if needs_gap_below:
                clean_lines.append("")

            lines[insert_index:insert_index] = clean_lines
            working = "\n".join(lines)
        else:
            working = "\n".join(lines)

        # Actualizar memoria
        self.asm_original_content = working
        
        # Actualizar Vista
        self._asm_set_view(working)
        self.asm_view.config(state="disabled")

        # 7. Validar y Ejecutar
        syntax_ok, syntax_msg = self._validate_python_syntax(working, str(script_path) if script_path else "memory")
        self.asm_syntax_lbl.config(text=syntax_msg, foreground="#4ade80" if syntax_ok else "#f87171")

        if not syntax_ok:
            self.asm_status_lbl.config(text="❌ Error de sintaxis", foreground="#f87171")
            return

        self.asm_status_lbl.config(text=f"⏳ Ejecutando...", foreground="#fbbf24")
        self.root.update_idletasks()
        
        def run():
            try:
                res = subprocess.run(["python", "-c", working], capture_output=True, text=True, timeout=60)
                self.root.after(0, lambda: self._asm_finish(res.stdout, res.stderr, res.returncode, script_path, parsed))
            except Exception as ex:
                self.root.after(0, lambda: self._asm_finish("", str(ex), 1, script_path, parsed))
        
        threading.Thread(target=run, daemon=True).start()

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
        content = self.asm_view.get('1.0', 'end-1c')
        path = self.asm_file_path.get()

        if not path or not content.strip():
            messagebox.showwarning("Sin datos", "Ejecuta primero el flujo.")
            return

        if not messagebox.askyesno("Confirmar", f"¿Guardar cambios en:\n{path}?"): return

        try:
            self.asm_backup_path = self._asm_make_backup()
            Path(path).write_text(content, encoding="utf-8")
            self.asm_baseline_content = content
            self._asm_set_view(content) 
            self.asm_status_lbl.config(text=f"✅ GUARDADO — {Path(path).name}", foreground="#4ade80")
            self._asm_clear_inputs()
            
            msg = f"Archivo guardado.\nLíneas: {content.count(chr(10))+1}"
            if self.asm_backup_path:
                msg += f"\nBackup: {self.asm_backup_path.name}"
            
            messagebox.showinfo("Aprobado", msg)
        except Exception as e:
            messagebox.showerror("Error al guardar", str(e))
    
    def _asm_reject(self):
        # Revertir al baseline
        if self.asm_baseline_content:
            self.asm_original_content = self.asm_baseline_content
            self._asm_set_view(self.asm_baseline_content)
            self.asm_view.config(state="disabled")
            
            self.asm_status_lbl.config(text="❌ RECHAZADO — cambios descartados", foreground="#f87171")
            
            # Limpiar inputs
            self._asm_clear_inputs()
        else:
            self._asm_clear_inputs() # Si no hay baseline, al menos limpiar inputs
  
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
        prev = self.asm_undo_stack.pop()
        self.asm_original_content = prev
        # Nota: El undo no cambia el baseline, por eso se verá rojo si es diferente
        self._asm_set_view(prev)
        self.asm_view.config(state="disabled")
        self.asm_status_lbl.config(text="↩ Deshecho", foreground="#fbbf24")

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

    def _asm_make_backup(self) -> Path | None:
        path = self.asm_file_path.get()
        if not path: return None
        p = Path(path)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = p.parent / f"{p.stem}_backup_{ts}{p.suffix}"
        try:
            shutil.copy2(p, backup)
            return backup
        except: return None

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
            self.root.update() # Mantener en portapapeles
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

# Bloque de inicio
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()