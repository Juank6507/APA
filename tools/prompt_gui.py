# tools/prompt_gui.py — Procesador de prompts genérico (búsqueda flexible de archivos)

import json
import re
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, ttk
from pathlib import Path
from datetime import datetime

try:
    from fpdf import FPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

class ToolTip:
    """Clase para crear tooltips personalizados."""
    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip = None
        self.after_id = None
        widget.bind("<Enter>", self.schedule, "+")
        widget.bind("<Leave>", self.hide, "+")
        widget.bind("<ButtonPress>", self.hide, "+")

    def schedule(self, event=None):
        self.hide()
        self.after_id = self.widget.after(self.delay, self.show)

    def hide(self, event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def show(self, event=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip, text=self.text, background="#ffffe0",
                         foreground="#000000", font=("Segoe UI", 9), padx=8, pady=4,
                         relief="solid", borderwidth=1)
        label.pack()

class App:
    def __init__(self, root):
        self.root = root
        root.title("APA — Prompt Processor")
        self._setup_dark_theme()
        w, h = 950, 750
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(800, 600)
        self.current_file_name = None
        self.project_root = tk.StringVar()
        self.plan_path = None
        self.add_text = None
        self.add_btn = None
        self.add_mode = False
        self.done_task_id = None
        style = ttk.Style()
        style.configure("TNotebook.Tab", font=('Segoe UI', 11, 'bold'), padding=[20, 8])
        self.notebook = ttk.Notebook(root, style="TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_process = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.tab_process, text="⚡ Procesar Prompt")
        self._setup_process_tab()
        self.tab_plan = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(self.tab_plan, text="📋 Plan de Mejoras")
        self._setup_plan_tab()
        self._setup_keyboard_shortcuts()
        self.project_root.trace_add("write", lambda *args: self.on_project_root_change())
        self.auto_detect_project_root()
        self.refresh_plan_view()

    def _setup_keyboard_shortcuts(self):
        for key in ['a', 'A']:
            self.root.bind(f'<KeyPress-{key}>', self._on_plan_key_a)
        for key in ['g', 'G']:
            self.root.bind(f'<KeyPress-{key}>', self._on_plan_key_g)
        for key in ['m', 'M']:
            self.root.bind(f'<KeyPress-{key}>', self._on_plan_key_m)
        for key in ['r', 'R']:
            self.root.bind(f'<KeyPress-{key}>', self._on_plan_key_r)
        for key in ['e', 'E']:
            self.root.bind(f'<KeyPress-{key}>', self._on_plan_key_e)
        for key in ['p', 'P']:
            self.root.bind(f'<KeyPress-{key}>', self._on_process_key_p)
        for key in ['v', 'V']:
            self.root.bind(f'<KeyPress-{key}>', self._on_process_key_v)
        for key in ['l', 'L']:
            self.root.bind(f'<KeyPress-{key}>', self._on_process_key_l)
        for key in ['o', 'O']:
            self.root.bind(f'<KeyPress-{key}>', self._on_process_key_o)

    def _is_input_focused(self):
        focused = self.root.focus_get()
        return isinstance(focused, (tk.Entry, tk.Text, scrolledtext.ScrolledText, ttk.Entry))

    def _get_active_tab_index(self):
        return self.notebook.index(self.notebook.select())

    def _on_plan_key_a(self, event):
        if self._get_active_tab_index() != 1:
            return
        focused = self.root.focus_get()
        if focused == self.add_text:
            return
        if isinstance(focused, (tk.Entry, ttk.Entry)):
            return "break"
        self.toggle_add_mode()
        return "break"

    def _on_plan_key_g(self, event):
        if self._get_active_tab_index() == 1 and not self._is_input_focused():
            messagebox.showinfo("Guardar", "Función Guardar Cambios")
            return "break"

    def _on_plan_key_m(self, event):
        if self._get_active_tab_index() == 1:
            self.complete_task()
            return "break"

    def _on_plan_key_r(self, event):
        if self._get_active_tab_index() == 1 and not self._is_input_focused():
            self.refresh_plan_view()
            return "break"

    def _on_plan_key_e(self, event):
        if self._get_active_tab_index() == 1 and not self._is_input_focused():
            messagebox.showinfo("Especificar", "Función Generar Especificación")
            return "break"

    def _on_process_key_p(self, event):
        if self._get_active_tab_index() == 0 and not self._is_input_focused():
            self.process()
            return "break"

    def _on_process_key_v(self, event):
        if self._get_active_tab_index() == 0 and not self._is_input_focused():
            self.copy()
            return "break"

    def _on_process_key_l(self, event):
        if self._get_active_tab_index() == 0 and not self._is_input_focused():
            self.clear()
            return "break"

    def _on_process_key_o(self, event):
        if self._get_active_tab_index() == 0 and not self._is_input_focused():
            self.browse_project_root()
            return "break"

    def handle_ctrl_enter(self, event):
        tab_name = self.notebook.tab(self.notebook.select(), "text")
        if tab_name == "⚡ Procesar Prompt":
            self.process()
        elif tab_name == "📋 Plan de Mejoras":
            self.toggle_add_mode()

    def handle_ctrl_n(self, event):
        if self.notebook.tab(self.notebook.select(), "text") == "📋 Plan de Mejoras":
            if self.add_mode and self.add_text:
                self.add_text.focus_set()

    def handle_ctrl_shift_c(self, event):
        if self.notebook.tab(self.notebook.select(), "text") == "📋 Plan de Mejoras":
            self.complete_task()

    def on_project_root_change(self):
        if self.notebook.tab(self.notebook.select(), "text") == "📋 Plan de Mejoras":
            self.auto_detect_project_root()
            self.refresh_plan_view()

    def _setup_dark_theme(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabel", background="#1e1e1e", foreground="#d4d4d4", font=('Segoe UI', 10))
        style.configure("Header.TLabel", font=('Segoe UI', 12, 'bold'), foreground="#3b82f6")
        style.configure("TButton", background="#3b82f6", foreground="#ffffff", font=('Segoe UI', 10, 'bold'), borderwidth=0, focuscolor='none', padding=8)
        style.map("TButton", background=[('active', '#2563eb'), ('pressed', '#1d4ed8')])
        style.configure("TEntry", fieldbackground="#2d2d2d", foreground="#d4d4d4", insertcolor="#ffffff", padding=5)
        style.configure("TLabelframe", background="#1e1e1e", foreground="#3b82f6")
        style.configure("TLabelframe.Label", background="#1e1e1e", foreground="#3b82f6", font=('Segoe UI', 10, 'bold'))
        style.configure("TNotebook", background="#1e1e1e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2d2d2d", foreground="#d4d4d4")
        style.map("TNotebook.Tab", background=[("selected", "#3b82f6")], foreground=[("selected", "#ffffff")])
        self.root.configure(bg="#1e1e1e")

    def _setup_process_tab(self):
        tab = self.tab_process
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=2)
        tab.rowconfigure(3, weight=2)
        cfg = ttk.LabelFrame(tab, text="📁 Configuración del proyecto", padding=10)
        cfg.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        cfg.columnconfigure(1, weight=1)
        ttk.Label(cfg, text="Ruta raíz:").grid(row=0, column=0, sticky="w", padx=5)
        entry = ttk.Entry(cfg, textvariable=self.project_root)
        entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        entry.bind("<Return>", lambda e: self.update_project_root())
        ToolTip(entry, "Directorio raíz del proyecto.")
        ttk.Button(cfg, text="📂 Examinar", command=self.browse_project_root).grid(row=0, column=2, padx=5)
        ToolTip(cfg.winfo_children()[-1], "Seleccionar carpeta raíz")
        inp = ttk.LabelFrame(tab, text="📝 Prompt Base", padding=10)
        inp.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        inp.columnconfigure(0, weight=1)
        inp.rowconfigure(0, weight=1)
        self.input_text = scrolledtext.ScrolledText(inp, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4",
            insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.input_text.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.input_text, "Escribe tu prompt aquí. Usa [INCRUSTAR: archivo.py].")
        btn_process = ttk.Button(tab, text="Procesar Prompt", command=self.process)
        btn_process.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        btn_process.configure(underline=0)
        ToolTip(btn_process, "Ejecuta el procesamiento del prompt (tecla: P)")
        out = ttk.LabelFrame(tab, text="✨ Prompt Procesado", padding=10)
        out.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)
        self.output_text = scrolledtext.ScrolledText(out, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4",
            insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.output_text.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.output_text, "Resultado listo para copiar.")
        act = ttk.Frame(tab, padding=5)
        act.grid(row=4, column=0, padx=10, pady=(5, 10), sticky="ew")
        act.columnconfigure((0, 1, 2), weight=1)
        b_copy = ttk.Button(act, text="Copiar", command=self.copy)
        b_copy.grid(row=0, column=0, padx=5)
        b_copy.configure(underline=0)
        ToolTip(b_copy, "Copiar al portapapeles (tecla: V)")
        b_pdf = ttk.Button(act, text="PDF", command=self.pdf)
        b_pdf.grid(row=0, column=1, padx=5)
        ToolTip(b_pdf, "Exportar a PDF")
        b_clear = ttk.Button(act, text="Limpiar", command=self.clear)
        b_clear.grid(row=0, column=2, padx=5)
        b_clear.configure(underline=0)
        ToolTip(b_clear, "Limpiar campos de texto (tecla: L)")

    def toggle_add_mode(self):
        if not self.add_mode:
            self.add_btn.configure(text="Aceptar")
            self.add_text.config(state='normal')
            self.add_text.delete('1.0', tk.END)
            self.add_text.focus_set()
            self.add_mode = True
        else:
            self.save_added_task()

    def _find_block_insert_position(self, lines: list, block: str) -> int:
        """Encuentra la posición de inserción para una nueva tarea en un bloque.
        Retorna el índice de línea donde insertar, o -1 si el bloque no existe."""
        pat_bloque = re.compile(rf'^##\s+Bloque\s+{re.escape(block)}\b', re.IGNORECASE)
        pat_tarea = re.compile(r'^###\s+[A-Z]+\d+\s*[–\-—]')
        pat_siguiente_bloque = re.compile(r'^##\s+Bloque\s+', re.IGNORECASE)
        
        bloque_encontrado = False
        last_task_idx = -1
        
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if pat_bloque.match(stripped):
                bloque_encontrado = True
                last_task_idx = idx  # Posición justo después del título del bloque
                continue
            if bloque_encontrado:
                if pat_siguiente_bloque.match(stripped):
                    # Llegó al siguiente bloque, insertar antes
                    return idx
                if pat_tarea.match(stripped):
                    # Actualizar última tarea encontrada en este bloque
                    last_task_idx = idx
        if bloque_encontrado:
            # Insertar al final del bloque (última línea del archivo o antes de siguiente bloque)
            return last_task_idx + 1 if last_task_idx >= 0 else -1
        return -1

    # FORMATO ESPERADO AL AÑADIR TAREAS:
    # El usuario debe incluir en el campo **Prioridad:** el sufijo "/ Pendiente".
    # Ejemplo: "Alta / Pendiente". El sistema NO modifica automáticamente este valor.
    def save_added_task(self):
        content = self.add_text.get('1.0', 'end-1c').strip()
        if not content:
            self.add_text.config(state='disabled')
            self.add_btn.configure(text="Añadir Tarea")
            self.add_mode = False
            return
        plan_path = self.get_plan_path()
        try:
            if not plan_path.exists():
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text("", encoding="utf-8")
            
            # Parsear el ID de la nueva tarea para determinar su bloque
            task_id = None
            pat_task_id = re.compile(r'^###\s+([A-Z]+\d+)\s*[–\-—]')
            for line in content.split('\n'):
                match = pat_task_id.match(line.strip())
                if match:
                    task_id = match.group(1)
                    break
            
            current = plan_path.read_text(encoding="utf-8")
            lines = current.split('\n')
            
            if task_id:
                # Extraer bloque del ID (ej. "V7" → "V")
                block_match = re.match(r'^([A-Z]+)', task_id)
                if block_match:
                    block = block_match.group(1)
                    insert_pos = self._find_block_insert_position(lines, block)
                    if insert_pos >= 0:
                        # Insertar la tarea en la posición correcta
                        # Asegurar línea en blanco antes si no es justo después del título del bloque
                        if insert_pos > 0 and lines[insert_pos - 1].strip() and not lines[insert_pos - 1].strip().startswith("##"):
                            lines.insert(insert_pos, "")
                            insert_pos += 1
                        for task_line in content.split('\n'):
                            lines.insert(insert_pos, task_line)
                            insert_pos += 1
                        lines.insert(insert_pos, "")  # Línea en blanco después
                        new_content = '\n'.join(lines)
                        plan_path.write_text(new_content, encoding="utf-8")
                        self.refresh_plan_view()
                        self.add_text.config(state='disabled')
                        self.add_btn.configure(text="Añadir Tarea")
                        self.add_mode = False
                        messagebox.showinfo("Éxito", f"Tarea {task_id} añadida en Bloque {block}.")
                        return
            
            # Fallback: añadir al final si no se pudo determinar bloque o posición
            with open(plan_path, 'a', encoding="utf-8") as f:
                if current and not current.endswith('\n'):
                    f.write('\n')
                f.write(content + '\n')
            self.refresh_plan_view()
            self.add_text.config(state='disabled')
            self.add_btn.configure(text="Añadir Tarea")
            self.add_mode = False
            messagebox.showinfo("Éxito", "Contenido añadido al plan.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar: {e}")

    def _setup_plan_tab(self):
        tab = self.tab_plan
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=2)
        tab.rowconfigure(2, weight=1)
        pv = ttk.LabelFrame(tab, text="📄 Contenido del Plan", padding=10)
        pv.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        pv.columnconfigure(0, weight=1)
        pv.rowconfigure(0, weight=1)
        self.plan_text = scrolledtext.ScrolledText(pv, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4",
            font=("Consolas", 9), relief="flat", padx=10, pady=10, state="disabled")
        self.plan_text.grid(row=0, column=0, sticky="nsew")
        ToolTip(self.plan_text, "Vista del plan. Se refresca tras cambios.")
        ctrl = ttk.Frame(tab, padding=10)
        ctrl.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        ctrl.columnconfigure((0, 1), weight=1)
        add = ttk.LabelFrame(ctrl, text="➕ Añadir Tarea", padding=10)
        add.grid(row=0, column=0, padx=5, sticky="ew")
        add.columnconfigure(0, weight=1)
        ttk.Label(add, text="Contenido a añadir (puede ser una línea o un bloque completo):").grid(row=0, column=0, sticky="w", pady=(0, 4))
        text_frame = ttk.Frame(add)
        text_frame.grid(row=1, column=0, sticky="ew", pady=4)
        text_frame.columnconfigure(0, weight=1)
        self.add_text = tk.Text(text_frame, height=5, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4",
            insertbackground="white", font=("Consolas", 9), relief="flat", padx=8, pady=8, state='disabled')
        self.add_text.grid(row=0, column=0, sticky="ew")
        ToolTip(self.add_text, "Pega aquí la tarea o bloque. Asegúrate de que la prioridad incluya '/ Pendiente'.")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.add_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.add_text.configure(yscrollcommand=scrollbar.set)
        self.add_btn = ttk.Button(add, text="Añadir Tarea", command=self.toggle_add_mode)
        self.add_btn.grid(row=2, column=0, pady=10, sticky="ew")
        self.add_btn.configure(underline=0)
        ToolTip(self.add_btn, "Habilita edición o guarda el contenido (tecla: A)")
        done = ttk.LabelFrame(ctrl, text="✅ Completar Tarea", padding=10)
        done.grid(row=0, column=1, padx=5, sticky="ew")
        done.columnconfigure(0, weight=1)
        ttk.Label(done, text="ID de tarea (ej. V6):").grid(row=0, column=0, sticky="e", pady=4)
        self.done_task_id = ttk.Entry(done)
        self.done_task_id.grid(row=1, column=0, sticky="ew", padx=5, pady=4)
        ToolTip(self.done_task_id, "Ingrese ID completo: V6, H7, TS1, etc. (tecla M para ejecutar)")
        b_done = ttk.Button(done, text="Marcar Completada", command=self.complete_task)
        b_done.grid(row=2, column=0, pady=10, sticky="ew")
        b_done.configure(underline=0)
        ToolTip(b_done, "Marca tarea como completada (tecla: M)")
        b_ref = ttk.Button(tab, text="Recargar Plan", command=self.refresh_plan_view)
        b_ref.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        b_ref.configure(underline=0)
        ToolTip(b_ref, "Recargar el contenido del archivo (tecla: R)")

    def _find_project_root(self, start_path: Path) -> Path:
        current = start_path.resolve()
        while current != current.parent:
            if (current / "apa").exists() or (current / "docs").exists() or (current / "tools").exists():
                return current
            current = current.parent
        return Path.cwd()

    def find_plan_file_flexible(self, start_dir: Path) -> Path | None:
        exclude_dirs = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', 'build', 'dist'}
        for path in start_dir.rglob("*PLAN*.md"):
            if path.name.lower().endswith('.md') and not any(excl in path.parts for excl in exclude_dirs):
                return path.resolve()
        current = start_dir.resolve()
        while current != current.parent:
            for path in current.rglob("*PLAN*.md"):
                if path.name.lower().endswith('.md') and not any(excl in path.parts for excl in exclude_dirs):
                    return path.resolve()
            current = current.parent
        return None

    def get_plan_path(self) -> Path:
        script_dir = Path(__file__).resolve().parent
        project_root = self._find_project_root(script_dir)
        canonical = project_root / "docs" / "PLAN_MEJORAS_APA.md"
        if canonical.exists():
            return canonical
        found = self.find_plan_file_flexible(project_root)
        if found:
            return found
        return canonical

    def auto_detect_project_root(self):
        self.plan_path = self.get_plan_path()
        self.project_root.set(str(self.get_plan_path().parent.parent if self.plan_path.exists() else Path.cwd()))

    def browse_project_root(self):
        p = filedialog.askdirectory(title="Raíz del proyecto")
        if p:
            self.project_root.set(p)
            self.auto_detect_project_root()
            self.refresh_plan_view()

    def update_project_root(self):
        if not Path(self.project_root.get()).exists():
            messagebox.showwarning("Ruta inválida", "La carpeta no existe.")

    def get_source_root(self):
        r = Path(self.project_root.get().strip())
        if not r or not r.exists():
            raise FileNotFoundError(f"Ruta inválida: {r}")
        return r

    def find_file(self, root_dir: Path, file_ref: str) -> Path:
        if '/' in file_ref or '\\' in file_ref:
            target = root_dir / file_ref
            if target.exists():
                return target
            raise FileNotFoundError(f"No encontrado: {target}")
        matches = list(root_dir.rglob(file_ref))
        if not matches:
            raise FileNotFoundError(f"No hay archivo '{file_ref}' en {root_dir}")
        if len(matches) > 1:
            raise ValueError(f"Múltiples '{file_ref}':\n" + "\n".join(str(x.relative_to(root_dir)) for x in matches))
        return matches[0]

    def normalize_content(self, content: str) -> str:
        normalized = content.replace('\r\n', '\n').replace('\r', '\n')
        lines = normalized.split('\n')
        lines = [line.rstrip() for line in lines]
        return '\n'.join(lines)

    def fingerprint(self, content: str) -> dict:
        normalized = self.normalize_content(content)
        lines = normalized.split('\n')
        return {
            "lines": len(lines),
            "chars": len(normalized),
            "ascii_sum_mod": sum(ord(c) for c in normalized) % 100000,
            "first_three": "\n".join(lines[:3]),
            "last_three": "\n".join(lines[-3:])
        }

    def process_prompt(self, base_prompt: str) -> tuple:
        m = re.search(r'\[INCRUSTAR:\s*([^\]]+)\]', base_prompt)
        if not m:
            return base_prompt + "\n\n⚠️ No se encontró directiva [INCRUSTAR: ...].", None
        ref = m.group(1).strip()
        root = self.get_source_root()
        fp = self.find_file(root, ref)
        raw = fp.read_text(encoding="utf-8")
        cnt = self.normalize_content(raw)
        met = self.fingerprint(raw)
        nm = fp.name
        try:
            rel = fp.relative_to(root)
        except ValueError:
            rel = fp
        exp = f"# {rel.as_posix()}"
        mj = json.dumps(met, indent=2, ensure_ascii=False)
        vb = (
            f"\n## FASE 0 — VERIFICACIÓN AUTOMÁTICA DE INTEGRIDAD DEL ARCHIVO (OBLIGATORIA)\n\n"
            f"Debes verificar **internamente** que el archivo `{nm}` que has recibido está íntegro antes de modificarlo.\n\n"
            f"**Métricas esperadas (calculadas por el director sobre el archivo original con normalización de formato):**\n"
            f"```json\n{mj}\n```\n\n"
            f"### Instrucciones estrictas:\n"
            f"1. Toma el contenido **EXACTO** del archivo tal cual ha llegado a tu contexto.\n"
            f"2. **Normaliza el contenido** antes de calcular métricas:\n"
            f"   - Reemplaza todos los saltos de línea `\\r\\n` o `\\r` por `\\n`.\n"
            f"   - Elimina espacios en blanco al final de cada línea (`.rstrip()`).\n"
            f"3. Calcula sobre el contenido normalizado: líneas (separadas por `\\n`), caracteres totales, suma ASCII mód 100000, primeras 3 líneas, últimas 3 líneas.\n"
            f"4. Compara con los valores esperados.\n\n"
            f"### Decisión automática:\n"
            f"- ✅ Si coinciden, procede directamente a la TAREA EXACTA.\n"
            f"- ❌ Si no coinciden, responde ÚNICAMENTE con el mensaje de error y NO modifiques nada.\n\n"
            f"```\n"
            f"❌ ARCHIVO CORRUPTO EN TRANSMISIÓN.\n"
            f"   Esperado: lines={met['lines']}, chars={met['chars']}, ascii_sum_mod={met['ascii_sum_mod']}\n"
            f"   Recibido: lines=<líneas_reales>, chars=<caracteres_reales>, ascii_sum_mod=<suma_real>\n"
            f"```\n\n"
            f"---\n\n"
            f"## CONTENIDO ÍNTEGRO DEL ARCHIVO (INCRUSTADO Y NORMALIZADO)\n\n"
            f"```python\n{cnt}\n```\n\n"
            f"---\n\n"
            f"## FORMATO DE ENTREGA OBLIGATORIO\n\n"
            f"1. Entrega el archivo `{nm}` completo modificado entre ```python y ```.\n"
            f"2. La primera línea del archivo debe ser: `{exp}`.\n"
            f"3. Incluye el output real del bloque de pruebas (si existe).\n"
            f"---\n"
        )
        mn, mx = max(1, int(met['lines'] * 0.95)), int(met['lines'] * 1.05)
        cb = (
            f"\n---\n\n## 📏 CONTROL DE LÍNEAS EN LA ENTREGA (OBLIGATORIO)\n\n"
            f"Antes de entregar el archivo modificado, DEBES:\n"
            f"1. Contar el número total de líneas del archivo que vas a entregar.\n"
            f"2. Verificar que está dentro del rango permitido: **{mn} – {mx} líneas** (±5% del original).\n"
            f"3. Incluir en tu respuesta, justo antes del bloque ```python, una línea con el formato:\n"
            f"   `📊 LÍNEAS ENTREGADAS: <número> (rango permitido: {mn}-{mx})`\n"
            f"4. Si el número de líneas está fuera del rango, DEBES incluir una sección \"📉 JUSTIFICACIÓN DE REDUCCIÓN\" "
            f"o \"📈 JUSTIFICACIÓN DE AUMENTO\" explicando exactamente qué líneas se modificaron y por qué.\n\n"
            f"**Si no se incluye la declaración de líneas o el número está fuera de rango sin justificación, "
            f"la entrega será RECHAZADA automáticamente.**\n"
        )
        return base_prompt[:m.start()] + vb + cb + base_prompt[m.end():], nm

    def process(self):
        if not self.project_root.get().strip():
            return messagebox.showerror("Error", "Configura la ruta raíz.")
        try:
            self.get_source_root()
        except Exception as e:
            return messagebox.showerror("Error", str(e))
        base = self.input_text.get("1.0", tk.END).strip()
        if not base:
            return messagebox.showwarning("Vacío", "Pega un prompt con [INCRUSTAR: ...]")
        try:
            proc, nm = self.process_prompt(base)
            self.current_file_name = nm
            self.output_text.delete("1.0", tk.END)
            self.output_text.insert("1.0", proc)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def copy(self):
        c = self.output_text.get("1.0", tk.END).strip()
        if c:
            self.root.clipboard_clear()
            self.root.clipboard_append(c)
            self.root.update()
            messagebox.showinfo("Copiado", "Listo")
        else:
            messagebox.showwarning("Vacío", "No hay prompt")

    def pdf(self):
        c = self.output_text.get("1.0", tk.END).strip()
        if not c:
            return messagebox.showwarning("Vacío", "No hay prompt")
        if not PDF_AVAILABLE:
            return messagebox.showerror("Falta fpdf", "pip install fpdf")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dn = f"Prompt_{Path(self.current_file_name).stem if self.current_file_name else 'export'}_{ts}.pdf"
        fp = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=dn, filetypes=[("PDF", "*.pdf")])
        if not fp:
            return
        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Courier", size=10)
            for ln in c.split('\n'):
                pdf.multi_cell(0, 5, ln.encode('latin-1', 'replace').decode('latin-1'))
            pdf.output(fp)
            messagebox.showinfo("PDF", f"Guardado:\n{fp}")
        except Exception as e:
            messagebox.showerror("Error PDF", str(e))

    def clear(self):
        self.input_text.delete("1.0", tk.END)
        self.output_text.delete("1.0", tk.END)
        self.current_file_name = None

    def refresh_plan_view(self):
        """Refresca el contenido del cuadro de texto del plan mostrando el archivo tal cual."""
        if not self.plan_path or not self.plan_path.exists():
            self.plan_text.config(state="normal")
            self.plan_text.delete("1.0", tk.END)
            self.plan_text.insert("1.0", f"⚠️ No encontrado:\n{self.plan_path}")
            self.plan_text.config(state="disabled")
            return
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            self.plan_text.config(state="normal")
            self.plan_text.delete("1.0", tk.END)
            self.plan_text.insert("1.0", content)
            self.plan_text.config(state="disabled")
            self._scroll_to_priority_task(content)
            self._auto_select_and_highlight_after_load(content)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar: {e}")

    def _scroll_to_priority_task(self, content: str):
        """Scroll automático robusto hacia tarea Actual/Próxima/Alta pendiente usando texto."""
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
        """Selecciona y resalta tarea prioritaria usando texto."""
        lines = content.split('\n')
        selected = None
        actual_task_line = None
        for idx, line in enumerate(lines):
            if line.strip().startswith("- [ ]") and "/ Actual" in line:
                match = re.search(r'-\s*\[\s*\]\s*(\w+\d+)\s*[–-]', line)
                if match:
                    task_id = match.group(1)
                    if selected is None:
                        selected = task_id
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
                if line.strip().startswith("- [ ]") and "**Prioridad:** Alta" in line:
                    match = re.search(r'-\s*\[\s*\]\s*(\w+\d+)\s*[–-]', line)
                    if match:
                        selected = match.group(1)
                        break
        if selected:
            self.done_task_id.delete(0, tk.END)
            self.done_task_id.insert(0, selected)
        if actual_task_line is not None:
            self.plan_text.tag_configure("actual_task", background="#3b82f6", foreground="white")
            line_start = f"{actual_task_line + 1}.0"
            line_end = f"{actual_task_line + 1}.end"
            self.plan_text.tag_add("actual_task", line_start, line_end)

    def add_task(self):
        self.toggle_add_mode()

    def parse_task_id(self, task_id: str) -> tuple:
        """Parsea un ID de tarea como 'V6' en (bloque='V', num='6') usando regex."""
        if not task_id:
            return "", ""
        match = re.match(r'^([A-Z]+)(\d+)$', task_id.strip())
        if match:
            return match.group(1), match.group(2)
        return "", ""

    def complete_task(self):
        """Marca una tarea como completada mediante manipulación directa de líneas."""
        # NOTA: El plan usa formato homogéneo con '### ID – descripción' (tres almohadillas).
        # La búsqueda de tareas asume este formato.
        task_id_input = self.done_task_id.get().strip() if self.done_task_id else ""
        if not task_id_input:
            return messagebox.showwarning("Campo vacío", "Ingrese un ID de tarea (ej. V6, H7, TS1).")
        block, num = self.parse_task_id(task_id_input)
        if not block or not num:
            return messagebox.showerror("Formato inválido", "Formato inválido. Use ej. V6, H7, TS1.")
        plan_path = self.get_plan_path()
        if not plan_path.exists():
            return messagebox.showerror("Error", f"Plan no encontrado: {plan_path}")
        try:
            content = plan_path.read_text(encoding="utf-8")
            lines = content.split('\n')
            full_id = f"{block}{num}"
            task_line_idx = -1
            pat_task = re.compile(rf'^###\s+{re.escape(full_id)}\b')
            for idx, line in enumerate(lines):
                if pat_task.match(line.strip()):
                    task_line_idx = idx
                    break
            if task_line_idx < 0:
                return messagebox.showerror("No hallada", f"No se encontró la tarea '{full_id}'.")
            # Extraer descripción para confirmación
            desc_match = re.match(rf'^###\s+{re.escape(full_id)}\s*[–\-—]\s*(.*)', lines[task_line_idx].strip())
            description = desc_match.group(1).strip() if desc_match else "N/A"
            # Verificar estado actual
            is_completed = False
            for k in range(task_line_idx + 1, min(task_line_idx + 15, len(lines))):
                if lines[k].strip().startswith("### "):
                    break
                if "**Estado:**" in lines[k] and "[x]" in lines[k]:
                    is_completed = True
                    break
            if is_completed:
                return messagebox.showinfo("Ya completada", f"La tarea {full_id} ya está marcada como completada.\n\nDescripción: {description}")
            # Confirmación
            confirm_msg = f"¿Marcar como completada la siguiente tarea?\n\nID: {full_id}\nDescripción: {description}"
            if not messagebox.askyesno("Confirmar completar tarea", confirm_msg):
                return
            # Modificar líneas: prioridad y estado
            for k in range(task_line_idx + 1, min(task_line_idx + 15, len(lines))):
                if lines[k].strip().startswith("### "):
                    break
                if "- **Estado:**" in lines[k]:
                    lines[k] = re.sub(r'\[ \]', '[x]', lines[k])
                    if "Completada" not in lines[k]:
                        lines[k] = lines[k].replace("Pendiente", "Completada")
                if "**Prioridad:**" in lines[k]:
                    # CORRECCIÓN: La prioridad completada debe ser "X / Completada" (valor fijo literal)
                    new_priority = "X / Completada"
                    lines[k] = re.sub(r"\*\*Prioridad:\*\*\s*.+?(?:\s*$)", f"**Prioridad:** {new_priority}", lines[k])
            # Guardar archivo
            plan_path.write_text('\n'.join(lines), encoding="utf-8")
            # Refrescar vista
            self.refresh_plan_view()
            # --- Forzar scroll a la tarea recién editada, anulando el scroll automático ---
            line_num = task_line_idx + 1
            def _force_scroll(ln):
                self.plan_text.see(f"{ln}.0")
                self.plan_text.update_idletasks()
                # Ajuste para que la línea quede al inicio del área visible
                bbox = self.plan_text.bbox(f"{ln}.0")
                if bbox:
                    total_bbox = self.plan_text.bbox("end-1c")
                    # CORRECCIÓN: Verificar que total_bbox no sea None antes de acceder
                    if total_bbox and total_bbox[1] > 0:
                        fraction = bbox[1] / total_bbox[1]
                        self.plan_text.yview_moveto(fraction)
            self.plan_text.after(200, lambda ln=line_num: _force_scroll(ln))
            # Limpiar campo
            if self.done_task_id:
                self.done_task_id.delete(0, tk.END)
            messagebox.showinfo("Éxito", f"Tarea {full_id} marcada como completada.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo completar: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()