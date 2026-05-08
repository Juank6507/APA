# tools/ensamblador_gui.py — Ensamblador Atómico APA (v3.1)

import ast
import json
import re
import os
import shutil
import subprocess
import tkinter as tk
import difflib

from tkinter import scrolledtext, messagebox, filedialog, ttk
from pathlib import Path
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apa.core.assembler import Assembler, AssemblyResult, PlannerOutputParser

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
# Aplicación principal
# ─────────────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        root.title("APA — Ensamblador Atómico v3.1")
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

        self.tab_assembler = ttk.Frame(nb)
        nb.add(self.tab_assembler, text="🧩 Ensamblador")
        self._setup_assembler_tab()

        self.tab_plan = ttk.Frame(nb)
        nb.add(self.tab_plan, text="📋 Plan de Mejoras")
        self._setup_plan_tab()

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
            'o': self._on_browse_key_o, 'O': self._on_browse_key_o,
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

    def _on_browse_key_o(self, e):
        if not self._focused_is_input():
            self.browse_project_root(); return "break"

    def handle_ctrl_enter(self, e):
        t = self.notebook.tab(self.notebook.select(), "text")
        if "Plan" in t: self.toggle_add_mode()

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
    # Tab 2 — Plan de Mejoras
    # ─────────────────────────────────────────────────────────────────────────

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
    # Tab 1 — Ensamblador
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

    def _asm_run_full_auto(self):
            raw_planner = self.asm_input.get("1.0", "end-1c").strip()
            raw_coder = self.asm_coder_input.get("1.0", "end-1c").strip()
            
            if not raw_planner:
                messagebox.showwarning("Advertencia", "El bloque del planificador esta vacio.")
                return

            # Parsear para obtener script y tarea_id
            parsed = PlannerOutputParser.parse(raw_planner)
            if parsed.get("errores"):
                messagebox.showerror("Error de parseo", "\n".join(parsed["errores"]))
                return

            # Resolver archivo target
            root_dir = self.get_source_root()
            script_name = parsed.get("script", "")
            
            try:
                found_path = self.find_file(root_dir, script_name)
                script_path = Path(found_path)
            except Exception:
                blocks_data = PlannerOutputParser._parse_blocks(raw_planner)
                if blocks_data and blocks_data[0].get("anchor") == "ARCHIVO_NUEVO":
                    script_path = root_dir / script_name
                    script_path.parent.mkdir(parents=True, exist_ok=True)
                    script_path.write_text("", encoding="utf-8")
                else:
                    messagebox.showerror("Error", "Archivo " + script_name + " no encontrado.")
                    return

            self.asm_file_path.set(str(script_path))

            # Obtener contenido actual
            if self.asm_original_content:
                original_content = self.asm_original_content
            else:
                original_content = ""
                if script_path.exists():
                    original_content = script_path.read_text(encoding="utf-8")
            
            # Guardar estado ANTES de cualquier modificación para undo
            pre_modification_content = original_content

            # ── PRE-CHECK: Validación existente ──────────────────────────
            validation_mode = "new"
            task_id_val = parsed.get("tarea_id", "")
            
            if task_id_val and "if __name__" in original_content:
                lines_orig = original_content.split("\n")
                pattern = re.compile(r'#\s*===\s*VALIDACIÓN\s+TAREA:\s*' + re.escape(task_id_val) + r'\s*===')
                marker_line = -1
                for i, line in enumerate(lines_orig):
                    if pattern.search(line):
                        marker_line = i
                        break
                
                if marker_line >= 0:
                    respuesta = messagebox.askyesno(
                        "Validación existente",
                        "Ya existe validación para " + task_id_val + "\n\n" +
                        "• SÍ = Sobrescribir (reemplazar existente)\n" +
                        "• NO = Implementar (agregar después de existente)"
                    )
                    if respuesta:
                        validation_mode = "overwrite"
                        # Eliminar validación existente del contenido
                        end_val_line = len(lines_orig)
                        next_marker = re.compile(r'#\s*===\s*VALIDACIÓN\s+TAREA:')
                        for i in range(marker_line + 1, len(lines_orig)):
                            if next_marker.search(lines_orig[i]):
                                end_val_line = i
                                break
                        lines_new = lines_orig[:marker_line] + lines_orig[end_val_line:]
                        original_content = "\n".join(lines_new)
                    else:
                        validation_mode = "implement"

            # ── PRE-CHECK: Estructuras duplicadas ────────────────────────
            duplicate_decisions = {}  # {(type, name): action} — decisión por estructura
            
            blocks_data = PlannerOutputParser._parse_blocks(raw_planner)
            existing_structures = self.assembler.detect_existing_structures(original_content)
            
            # Asociar código del codificador para verificar duplicados
            coder_code = raw_coder.strip() if raw_coder.strip() else ""
            coder_code = re.sub(r"^```python\s*\n?", "", coder_code, flags=re.IGNORECASE)
            coder_code = re.sub(r"\n?```\s*$", "", coder_code)
            script_name_only = Path(script_name).name
            code_lines = coder_code.split("\n")
            cleaned_lines = []
            for line in code_lines:
                stripped = line.strip()
                if stripped in ("#" + script_name, "# " + script_name, "#" + script_name_only, "# " + script_name_only):
                    continue
                if re.match(r"^#\s*\w+[/\\]?\w*\.py$", stripped):
                    continue
                cleaned_lines.append(line)
            coder_code_clean = "\n".join(cleaned_lines).strip()
            
            # Separar main_code para detectar estructuras
            main_code_for_check = []
            in_main = False
            for line in coder_code_clean.split("\n"):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    continue
                if "if __name__" in line and "__main__" in line:
                    in_main = True
                    continue
                if not in_main:
                    main_code_for_check.append(line)
            
            # Verificar duplicados en cada bloque
            if blocks_data and existing_structures:
                # Primero asignar código a bloques para multitarea
                is_multitarea = len(blocks_data) > 1
                if is_multitarea:
                    code_structures = PlannerOutputParser._split_code_by_structure("\n".join(main_code_for_check))
                    blocks_data = PlannerOutputParser._associate_code_to_planner_blocks(blocks_data, code_structures, existing_structures)
                    code_structures = PlannerOutputParser._split_code_by_structure("\n".join(main_code_for_check))
                    blocks_data = PlannerOutputParser._associate_code_to_planner_blocks(blocks_data, code_structures)
                else:
                    if blocks_data and not blocks_data[0].get("code", "").strip() and main_code_for_check:
                        blocks_data[0]["code"] = "\n".join(main_code_for_check).strip()
                
                # Recopilar TODAS las estructuras duplicadas de todos los bloques
                all_duplicates = set()
                for bd in blocks_data:
                    code_content = bd.get("code", "")
                    if not code_content.strip():
                        continue
                    block_dups = self.assembler.detect_block_duplicates(code_content, existing_structures)
                    all_duplicates |= block_dups
                
                # Preguntar por cada estructura duplicada individualmente
                for dup_type, dup_name in all_duplicates:
                    if (dup_type, dup_name) in duplicate_decisions:
                        continue  # Ya se preguntó por esta estructura
                    
                    has_class_dup = dup_type == "class"
                    dup_label = "clase" if dup_type == "class" else "funcion"
                    
                    dlg = DuplicateStructureDialog(
                        self.root,
                        "Estructura duplicada: " + dup_label + " " + dup_name,
                        "La " + dup_label + " '" + dup_name + "' ya existe en el archivo.\n\n" +
                        "¿Qué desea hacer con esta " + dup_label + "?",
                        has_class=has_class_dup
                    )
                    answer = dlg.result
                    
                    if answer == 'cancel':
                        return
                    elif answer == 'discard':
                        duplicate_decisions[(dup_type, dup_name)] = "discard"
                    elif answer == 'modify':
                        duplicate_decisions[(dup_type, dup_name)] = "modify"
                    else:
                        duplicate_decisions[(dup_type, dup_name)] = "replace"
            
            # ── DELEGAR AL MOTOR ASSEMBLER ───────────────────────────────
            result = self.assembler.run_full(
                planner_text=raw_planner,
                coder_text=raw_coder,
                original_content=original_content,
                script_name=script_name,
                duplicate_action=duplicate_decisions.get(next(iter(duplicate_decisions)), "replace") if duplicate_decisions else "replace",
                duplicate_decisions=duplicate_decisions if duplicate_decisions else None,
                validation_override=validation_mode
            )
            
            self._parsed = result.parsed
            
            # Guardar estado en pila undo
            current_state = {
                "content": pre_modification_content,
                "planner": self.asm_input.get("1.0", "end-1c"),
                "coder": self.asm_coder_input.get("1.0", "end-1c")
            }
            self.asm_undo_stack.append(current_state)
            self.asm_redo_stack.clear()
            
            # Mostrar resultado
            assembled_content = result.assembled_content
            self.asm_original_content = assembled_content
            # Fondo rojo: baseline debe ser el contenido ANTES del ensamblaje
            # para que _asm_highlight_changes() detecte solo las líneas nuevas/cambiadas
            self.asm_baseline_content = original_content
            self._asm_set_view(assembled_content)
            # Actualizar baseline para la próxima comparación
            self.asm_baseline_content = assembled_content
            self._asm_output_clear()
            self._asm_output_append(result.validation_result.get("output", ""))
            
            # Log del motor
            for log_msg in result.log:
                print("[ENSAMBLADOR] " + log_msg)

            if result.success:
                self.asm_input.delete("1.0", tk.END)
                self.asm_coder_input.delete("1.0", tk.END)
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

    def _asm_finish(self, stdout, stderr, rc, script_path, parsed):
        out = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}\nReturncode: {rc}\n" if (stdout or stderr) else "(sin output)\n"
        self._asm_output_append(out)
        
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