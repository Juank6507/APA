# tools/update_docs.py
"""
Script de actualización automática de documentación viva.

Regenera las secciones dinámicas de:
- BITACORA.md
- WHITEPAPER.md
- COST_COMPARISON.md

Usando datos extraídos directamente del código de APA.
"""
import sys
import os
import re
import logging
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from apa.core.language_profiles import LANGUAGE_PROFILES
from apa.core.project_reader import ProjectReader
from apa.core.price_estimator import estimate_price_details

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
PLAN_PATH = DOCS_DIR / "PLAN_MEJORAS_APA.md"

REPRESENTATIVE_MODELS = [
    "openai/gpt-4o", "anthropic/claude-opus-4.7", "meta-llama/llama-3-70b",
    "google/gemini-1.5-pro", "qwen/qwen2.5-coder-32b"
]


def get_project_stats() -> Dict[str, Any]:
    try:
        reader = ProjectReader(str(PROJECT_ROOT))
        stats = reader.get_stats()
        return {"total_lines": stats.get("total_lines", 0), "python_files": stats.get("python_files", 0), "total_files": stats.get("total_files", 0)}
    except Exception as e:
        logger.warning(f"Error obteniendo estadísticas: {e}")
        return {"total_lines": 0, "python_files": 0, "total_files": 0}


def generate_language_table() -> str:
    lines = ["| Lenguaje | Extensiones | Intérprete |", "|----------|-------------|------------|"]
    for profile in LANGUAGE_PROFILES:
        exts = ", ".join(profile.extensions)
        lines.append(f"| `{profile.name}` | `{exts}` | `{profile.interpreter}` |")
    return "\n".join(lines)


def generate_language_list() -> str:
    items = []
    for profile in LANGUAGE_PROFILES:
        exts = ", ".join(f"`{e}`" for e in profile.extensions)
        items.append(f"- **{profile.name}**: {exts} (intérprete: `{profile.interpreter}`)")
    return "\n".join(items)


def generate_prices_table() -> str:
    lines = ["| Modelo | Prompt ($/1k) | Completion ($/1k) | Fuente | Confianza |", "|--------|---------------|-------------------|--------|-----------|"]
    for model_id in REPRESENTATIVE_MODELS:
        try:
            details = estimate_price_details(model_id)
            prompt = f"{details['prompt_price_per_1k']:.6f}"
            completion = f"{details['completion_price_per_1k']:.6f}"
            source = details.get("source", "unknown")
            confidence = f"{details.get('confidence', 0):.2f}"
            lines.append(f"| `{model_id}` | {prompt} | {completion} | {source} | {confidence} |")
        except Exception as e:
            logger.warning(f"Error obteniendo precio para {model_id}: {e}")
            lines.append(f"| `{model_id}` | N/A | N/A | error | 0.00 |")
    return "\n".join(lines)


def parse_plan_md(plan_path: Path) -> dict:
    """Parsea PLAN_MEJORAS_APA.md extrayendo bloques y tareas."""
    if not plan_path.exists():
        logger.warning(f"Plan no encontrado: {plan_path}")
        return {"blocks": [], "pending_tasks": []}
    try:
        content = plan_path.read_text(encoding="utf-8")
        blocks, pending, current = [], [], None
        for line in content.splitlines():
            if line.strip().startswith("## Bloque"):
                current = {"name": line.strip().replace("## ", ""), "tasks": []}
                blocks.append(current)
            elif line.strip().startswith("- [") and current:
                completed = "[x]" in line
                parts = line.split("]", 1)
                task_id = parts[0].split()[-1] if len(parts) > 1 and parts[0].split() else ""
                desc = parts[1].strip() if len(parts) > 1 else ""
                task = {"id": task_id, "description": desc, "completed": completed}
                current["tasks"].append(task)
                if not completed: pending.append(task)
        logger.info(f"Plan de mejoras cargado desde {plan_path}")
        return {"blocks": blocks, "pending_tasks": pending}
    except Exception as e:
        logger.warning(f"Error parseando plan: {e}")
        return {"blocks": [], "pending_tasks": []}


def generate_hitos_table(blocks: List[Dict]) -> str:
    """Genera tabla Markdown con hitos completados (todas las tareas [x])."""
    lines = ["| Bloque | Estado |", "|--------|--------|"]
    for b in blocks:
        if b["tasks"] and all(t["completed"] for t in b["tasks"]):
            name = b["name"].replace("Bloque", "Bloque").split("–")[0].strip()
            lines.append(f"| {name} | ✅ Completado |")
    return "\n".join(lines) if len(lines) > 2 else "_Sin hitos completados aún_"


