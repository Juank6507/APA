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

def create_tooltip(widget, text):
    """Crea un tooltip simple para widgets tkinter."""
    tooltip = None
    def on_enter(e):
        nonlocal tooltip
        x, y = widget.winfo_rootx() + 20, widget.winfo_rooty() + widget.winfo_height() + 5
        tooltip = tk.Toplevel(widget)
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(tooltip, text=text, background="#ffffe0", foreground="#000",
                       relief="solid", borderwidth=1, font=("Arial", 9), padx=8, pady=4)
        lbl.pack()
    def on_leave(e):
        nonlocal tooltip
        if tooltip:
            tooltip.destroy()
            tooltip = None
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)

class App:
    def __init__(self, root):
        self.root = root
        root.title("Prompt Processor")
        root.geometry("1000x800")
        root.configure(bg="#1e1e1e")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.current_file_name = None
        self.project_root = tk.StringVar()
        self.plan_path = None

        # Notebook para pestañas
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.notebook.configure(style="Custom.TNotebook")

        # Pestaña 1: Procesar Prompt (original)
        self.tab_process = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_process, text="⚙️ Procesar Prompt")
        self._setup_process_tab()

        # Pestaña 2: Plan de Mejoras (nueva)
        self.tab_plan = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_plan, text="📋 Plan de Mejoras")
        self._setup_plan_tab()

    def _setup_process_tab(self):
        """Configura la pestaña original de procesamiento de prompts."""
        tab = self.tab_process
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=0)
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(2, weight=0)
        tab.rowconfigure(3, weight=1)
        tab.rowconfigure(4, weight=0)

        # Frame de configuración del proyecto
        config_frame = tk.LabelFrame(tab, text="Configuración del proyecto", bg="#1e1e1e", fg="#d4d4d4")
        config_frame.grid(row=0, column=0, padx=10, pady=(10,5), sticky="ew")
        config_frame.columnconfigure(0, weight=1)
        config_frame.columnconfigure(1, weight=0)

        tk.Label(config_frame, text="Ruta raíz del proyecto:", bg="#1e1e1e", fg="#d4d4d4").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        path_entry = tk.Entry(config_frame, textvariable=self.project_root, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white")
        path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        path_entry.bind("<Return>", lambda e: self.update_project_root())
        tk.Button(config_frame, text="Examinar", command=self.browse_project_root, bg="#0e639c", fg="white").grid(row=0, column=2, padx=5, pady=5)
        self.auto_detect_project_root()

        # Área de entrada
        input_frame = tk.LabelFrame(tab, text="Prompt base", bg="#1e1e1e", fg="#d4d4d4")
        input_frame.grid(row=1, column=0, padx=10, pady=(5,5), sticky="nsew")
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)
        self.input_text = scrolledtext.ScrolledText(input_frame, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 10))
        self.input_text.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        # Botón Procesar
        tk.Button(tab, text="⚙️ Procesar", command=self.process, bg="#0e639c", fg="white", height=2).grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        # Área de salida
        output_frame = tk.LabelFrame(tab, text="Prompt procesado", bg="#1e1e1e", fg="#d4d4d4")
        output_frame.grid(row=3, column=0, padx=10, pady=(5,5), sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", insertbackground="white", font=("Consolas", 10))
        self.output_text.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        # Botones de acción
        action_frame = tk.Frame(tab, bg="#1e1e1e")
        action_frame.grid(row=4, column=0, padx=10, pady=(5,10), sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        action_frame.columnconfigure(2, weight=1)
        tk.Button(action_frame, text="📋 Copiar", command=self.copy, bg="#0e639c", fg="white", height=2).grid(row=0, column=0, padx=5, sticky="ew")
        tk.Button(action_frame, text="📄 PDF", command=self.pdf, bg="#0e639c", fg="white", height=2).grid(row=0, column=1, padx=5, sticky="ew")
        tk.Button(action_frame, text="🧹 Limpiar", command=self.clear, bg="#444", fg="white", height=2).grid(row=0, column=2, padx=5, sticky="ew")

    def _setup_plan_tab(self):
        """Configura la nueva pestaña de gestión del plan de mejoras."""
        tab = self.tab_plan
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        tab.rowconfigure(1, weight=0)
        tab.rowconfigure(2, weight=1)

        # Cuadro de texto para mostrar el plan
        plan_frame = tk.LabelFrame(tab, text="PLAN_MEJORAS_APA.md", bg="#1e1e1e", fg="#d4d4d4")
        plan_frame.grid(row=0, column=0, padx=10, pady=(10,5), sticky="nsew")
        plan_frame.columnconfigure(0, weight=1)
        plan_frame.rowconfigure(0, weight=1)
        self.plan_text = scrolledtext.ScrolledText(plan_frame, wrap=tk.WORD, bg="#2d2d2d", fg="#d4d4d4", font=("Consolas", 9), state="disabled")
        self.plan_text.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        create_tooltip(self.plan_text, "Contenido actual del plan de mejoras. Se actualiza automáticamente tras cada cambio.")

        # Frame de controles
        controls_frame = tk.Frame(tab, bg="#1e1e1e")
        controls_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        controls_frame.columnconfigure(0, weight=1)
        controls_frame.columnconfigure(1, weight=1)

        # Frame Añadir Tarea
        add_frame = tk.LabelFrame(controls_frame, text="➕ Añadir Tarea", bg="#1e1e1e", fg="#d4d4d4")
        add_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        add_frame.columnconfigure(1, weight=1)
        tk.Label(add_frame, text="Bloque:", bg="#1e1e1e", fg="#d4d4d4").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.add_block = tk.Entry(add_frame, width=8, bg="#2d2d2d", fg="#d4d4d4")
        self.add_block.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        create_tooltip(self.add_block, "Letra del bloque, ej: H, V, P. Debe coincidir con un título '## Bloque X – ...' existente.")
        tk.Label(add_frame, text="ID:", bg="#1e1e1e", fg="#d4d4d4").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.add_id = tk.Entry(add_frame, width=8, bg="#2d2d2d", fg="#d4d4d4")
        self.add_id.grid(row=1, column=1, sticky="w", padx=2, pady=2)
        create_tooltip(self.add_id, "Identificador único de la tarea, ej: H7")
        tk.Label(add_frame, text="Desc:", bg="#1e1e1e", fg="#d4d4d4").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        self.add_desc = tk.Entry(add_frame, bg="#2d2d2d", fg="#d4d4d4")
        self.add_desc.grid(row=2, column=1, sticky="ew", padx=2, pady=2)
        create_tooltip(self.add_desc, "Texto descriptivo de la tarea")
        tk.Button(add_frame, text="Añadir", command=self.add_task, bg="#0e639c", fg="white").grid(row=3, column=0, columnspan=2, pady=5)
        create_tooltip(add_frame.winfo_children()[-1], "Añade una nueva tarea pendiente al final del bloque especificado")

        # Frame Completar Tarea
        done_frame = tk.LabelFrame(controls_frame, text="✅ Completar Tarea", bg="#1e1e1e", fg="#d4d4d4")
        done_frame.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        done_frame.columnconfigure(1, weight=1)
        tk.Label(done_frame, text="Bloque:", bg="#1e1e1e", fg="#d4d4d4").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.done_block = tk.Entry(done_frame, width=8, bg="#2d2d2d", fg="#d4d4d4")
        self.done_block.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        create_tooltip(self.done_block, "Letra del bloque donde se encuentra la tarea")
        tk.Label(done_frame, text="ID:", bg="#1e1e1e", fg="#d4d4d4").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.done_id = tk.Entry(done_frame, width=8, bg="#2d2d2d", fg="#d4d4d4")
        self.done_id.grid(row=1, column=1, sticky="w", padx=2, pady=2)
        create_tooltip(self.done_id, "ID de la tarea a marcar como completada")
        tk.Button(done_frame, text="Completar", command=self.complete_task, bg="#0e639c", fg="white").grid(row=2, column=0, columnspan=2, pady=5)
        create_tooltip(done_frame.winfo_children()[-1], "Cambia el estado de la tarea de pendiente [ ] a completada [x]")

        # Botón refrescar
        tk.Button(tab, text="🔄 Refrescar vista", command=self.refresh_plan_view, bg="#444", fg="white").grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        # Cargar plan al iniciar
        self.auto_detect_project_root()
        self.refresh_plan_view()

    def auto_detect_project_root(self):
        current_dir = Path.cwd()
        self.project_root.set(str(current_dir))
        # Detectar ruta del plan
        plan_candidates = [current_dir / "docs" / "PLAN_MEJORAS_APA.md", Path(__file__).parent.parent / "docs" / "PLAN_MEJORAS_APA.md"]
        for cand in plan_candidates:
            if cand.exists():
                self.plan_path = cand
                return
        self.plan_path = current_dir / "docs" / "PLAN_MEJORAS_APA.md"

    def browse_project_root(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta raíz del proyecto")
        if path:
            self.project_root.set(path)
            self.auto_detect_project_root()

    def update_project_root(self):
        path = Path(self.project_root.get())
        if not path.exists():
            messagebox.showwarning("Ruta inválida", "La carpeta seleccionada no existe.")

    def get_source_root(self):
        root = self.project_root.get().strip()
        if not root:
            raise ValueError("No se ha configurado la ruta raíz del proyecto.")
        root_path = Path(root)
        if not root_path.exists():
            raise FileNotFoundError(f"No existe la carpeta: {root}")
        return root_path

    def find_file(self, root_dir: Path, file_ref: str) -> Path:
        if '/' in file_ref or '\\' in file_ref:
            target = root_dir / file_ref
            if target.exists():
                return target
            raise FileNotFoundError(f"No se encontró el archivo en la ruta especificada: {target}")
        matches = list(root_dir.rglob(file_ref))
        if not matches:
            raise FileNotFoundError(f"No se encontró ningún archivo llamado '{file_ref}' en {root_dir}")
        if len(matches) > 1:
            rel_paths = [str(m.relative_to(root_dir)) for m in matches]
            raise ValueError(f"Se encontraron múltiples archivos con nombre '{file_ref}'. Especifica una ruta más concreta:\n" + "\n".join(rel_paths))
        return matches[0]

    def normalize_content(self, content: str) -> str:
        normalized = content.replace('\r\n', '\n').replace('\r', '\n')
        lines = normalized.split('\n')
        lines = [line.rstrip() for line in lines]
        return '\n'.join(lines)

    def fingerprint(self, content: str) -> dict:
        normalized = self.normalize_content(content)
        lines = normalized.split('\n')
        return {"lines": len(lines), "chars": len(normalized), "ascii_sum_mod": sum(ord(c) for c in normalized) % 100000, "first_three": "\n".join(lines[:3]), "last_three": "\n".join(lines[-3:])}

    def process_prompt(self, base_prompt: str) -> tuple:
        pattern = re.compile(r'\[INCRUSTAR:\s*([^\]]+)\]')
        match = pattern.search(base_prompt)
        if not match:
            return base_prompt + "\n\n⚠️ No se encontró directiva [INCRUSTAR: ...].", None
        file_ref = match.group(1).strip()
        source_root = self.get_source_root()
        full_path = self.find_file(source_root, file_ref)
        raw_content = full_path.read_text(encoding="utf-8")
        file_content = self.normalize_content(raw_content)
        metrics = self.fingerprint(raw_content)
        file_name = full_path.name
        try:
            rel_path = full_path.relative_to(source_root)
        except ValueError:
            rel_path = full_path
        first_line_expected = f"# {rel_path.as_posix()}"
        metrics_json = json.dumps(metrics, indent=2, ensure_ascii=False)
        verification_block = ("\n## FASE 0 — VERIFICACIÓN AUTOMÁTICA DE INTEGRIDAD DEL ARCHIVO (OBLIGATORIA)\n\n"
            "Debes verificar **internamente** que el archivo `" + file_name + "` que has recibido está íntegro antes de modificarlo.\n\n"
            "**Métricas esperadas (calculadas por el director sobre el archivo original con normalización de formato):**\n"
            "```json\n" + metrics_json + "\n```\n\n"
            "### Instrucciones estrictas:\n"
            "1. Toma el contenido **EXACTO** del archivo tal cual ha llegado a tu contexto.\n"
            "2. **Normaliza el contenido** antes de calcular métricas:\n"
            "   - Reemplaza todos los saltos de línea `\\r\\n` o `\\r` por `\\n`.\n"
            "   - Elimina espacios en blanco al final de cada línea (`.rstrip()`).\n"
            "3. Calcula sobre el contenido normalizado: líneas (separadas por `\\n`), caracteres totales, suma ASCII mód 100000, primeras 3 líneas, últimas 3 líneas.\n"
            "4. Compara con los valores esperados.\n\n"
            "### Decisión automática:\n"
            "- ✅ Si coinciden, procede directamente a la TAREA EXACTA.\n"
            "- ❌ Si no coinciden, responde ÚNICAMENTE con el mensaje de error y NO modifiques nada.\n\n"
            "```\n"
            "❌ ARCHIVO CORRUPTO EN TRANSMISIÓN.\n"
            "   Esperado: lines=" + str(metrics['lines']) + ", chars=" + str(metrics['chars']) + ", ascii_sum_mod=" + str(metrics['ascii_sum_mod']) + "\n"
            "   Recibido: lines=<líneas_reales>, chars=<caracteres_reales>, ascii_sum_mod=<suma_real>\n"
            "```\n\n"
            "---\n\n"
            "## CONTENIDO ÍNTEGRO DEL ARCHIVO (INCRUSTADO Y NORMALIZADO)\n\n"
            "```python\n" + file_content + "\n```\n\n"
            "---\n\n"
            "## FORMATO DE ENTREGA OBLIGATORIO\n\n"
            "1. Entrega el archivo `" + file_name + "` completo modificado entre ```python y ```.\n"
            "2. La primera línea del archivo debe ser: `" + first_line_expected + "`.\n"
            "3. Incluye el output real del bloque de pruebas (si existe).\n"
            "---\n")
        min_lines, max_lines = max(1, int(metrics['lines'] * 0.95)), int(metrics['lines'] * 1.05)
        control_block = f"\n---\n\n## 📏 CONTROL DE LÍNEAS EN LA ENTREGA (OBLIGATORIO)\n\nAntes de entregar el archivo modificado, DEBES:\n1. Contar el número total de líneas del archivo que vas a entregar.\n2. Verificar que está dentro del rango permitido: **{min_lines} – {max_lines} líneas** (±5% del original).\n3. Incluir en tu respuesta, justo antes del bloque ```python, una línea con el formato:\n   `📊 LÍNEAS ENTREGADAS: <número> (rango permitido: {min_lines}-{max_lines})`\n4. Si el número de líneas está fuera del rango, DEBES incluir una sección \"📉 JUSTIFICACIÓN DE REDUCCIÓN\" o \"📈 JUSTIFICACIÓN DE AUMENTO\" explicando exactamente qué líneas se modificaron y por qué.\n\n**Si no se incluye la declaración de líneas o el número está fuera de rango sin justificación, la entrega será RECHAZADA automáticamente.**\n"
        verification_block += control_block
        before, after = base_prompt[:match.start()], base_prompt[match.end():]
        return before + verification_block + after, file_name

    def process(self):
        if not self.project_root.get().strip():
            messagebox.showerror("Error", "Debe configurar la ruta raíz del proyecto.")
            return
        try:
            _ = self.get_source_root()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        base = self.input_text.get("1.0", tk.END).strip()
        if not base:
            messagebox.showwarning("Vacío", "Pega un prompt base con la directiva [INCRUSTAR: ...]")
            return
        try:
            processed, file_name = self.process_prompt(base)
            self.current_file_name = file_name
            self.output_text.delete("1.0", tk.END)
            self.output_text.insert("1.0", processed)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def copy(self):
        content = self.output_text.get("1.0", tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.root.update()
            messagebox.showinfo("Copiado", "Listo para pegar en el modelo")
        else:
            messagebox.showwarning("Vacío", "No hay prompt procesado")

    def pdf(self):
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("Vacío", "No hay prompt para exportar")
            return
        if not PDF_AVAILABLE:
            messagebox.showerror("Falta fpdf", "Instala: pip install fpdf")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"Prompt_{Path(self.current_file_name).stem if self.current_file_name else 'export'}_{timestamp}.pdf"
        file_path = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=default_name, filetypes=[("PDF files", "*.pdf")])
        if not file_path:
            return
        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Courier", size=10)
            for line in content.split('\n'):
                safe = line.encode('latin-1', 'replace').decode('latin-1')
                pdf.multi_cell(0, 5, safe)
            pdf.output(file_path)
            messagebox.showinfo("PDF", f"Guardado en:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Error PDF", str(e))

    def clear(self):
        self.input_text.delete("1.0", tk.END)
        self.output_text.delete("1.0", tk.END)
        self.current_file_name = None

    def refresh_plan_view(self):
        """Refresca el contenido del cuadro de texto del plan."""
        if not self.plan_path or not self.plan_path.exists():
            self.plan_text.config(state="normal")
            self.plan_text.delete("1.0", tk.END)
            self.plan_text.insert("1.0", f"⚠️ Archivo no encontrado:\n{self.plan_path}")
            self.plan_text.config(state="disabled")
            return
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            self.plan_text.config(state="normal")
            self.plan_text.delete("1.0", tk.END)
            self.plan_text.insert("1.0", content)
            self.plan_text.config(state="disabled")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el plan: {e}")

    def _find_block_index(self, lines: list, block_letter: str) -> int:
        """Encuentra el índice de la última línea de un bloque dado su letra."""
        pattern = re.compile(rf"^##\s*Bloque\s*{re.escape(block_letter)}\s*[–-]", re.IGNORECASE)
        for i, line in enumerate(lines):
            if pattern.match(line.strip()):
                # Buscar el final del bloque (siguiente ## o fin del archivo)
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().startswith("## Bloque"):
                        return j - 1
                return len(lines) - 1
        return -1

    def add_task(self):
        """Añade una nueva tarea pendiente al bloque especificado."""
        block = self.add_block.get().strip()
        task_id = self.add_id.get().strip()
        desc = self.add_desc.get().strip()
        if not all([block, task_id, desc]):
            messagebox.showwarning("Campos vacíos", "Completa todos los campos: Bloque, ID y Descripción.")
            return
        if not self.plan_path or not self.plan_path.exists():
            messagebox.showerror("Error", f"Archivo del plan no encontrado: {self.plan_path}")
            return
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            lines = content.split('\n')
            block_end = self._find_block_index(lines, block)
            if block_end < 0:
                messagebox.showerror("Bloque no encontrado", f"No se encontró '## Bloque {block} – ...' en el plan.")
                return
            new_line = f"- [ ] {task_id} – {desc}"
            lines.insert(block_end + 1, new_line)
            self.plan_path.write_text('\n'.join(lines), encoding="utf-8")
            self.refresh_plan_view()
            self.add_id.delete(0, tk.END)
            self.add_desc.delete(0, tk.END)
            messagebox.showinfo("Éxito", f"Tarea {task_id} añadida al Bloque {block}.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo añadir la tarea: {e}")

    def complete_task(self):
        """Marca una tarea como completada cambiando [ ] por [x]."""
        block = self.done_block.get().strip()
        task_id = self.done_id.get().strip()
        if not all([block, task_id]):
            messagebox.showwarning("Campos vacíos", "Completa Bloque e ID.")
            return
        if not self.plan_path or not self.plan_path.exists():
            messagebox.showerror("Error", f"Archivo del plan no encontrado: {self.plan_path}")
            return
        try:
            content = self.plan_path.read_text(encoding="utf-8")
            lines = content.split('\n')
            block_start = -1
            pattern = re.compile(rf"^##\s*Bloque\s*{re.escape(block)}\s*[–-]", re.IGNORECASE)
            for i, line in enumerate(lines):
                if pattern.match(line.strip()):
                    block_start = i
                    break
            if block_start < 0:
                messagebox.showerror("Bloque no encontrado", f"No se encontró '## Bloque {block} – ...' en el plan.")
                return
            # Buscar la tarea dentro del bloque
            task_pattern = re.compile(rf"^\s*-\s*\[\s*\]\s*{re.escape(task_id)}\s*[–-]")
            found = False
            for i in range(block_start + 1, len(lines)):
                if lines[i].strip().startswith("## Bloque"):
                    break  # Fin del bloque actual
                if task_pattern.match(lines[i]):
                    lines[i] = lines[i].replace("- [ ]", "- [x]", 1)
                    found = True
                    break
            if not found:
                # Verificar si ya está completada
                done_pattern = re.compile(rf"^\s*-\s*\[\s*x\s*\]\s*{re.escape(task_id)}\s*[–-]")
                for i in range(block_start + 1, len(lines)):
                    if lines[i].strip().startswith("## Bloque"):
                        break
                    if done_pattern.match(lines[i]):
                        messagebox.showinfo("Ya completada", f"La tarea {task_id} ya está marcada como completada.")
                        return
                messagebox.showerror("Tarea no encontrada", f"No se encontró la tarea '{task_id}' pendiente en Bloque {block}.")
                return
            self.plan_path.write_text('\n'.join(lines), encoding="utf-8")
            self.refresh_plan_view()
            self.done_id.delete(0, tk.END)
            messagebox.showinfo("Éxito", f"Tarea {task_id} marcada como completada.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo completar la tarea: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()