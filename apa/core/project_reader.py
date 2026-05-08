# apa/core/project_reader.py

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


class ProjectReader:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        self._cache = None
        self._stats_cache = None

    def _build_tree(self, path: Path, prefix: str = "", depth: int = 0, max_depth: int = 3) -> str:
        """Build ASCII tree representation of directory structure."""
        if depth >= max_depth:
            return f"{prefix}[...]\n"
        
        result = ""
        try:
            items = sorted(
                [p for p in path.iterdir() if not p.name.startswith('.')],
                key=lambda x: (not x.is_dir(), x.name.lower())
            )
            
            for i, item in enumerate(items):
                is_last = (i == len(items) - 1)
                connector = "└── " if is_last else "├── "
                result += f"{prefix}{connector}{item.name}\n"
                
                if item.is_dir():
                    extension = "    " if is_last else "│   "
                    result += self._build_tree(item, prefix + extension, depth + 1, max_depth)
        except PermissionError:
            result += f"{prefix}[Permission denied]\n"
        except Exception as e:
            logger.warning(f"Error reading directory {path}: {e}")
        
        return result

    def read(self) -> dict:
        """Read the entire project and return structured data."""
        if self._cache is not None:
            return self._cache
        
        try:
            files = []
            total_lines = 0
            total_size = 0
            
            for file_path in self.project_path.rglob('*'):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    try:
                        rel_path = file_path.relative_to(self.project_path)
                        content = file_path.read_text(encoding='utf-8', errors='replace')
                        lines = content.splitlines()
                        size = file_path.stat().st_size
                        
                        files.append({
                            "path": str(rel_path),
                            "extension": file_path.suffix,
                            "lines": len(lines),
                            "size": size,
                            "content": content,
                            "modified": datetime.fromtimestamp(
                                file_path.stat().st_mtime
                            ).isoformat()
                        })
                        
                        total_lines += len(lines)
                        total_size += size
                    except Exception as e:
                        logger.warning(f"Error reading file {file_path}: {e}")
                        continue
            
            structure = self._build_tree(self.project_path)
            
            result = {
                "project_name": self.project_path.name,
                "project_path": str(self.project_path),
                "total_files": len(files),
                "total_lines": total_lines,
                "total_size": total_size,
                "structure": structure,
                "files": files,
                "read_at": datetime.utcnow().isoformat()
            }
            
            self._cache = result
            return result
            
        except Exception as e:
            logger.error(f"Error reading project: {e}")
            return {
                "project_name": self.project_path.name,
                "project_path": str(self.project_path),
                "total_files": 0,
                "total_lines": 0,
                "total_size": 0,
                "structure": "",
                "files": [],
                "read_at": datetime.utcnow().isoformat(),
                "error": str(e)
            }

    def to_context(self, max_tokens: int = 4000) -> str:
        """Convert project to LLM-friendly context string with token limits."""
        data = self.read()
        
        # Estimate: 4 chars per token
        max_chars = max_tokens * 4
        
        # Start with project header
        context_parts = [
            f"# Project: {data['project_name']}",
            f"# Path: {data['project_path']}",
            f"# Files: {data['total_files']}, Lines: {data['total_lines']}",
            "",
            "## Directory Structure",
            data['structure'].strip(),
            "",
            "## File Contents"
        ]
        
        current_length = sum(len(p) + 1 for p in context_parts)
        
        # Separate Python files from others
        python_files = [f for f in data['files'] if f['extension'] == '.py']
        other_files = [f for f in data['files'] if f['extension'] != '.py']
        
        # Prioritize Python files
        prioritized = python_files + other_files
        
        for file_info in prioritized:
            if current_length >= max_chars:
                break
            
            rel_path = file_info['path']
            content = file_info['content']
            lines = content.splitlines()
            
            # Estimate if we can fit this file
            file_header = f"\n### File: {rel_path}\n"
            file_length = len(file_header) + len(content) + 1
            
            if current_length + file_length <= max_chars:
                context_parts.append(file_header)
                context_parts.append(content)
                current_length += file_length
            else:
                # Truncate the file
                remaining_chars = max_chars - current_length - len(file_header)
                if remaining_chars > 100:
                    truncated_lines = remaining_chars // 4
                    truncated_content = '\n'.join(lines[:truncated_lines])
                    omitted = len(lines) - truncated_lines
                    
                    context_parts.append(file_header)
                    context_parts.append(truncated_content)
                    if omitted > 0:
                        context_parts.append(f"\n# [TRUNCADO - {omitted} líneas omitidas]")
                    current_length = max_chars
                break
        
        return '\n'.join(context_parts)[:max_chars]

    def generate_refactor_spec(self, objetivo: str, problemas: list = None,
                               criterios: list = None) -> str:
        """Generate automatically a spec.md for refactoring the project."""
        if problemas is None:
            problemas = ["Analizar y mejorar según buenas prácticas"]
        if criterios is None:
            criterios = ["El proyecto refactorizado ejecuta sin errores"]
        
        context = self.to_context(max_tokens=2000)
        project_name = self.project_path.name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        problemas_md = "\n".join(f"- {p}" for p in problemas)
        criterios_md = "\n".join(f"- {c}" for c in criterios)
        
        spec_content = f"""# Spec: Refactorización de {project_name}

Modo: refactorización
Proyecto: {self.project_path}

## Objetivo
{objetivo}

## Contexto del proyecto actual
{context}

## Problemas a resolver
{problemas_md}

## Output esperado
Código refactorizado que:
- Mantiene toda la funcionalidad existente
- Corrige los problemas identificados
- Sigue PEP8 y buenas prácticas Python
- Incluye docstrings en todas las funciones

## Criterio de éxito
{criterios_md}
"""
        
        specs_dir = Path(__file__).parents[1] / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"refactor_{project_name}_{timestamp}.md"
        spec_path = specs_dir / filename
        
        with open(spec_path, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        
        logger.info(f"Refactor spec generated: {spec_path}")
        return str(spec_path)

    def get_stats(self) -> dict:
        """Return quick statistics about the project without reading full content."""
        if self._stats_cache is not None:
            return self._stats_cache
        
        try:
            total_files = 0
            python_files = 0
            total_lines = 0
            total_size = 0
            languages = set()
            largest_file = None
            largest_size = 0
            oldest_modified = None
            newest_modified = None
            
            for file_path in self.project_path.rglob('*'):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    try:
                        stat = file_path.stat()
                        ext = file_path.suffix.lower()
                        
                        total_files += 1
                        total_size += stat.st_size
                        
                        if ext == '.py':
                            python_files += 1
                        
                        if ext:
                            languages.add(ext.lstrip('.'))
                        
                        if stat.st_size > largest_size:
                            largest_size = stat.st_size
                            largest_file = str(file_path.relative_to(self.project_path))
                        
                        mtime = datetime.fromtimestamp(stat.st_mtime)
                        if oldest_modified is None or mtime < oldest_modified:
                            oldest_modified = mtime
                        if newest_modified is None or mtime > newest_modified:
                            newest_modified = mtime
                            
                    except Exception as e:
                        logger.warning(f"Error getting stats for {file_path}: {e}")
                        continue
            
            # Estimate lines for Python files only (quick scan)
            for file_path in self.project_path.rglob('*.py'):
                if file_path.is_file():
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            total_lines += sum(1 for _ in f)
                    except:
                        pass
            
            result = {
                "project_name": self.project_path.name,
                "total_files": total_files,
                "python_files": python_files,
                "total_lines": total_lines,
                "total_size_kb": round(total_size / 1024, 2),
                "languages": sorted(list(languages)),
                "largest_file": largest_file,
                "oldest_modified": oldest_modified.isoformat() if oldest_modified else None,
                "newest_modified": newest_modified.isoformat() if newest_modified else None
            }
            
            self._stats_cache = result
            return result
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "project_name": self.project_path.name,
                "total_files": 0,
                "python_files": 0,
                "total_lines": 0,
                "total_size_kb": 0,
                "languages": [],
                "largest_file": None,
                "oldest_modified": None,
                "newest_modified": None,
                "error": str(e)
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== PRUEBA 1: stats rápidas del propio proyecto APA ===")
    reader = ProjectReader(".")
    stats = reader.get_stats()
    print(f"Proyecto: {stats['project_name']}")
    print(f"Archivos Python: {stats['python_files']}")
    print(f"Total líneas: {stats['total_lines']}")
    print(f"Tamaño: {stats['total_size_kb']:.1f} KB")
    print(f"Lenguajes: {stats['languages']}")
    print("STATS OK")
    
    print("\n=== PRUEBA 2: lectura completa ===")
    data = reader.read()
    print(f"\nArchivos encontrados: {data['total_files']}")
    print(f"Estructura:\n{data['structure']}")
    print("READ OK")
    
    print("\n=== PRUEBA 3: contexto para LLM ===")
    context = reader.to_context(max_tokens=2000)
    print(f"\nContexto generado: {len(context)} chars")
    print(f"Estimado tokens: {len(context)//4}")
    print(context[:500])
    print("CONTEXT OK")
    
    print("\n=== PRUEBA 4: generar spec de refactorización ===")
    spec_path = reader.generate_refactor_spec(
        objetivo="Mejorar la calidad del código, añadir docstrings y aplicar PEP8",
        problemas=[
            "Falta documentación en algunos módulos",
            "Logging inconsistente entre módulos",
            "Imports duplicados en varios archivos"
        ],
        criterios=[
            "Todos los módulos tienen docstrings",
            "Logging unificado usando el mismo formato",
            "Sin imports duplicados"
        ]
    )
    print(f"\nSpec generada en: {spec_path}")
    print("SPEC_GEN OK")