def generate_next_steps(pending: List[Dict], max_items: int = 5) -> str:
    """Genera lista con viñetas de las primeras tareas pendientes."""
    items = [f"- `{t['id']}` – {t['description']}" for t in pending[:max_items] if t.get("id")]
    return "\n".join(items) if items else "_No hay tareas pendientes registradas_"


def ensure_markers(content: str, section_title: str, start_marker: str, end_marker: str, initial_content: str) -> str:
    """Inserta marcadores si no existen, justo después del título de sección."""
    if start_marker in content and end_marker in content:
        return content
    escaped_title = re.escape(section_title.strip())
    pattern = rf"^{escaped_title}\s*$"
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
    if match:
        insert_pos = match.end()
        prefix = "\n" if insert_pos < len(content) and content[insert_pos] != '\n' else ""
        block = f"{prefix}{start_marker}\n{initial_content}\n{end_marker}\n"
        content = content[:insert_pos] + block + content[insert_pos:]
        logger.info(f"Marcadores insertados en sección: '{section_title}'")
    else:
        logger.warning(f"No se encontró sección '{section_title}' para insertar marcadores")
    return content


def update_file(filepath: Path, replacements: Dict[str, Tuple[str, str]],
                marker_config: Optional[List[Tuple[str, str, str, str]]] = None) -> bool:
    """
    Actualiza un archivo Markdown reemplazando contenido entre marcadores.
    Usa reemplazo completo del bloque para evitar duplicados.
    """
    if not filepath.exists():
        logger.warning(f"Archivo no encontrado: {filepath}")
        return False
    try:
        content = filepath.read_text(encoding="utf-8")
        original_content = content

        # Primero, insertar marcadores faltantes si se especificó configuración
        if marker_config:
            for section_title, start_marker, end_marker, initial_content in marker_config:
                content = ensure_markers(content, section_title, start_marker, end_marker, initial_content)

        # Aplicar reemplazos: captura TODO entre marcadores y reemplaza completamente
        for start_marker, (end_marker, new_content) in replacements.items():
            # Patrón que captura desde start_marker hasta end_marker (incluyendo saltos)
            pattern = re.compile(
                rf'({re.escape(start_marker)}).*?({re.escape(end_marker)})',
                re.DOTALL
            )
            # Reemplazo completo: mantiene marcadores, reemplaza solo el contenido intermedio
            replacement = f"{start_marker}\n{new_content}\n{end_marker}"
            content = pattern.sub(replacement, content)

        # Guardar solo si hubo cambios reales
        if content != original_content:
            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Actualizado: {filepath.name}")
            return True
        logger.info(f"Sin cambios: {filepath.name}")
        return False
    except Exception as e:
        logger.error(f"Error actualizando {filepath}: {e}")
        return False


