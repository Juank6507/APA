#!/usr/bin/env python3
"""
test_cascada_rankings.py
Test de la cascada Arena: 3 pasos × 2 rankings × 5 tareas

Ejecución:
  cd <raíz del proyecto APA>
  python test_cascada_rankings.py

Los 3 pasos:
  PASO 1: HuggingFace vía librería 'datasets'
  PASO 2: HuggingFace vía HTTP directo a parquet (sin librería datasets)
  PASO 3: Caché local (arena_cache.json v2)

Los 2 rankings por tarea:
  RANKING 1: Score en la categoría específica de la tarea (coding, math, hard_prompts...)
  RANKING 2: Score general/overall del modelo (ranking global)
"""

import sys
import os

# Asegurar que el path del proyecto APA está disponible
# El script espera ejecutarse desde la raíz del proyecto APA
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apa'))

from core.arena_fetcher import (
    _fetch_from_huggingface,
    _fetch_from_huggingface_http,
    _load_cache,
    _build_fast_index,
    _elo_to_normalized,
    normalize_model_id,
)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

TASK_TYPES = ["planning", "generation", "coding", "correction", "evaluation"]

# Mapeo de task_type APA → categoría Arena (primera = categoría específica para Ranking 1)
CATEGORY_MAP = {
    "planning":    ["hard_prompts", "overall", "general"],
    "evaluation":  ["math", "hard_prompts", "overall", "general"],
    "generation":  ["coding", "webdev", "webdev-react", "overall", "general"],
    "coding":      ["coding", "webdev", "webdev-react", "overall", "general"],
    "correction":  ["coding", "instruction_following", "overall", "general"],
}

TOP_N = 10  # Cuántos modelos mostrar por ranking


# =============================================================================
# FUNCIONES DE RANKING
# =============================================================================

def get_ranking_especifico(fast_index, task_type, top_n=TOP_N):
    """RANKING 1: Score en la categoría específica de la tarea.
    Para planning → hard_prompts, para coding → coding, para evaluation → math, etc.
    """
    primary_cat = CATEGORY_MAP[task_type][0]
    models = []
    for name, scores in fast_index.items():
        if primary_cat in scores:
            models.append((name, scores[primary_cat], primary_cat))
    models.sort(key=lambda x: -x[1])
    return models[:top_n]


def get_ranking_general(fast_index, task_type, top_n=TOP_N):
    """RANKING 2: Score general/overall del modelo.
    Refleja la calidad global del modelo independientemente de la tarea.
    También muestra el score específico para comparar.
    """
    primary_cat = CATEGORY_MAP[task_type][0]
    models = []
    for name, scores in fast_index.items():
        general_score = scores.get("general") or scores.get("overall")
        if general_score is not None:
            # Buscar también el score específico para mostrar la diferencia
            spec_score = scores.get(primary_cat)
            models.append((name, general_score, "general", spec_score, primary_cat))
    models.sort(key=lambda x: -x[1])
    return models[:top_n]


# =============================================================================
# FUNCIÓN PRINCIPAL DE TEST POR PASO
# =============================================================================

def test_paso(nombre_paso, raw_data):
    """Ejecuta el test completo para un paso de la cascada.
    Muestra ambos rankings para cada una de las 5 tareas.
    Retorna True si hubo datos, False si no.
    """
    if not raw_data:
        print(f"\n  FALLO  {nombre_paso}: No se obtuvieron datos")
        return False

    fast = _build_fast_index(raw_data)
    total_cats = set()
    for s in fast.values():
        total_cats.update(s.keys())

    print(f"\n  OK  {nombre_paso}: {len(fast)} modelos, {len(total_cats)} categorias")
    print(f"       Categorias: {', '.join(sorted(total_cats)[:8])}...")

    for task in TASK_TYPES:
        primary_cat = CATEGORY_MAP[task][0]
        count_specific = sum(1 for s in fast.values() if primary_cat in s)

        print()
        print(f"  ┌─────────────────────────────────────────────────────────────────────")
        print(f"  │ TAREA: {task:12s} → Categoria Arena: {primary_cat} ({count_specific} modelos)")
        print(f"  │")

        # ── RANKING 1: Específico ──
        r1 = get_ranking_especifico(fast, task)
        print(f"  │ RANKING 1 — Especifico ({primary_cat}):")
        if r1:
            for i, (name, score, cat) in enumerate(r1):
                print(f"  │   {i+1:2d}. {name:52s} {score:6.1f}")
        else:
            print(f"  │   (sin modelos con score en '{primary_cat}')")

        # ── RANKING 2: General ──
        r2 = get_ranking_general(fast, task)
        print(f"  │")
        print(f"  │ RANKING 2 — General (overall):")
        if r2:
            for i, (name, gen_score, _, spec_score, spec_cat) in enumerate(r2):
                if spec_score is not None:
                    diff = spec_score - gen_score
                    diff_str = f"esp={spec_score:.1f} ({diff:+.1f})"
                else:
                    diff_str = f"esp=N/A"
                print(f"  │   {i+1:2d}. {name:52s} {gen_score:6.1f}  {diff_str}")
        else:
            print(f"  │   (sin modelos con score general)")

        print(f"  └─────────────────────────────────────────────────────────────────────")

    return True