def update_all_docs() -> Dict[str, bool]:
    results = {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = get_project_stats()
    plan_data = parse_plan_md(PLAN_PATH)
    plan_processed = bool(plan_data.get("blocks"))

    # BITACORA.md
    bitacora_path = DOCS_DIR / "BITACORA.md"
    bitacora_replacements = {
        "<!-- AUTO-LANGUAGES-START -->": ("<!-- AUTO-LANGUAGES-END -->", generate_language_table()),
        "<!-- AUTO-STATS-START -->": ("<!-- AUTO-STATS-END -->", f"- **Líneas de código**: {stats['total_lines']:,}\n- **Archivos Python**: {stats['python_files']}\n- **Total archivos**: {stats['total_files']}"),
        "<!-- AUTO-HITOS-START -->": ("<!-- AUTO-HITOS-END -->", generate_hitos_table(plan_data["blocks"])),
        "<!-- AUTO-PROXIMOS-START -->": ("<!-- AUTO-PROXIMOS-END -->", generate_next_steps(plan_data["pending_tasks"])),
        "<!-- AUTO-UPDATED-START -->": ("<!-- AUTO-UPDATED-END -->", f"*Última actualización automática: {now}*")
    }
    bitacora_markers = [
        ("## Lenguajes soportados", "<!-- AUTO-LANGUAGES-START -->", "<!-- AUTO-LANGUAGES-END -->", "| Lenguaje | Extensiones | Intérprete |\n|----------|-------------|------------|"),
        ("## Estadísticas del proyecto", "<!-- AUTO-STATS-START -->", "<!-- AUTO-STATS-END -->", "- **Líneas de código**: 0\n- **Archivos Python**: 0\n- **Total archivos**: 0"),
        ("## Hitos del desarrollo", "<!-- AUTO-HITOS-START -->", "<!-- AUTO-HITOS-END -->", "| Bloque | Estado |\n|--------|--------|"),
        ("## Próximos pasos", "<!-- AUTO-PROXIMOS-START -->", "<!-- AUTO-PROXIMOS-END -->", "_No hay tareas pendientes registradas_"),
        ("## Historial", "<!-- AUTO-UPDATED-START -->", "<!-- AUTO-UPDATED-END -->", "*Última actualización automática: --/--/---- --:--:--*")
    ]
    if plan_processed:
        logger.info("Actualizando sección de hitos en BITACORA.md")
        logger.info("Actualizando sección de próximos pasos en BITACORA.md")
    results["BITACORA.md"] = update_file(bitacora_path, bitacora_replacements, bitacora_markers)

    # WHITEPAPER.md
    whitepaper_path = DOCS_DIR / "WHITEPAPER.md"
    whitepaper_replacements = {
        "<!-- AUTO-LANGUAGES-LIST-START -->": ("<!-- AUTO-LANGUAGES-LIST-END -->", generate_language_list()),
        "<!-- AUTO-UPDATED-START -->": ("<!-- AUTO-UPDATED-END -->", f"*Documento actualizado: {now}*")
    }
    whitepaper_markers = [
        ("## Soporte multi‑lenguaje real", "<!-- AUTO-LANGUAGES-LIST-START -->", "<!-- AUTO-LANGUAGES-LIST-END -->", "- **lenguaje**: extensiones (intérprete: `interp`)"),
        ("## Estado actual", "<!-- AUTO-UPDATED-START -->", "<!-- AUTO-UPDATED-END -->", "*Documento actualizado: --/--/---- --:--:--*")
    ]
    results["WHITEPAPER.md"] = update_file(whitepaper_path, whitepaper_replacements, whitepaper_markers)

    # COST_COMPARISON.md
    cost_path = DOCS_DIR / "COST_COMPARISON.md"
    cost_replacements = {
        "<!-- AUTO-PRICES-TABLE-START -->": ("<!-- AUTO-PRICES-TABLE-END -->", generate_prices_table()),
        "<!-- AUTO-UPDATED-START -->": ("<!-- AUTO-UPDATED-END -->", f"*Precios actualizados: {now}*")
    }
    cost_markers = [
        ("## Precios actuales", "<!-- AUTO-PRICES-TABLE-START -->", "<!-- AUTO-PRICES-TABLE-END -->", "| Modelo | Prompt ($/1k) | Completion ($/1k) | Fuente | Confianza |\n|--------|---------------|-------------------|--------|-----------|"),
        ("## Actualización", "<!-- AUTO-UPDATED-START -->", "<!-- AUTO-UPDATED-END -->", "*Precios actualizados: --/--/---- --:--:--*")
    ]
    results["COST_COMPARISON.md"] = update_file(cost_path, cost_replacements, cost_markers)

    return results


if __name__ == "__main__":
    print("=" * 60)
    print("🔄 Actualizando documentación viva de APA")
    print("=" * 60)
    try:
        results = update_all_docs()
        print("\n📋 Resumen:")
        for doc, updated in results.items():
            status = "✅ Actualizado" if updated else "⚠️ Sin cambios / No encontrado"
            print(f"  {doc}: {status}")
        plan_status = "✅ Procesado" if PLAN_PATH.exists() else "⚠️ No encontrado"
        print(f"  Plan de mejoras: {plan_status}")
        if not PLAN_PATH.exists():
            logger.warning(f"PLAN_MEJORAS_APA.md no encontrado en {PLAN_PATH}. Hitos/próximos pasos omitidos.")
            print(f"\n⚠️ Advertencia: {PLAN_PATH.name} no existe en docs/. Se omiten hitos y próximos pasos.")
        if not DOCS_DIR.exists():
            logger.warning(f"Directorio docs/ no encontrado en {DOCS_DIR}")
            print(f"\n⚠️ Advertencia: El directorio 'docs/' no existe en {DOCS_DIR}")
            print("   Los archivos se actualizarán cuando el directorio sea creado.")
        print("\n✨ Proceso completado.")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n⚠️ Cancelado por usuario.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Error crítico: {e}")
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)