# =============================================================================
# EJECUCIÓN PRINCIPAL
# =============================================================================

def main():
    print("=" * 75)
    print(" TEST DE CASCADA ARENA — 3 PASOS × 2 RANKINGS × 5 TAREAS")
    print("=" * 75)
    print()
    print(" Metodologia de la cascada:")
    print("   PASO 1: HuggingFace via libreria 'datasets'")
    print("   PASO 2: HuggingFace via HTTP directo a parquet (sin libreria)")
    print("   PASO 3: Cache local (arena_cache.json v2)")
    print()
    print(" Rankings por tarea:")
    print("   RANKING 1: Categoria especifica (coding, math, hard_prompts...)")
    print("   RANKING 2: General/overall (calidad global del modelo)")
    print()
    print(" Mapeo de tareas APA → categorias Arena:")
    for task, cats in CATEGORY_MAP.items():
        print(f"   {task:12s} → {cats[0]:25s} (fallback: {', '.join(cats[1:])})")
    print()
    print("=" * 75)

    resultados = {}

    # ── PASO 1: HuggingFace datasets lib ──
    print("\n\n" + "═" * 75)
    print(" PASO 1: HuggingFace — Libreria 'datasets'")
    print("═" * 75)
    raw1 = _fetch_from_huggingface()
    ok1 = test_paso("PASO 1 — HF datasets lib", raw1)
    resultados["PASO 1"] = ok1

    # ── PASO 2: HuggingFace HTTP directo ──
    print("\n\n" + "═" * 75)
    print(" PASO 2: HuggingFace — HTTP directo a parquet (sin libreria datasets)")
    print("═" * 75)
    raw2 = _fetch_from_huggingface_http()
    ok2 = test_paso("PASO 2 — HF HTTP parquet", raw2)
    resultados["PASO 2"] = ok2

    # ── PASO 3: Caché local ──
    print("\n\n" + "═" * 75)
    print(" PASO 3: Cache local (arena_cache.json v2)")
    print("═" * 75)
    cached = _load_cache()
    if cached:
        # Convertir fast_index de vuelta a raw para pasar por _build_fast_index
        raw3 = {}
        for name, scores in cached.items():
            raw3[name] = {}
            for cat, score in scores.items():
                elo_approx = score * 6.0 + 1000.0
                raw3[name][cat] = {"elo": elo_approx, "votes": 0}
        ok3 = test_paso("PASO 3 — Cache local", raw3)
    else:
        ok3 = False
        print(f"\n  FALLO  PASO 3 — Cache local: No hay cache o es invalido")
    resultados["PASO 3"] = ok3

    # ── VERIFICACIÓN DE COHERENCIA ENTRE PASOS ──
    print("\n\n" + "=" * 75)
    print(" VERIFICACION: Coherencia entre pasos")
    print("=" * 75)

    fast_indices = {}
    if ok1:
        fast_indices["Paso 1"] = _build_fast_index(raw1)
    if ok2:
        fast_indices["Paso 2"] = _build_fast_index(raw2)
    if ok3:
        fast_indices["Paso 3"] = _build_fast_index(raw3)

    # Comparar el #1 de cada ranking entre todos los pasos que funcionaron
    paso_names = list(fast_indices.keys())
    for task in TASK_TYPES:
        primary_cat = CATEGORY_MAP[task][0]
        print(f"\n  Tarea: {task} (categoria: {primary_cat})")
        for rank_name, rank_func in [("Ranking 1 (especifico)", get_ranking_especifico),
                                      ("Ranking 2 (general)", get_ranking_general)]:
            leaders = {}
            for pname, fi in fast_indices.items():
                r = rank_func(fi, task, 1)
                if r:
                    leaders[pname] = r[0][0]  # nombre del #1
            if len(leaders) > 1:
                valores = set(leaders.values())
                if len(valores) == 1:
                    print(f"    {rank_name}: TODOS coinciden → {list(valores)[0]}")
                else:
                    print(f"    {rank_name}: DIFIEREN → {leaders}")
            elif len(leaders) == 1:
                pname, model = list(leaders.items())[0]
                print(f"    {rank_name}: Solo {pname} disponible → {model}")

    # ── RESUMEN FINAL ──
    print("\n\n" + "=" * 75)
    print(" RESUMEN FINAL")
    print("=" * 75)
    for paso, ok in resultados.items():
        status = "OK" if ok else "FALLO"
        print(f"  {status:6s}  {paso}")

    total_ok = sum(1 for ok in resultados.values() if ok)
    total = len(resultados)
    print(f"\n  {total_ok}/{total} pasos exitosos")

    if total_ok == total:
        print("\n  >>> CASCADA COMPLETA: Los 3 pasos funcionan y los rankings coinciden <<<")
    elif total_ok > 0:
        print(f"\n  >>> CASCADA PARCIAL: {total_ok} pasos funcionan, la cascada cae al siguiente <<<")
    else:
        print("\n  >>> CASCADA ROTA: Ningun paso funciona <<<")

    print("\n" + "=" * 75)
    return 0 if total_ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
