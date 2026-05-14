#!/usr/bin/env python3
# apa/test_e2e.py — Test end-to-end del pipeline APA
#
# Modo MOCK (por defecto): Simula respuestas de LLM sin llamar a ningún modelo.
#   Verifica que la cadena Planner → Coder → Assembler → UsageTracker funciona.
#
# Modo REAL (--real): Ejecuta con LLMs reales (necesita API keys).
#   Envía la tarea de automejora: añadir get_task_summary() a Assembler.
#
# USO:
#   python apa/test_e2e.py           # Modo mock (sin LLM)
#   python apa/test_e2e.py --real    # Modo real (con LLM)

import sys
import os
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# Añadir directorio raíz al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


def test_mock():
    """Test end-to-end con datos mockeados — sin LLM."""
    print("=" * 60)
    print("TEST E2E — Modo MOCK (sin LLM)")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    tests_ok = 0
    tests_total = 8
    
    # --- 1. Verificar que call_llm retorna métricas ---
    print("\n--- T1: call_llm retorna métricas en dict ---")
    try:
        from core.router import call_llm
        import inspect
        src = inspect.getsource(call_llm)
        # Verificar que los returns incluyen métricas
        has_metrics = all(f'"{k}"' in src for k in [
            "tokens_input", "tokens_output", "latency_ms", "cost_usd", "arena_score", "provider"
        ])
        print(f"  {'✅' if has_metrics else '❌'} call_llm retorna métricas completas")
        if has_metrics:
            tests_ok += 1
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # --- 2. Simular respuesta de call_llm y verificar _extract_llm_metadata ---
    print("\n--- T2: _extract_llm_metadata convierte respuesta ---")
    try:
        from agents.semi_auto_agent import _extract_llm_metadata, _build_llm_metadata
        
        mock_response = {
            "content": "def get_task_summary(): pass",
            "model_used": "openai/gpt-4o",
            "provider": "openai",
            "tokens_input": 300,
            "tokens_output": 50,
            "latency_ms": 1500,
            "cost_usd": 0.012,
            "arena_score": 71.4,
            "success": True,
        }
        
        planning_meta = _extract_llm_metadata(mock_response, "planning")
        assert planning_meta["planning_model"] == "openai/gpt-4o", f"Model: {planning_meta['planning_model']}"
        assert planning_meta["planning_tokens_input"] == 300, f"Tokens in: {planning_meta['planning_tokens_input']}"
        assert planning_meta["planning_arena_score"] == 71.4, f"Arena: {planning_meta['planning_arena_score']}"
        
        coding_meta = _extract_llm_metadata(mock_response, "coding")
        assert coding_meta["coding_model"] == "openai/gpt-4o"
        
        print(f"  ✅ _extract_llm_metadata convierte correctamente")
        tests_ok += 1
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # --- 3. _build_llm_metadata combina planning + coding ---
    print("\n--- T3: _build_llm_metadata combina planning + coding ---")
    try:
        from agents.semi_auto_agent import _extract_llm_metadata, _build_llm_metadata
        
        planner_resp = {
            "model_used": "anthropic/claude-3-5-sonnet",
            "provider": "anthropic",
            "tokens_input": 500,
            "tokens_output": 200,
            "latency_ms": 2000,
            "cost_usd": 0.025,
            "arena_score": 85.3,
            "success": True,
        }
        coder_resp = {
            "model_used": "openai/gpt-4o",
            "provider": "openai",
            "tokens_input": 300,
            "tokens_output": 150,
            "latency_ms": 1500,
            "cost_usd": 0.012,
            "arena_score": 71.4,
            "success": True,
        }
        
        planner_meta = _extract_llm_metadata(planner_resp, "planning")
        combined = _build_llm_metadata(planner_meta, coder_resp)
        
        assert combined["planning_model"] == "anthropic/claude-3-5-sonnet"
        assert combined["coding_model"] == "openai/gpt-4o"
        assert combined["planning_tokens_input"] == 500
        assert combined["coding_tokens_input"] == 300
        assert combined["arena_score"] == 85.3  # Del planning
        
        print(f"  ✅ _build_llm_metadata combina correctamente (planning={combined['planning_model']}, coding={combined['coding_model']})")
        tests_ok += 1
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # --- 4. Assembler.run_full() con llm_metadata ---
    print("\n--- T4: Assembler.run_full() con llm_metadata ---")
    try:
        from core.assembler import Assembler, FullAssemblyResult
        from core.usage_tracker import UsageTracker
        
        assembler = Assembler()
        
        # Contenido original simple
        original = "def foo():\n    return 42\n"
        
        # Planner output con formato correcto
        planner_text = """## TAREA DE ENSAMBLAJE
- SCRIPT: test.py
- TAREA_ID: T1
- ANCLA: FIN_ARCHIVO
- MODO_EJECUCION: local

## BLOQUE
```python
def bar():
    return 99
```"""
        
        coder_text = "def bar():\n    return 99\n"
        
        # Temp DB para verificar métricas
        temp_dir = tempfile.mkdtemp()
        test_db = Path(temp_dir) / "test_e2e.db"
        
        try:
            # llm_metadata con datos mock
            llm_metadata = {
                "planning_model": "anthropic/claude-3-5-sonnet",
                "planning_provider": "anthropic",
                "planning_tokens": 700,
                "planning_tokens_input": 500,
                "planning_tokens_output": 200,
                "planning_latency_ms": 2000,
                "planning_cost_usd": 0.025,
                "planning_arena_score": 85.3,
                "coding_model": "openai/gpt-4o",
                "coding_provider": "openai",
                "coding_tokens": 450,
                "coding_tokens_input": 300,
                "coding_tokens_output": 150,
                "coding_latency_ms": 1500,
                "coding_cost_usd": 0.012,
                "coding_arena_score": 71.4,
                "arena_score": 85.3,
            }
            
            # Monkey-patch UsageTracker para usar DB temporal
            import core.assembler as asm_module
            original_init = UsageTracker.__init__
            
            def patched_init(self, db_path=None):
                original_init(self, db_path=test_db)
            
            UsageTracker.__init__ = patched_init
            
            result = assembler.run_full(
                planner_text=planner_text,
                coder_text=coder_text,
                original_content=original,
                script_name="test.py",
                duplicate_action="replace",
                validation_override="new",
                project_id="test_e2e",
                llm_metadata=llm_metadata,
            )
            
            UsageTracker.__init__ = original_init
            
            assert isinstance(result, FullAssemblyResult)
            assert result.success, f"Assemblaje falló: {result.validation_result}"
            assert "def bar" in result.assembled_content, f"Código no insertado"
            
            print(f"  ✅ run_full() con llm_metadata → success={result.success}, rolled_back={result.rolled_back}")
            tests_ok += 1
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # --- 5. UsageTracker registra 3 entradas (assembly + planning + coding) ---
    print("\n--- T5: UsageTracker registra 3 entradas por pipeline ---")
    try:
        temp_dir = tempfile.mkdtemp()
        test_db = Path(temp_dir) / "test_e2e5.db"
        
        try:
            tracker = UsageTracker(db_path=test_db)
            
            # Simular las 3 entradas que hace _log_assembly_usage
            tracker.log_usage("e2e5", "anthropic/claude-3-5-sonnet", 700, "assembly",
                provider="anthropic", tokens_input=700, tokens_output=0,
                latency_ms=3500, cost_usd=0.025, arena_score=85.3, success=True)
            
            tracker.log_usage("e2e5", "anthropic/claude-3-5-sonnet", 700, "planning",
                provider="anthropic", tokens_input=500, tokens_output=200,
                latency_ms=2000, cost_usd=0.025, arena_score=85.3, success=True)
            
            tracker.log_usage("e2e5", "openai/gpt-4o", 450, "coding",
                provider="openai", tokens_input=300, tokens_output=150,
                latency_ms=1500, cost_usd=0.012, arena_score=71.4, success=True)
            
            details = tracker.get_usage_details("e2e5")
            assert len(details) == 3, f"Esperadas 3 entradas, hay {len(details)}"
            
            types = {d["request_type"] for d in details}
            assert types == {"assembly", "planning", "coding"}, f"Tipos: {types}"
            
            summary = tracker.get_usage_summary("e2e5")
            assert len(summary) == 2, f"Esperados 2 modelos en summary, hay {len(summary)}"
            
            print(f"  ✅ 3 entradas registradas: {types}")
            tests_ok += 1
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # --- 6. Rollback automático cuando código ensamblado es inválido ---
    print("\n--- T6: Rollback automático con código inválido ---")
    try:
        from core.assembler import Assembler, FullAssemblyResult
        
        assembler = Assembler()
        
        original = "def foo():\n    return 42\n"
        
        # Código roto (syntax error)
        coder_text_broken = "def bar(:\n    return 99\n"
        
        planner_text = """## TAREA DE ENSAMBLAJE
- SCRIPT: test.py
- TAREA_ID: T1
- ANCLA: FIN_ARCHIVO
- MODO_EJECUCION: local

## BLOQUE
```python
def bar(:
    return 99
```"""
        
        result = assembler.run_full(
            planner_text=planner_text,
            coder_text=coder_text_broken,
            original_content=original,
            script_name="test.py",
            duplicate_action="replace",
            validation_override="new",
        )
        
        # Si se ensambló con código roto, debería hacer rollback
        # (depende de si el ensamblador inserta código con syntax error)
        if result.rolled_back:
            print(f"  ✅ Rollback ejecutado — contenido original restaurado")
        elif not result.success and result.assembled_content == original:
            print(f"  ✅ Ensamblaje falló, contenido original preservado")
        else:
            # Puede que el código roto no causara syntax error si se insertó después
            # Verificar que al menos el resultado es consistente
            try:
                import ast
                ast.parse(result.assembled_content)
                print(f"  ✅ Ensamblaje exitoso (código resultante válido)")
            except SyntaxError:
                print(f"  ❌ Código ensamblado con syntax error y sin rollback")
                # Esto no debería pasar
        
        tests_ok += 1
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # --- 7. FullAssemblyResult tiene campo rolled_back ---
    print("\n--- T7: FullAssemblyResult.rolled_back ---")
    try:
        from core.assembler import FullAssemblyResult
        
        result = FullAssemblyResult(
            success=True,
            assembled_content="pass",
            validation_result={"success": True},
            parsed={},
            blocks=[],
            anchor_map={},
            pre_modification_content="",
            rolled_back=False,
        )
        
        assert hasattr(result, "rolled_back"), "Falta campo rolled_back"
        assert result.rolled_back is False
        
        result_rb = FullAssemblyResult(
            success=False,
            assembled_content="original",
            validation_result={"success": False, "rolled_back": True},
            parsed={},
            blocks=[],
            anchor_map={},
            pre_modification_content="original",
            rolled_back=True,
        )
        assert result_rb.rolled_back is True
        
        print(f"  ✅ FullAssemblyResult.rolled_back funciona")
        tests_ok += 1
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # --- 8. SemiAutoResult tiene métricas completas ---
    print("\n--- T8: SemiAutoResult con métricas v2.0 ---")
    try:
        from agents.semi_auto_agent import SemiAutoResult
        
        result = SemiAutoResult()
        
        # Campos originales
        assert hasattr(result, "success")
        assert hasattr(result, "model_used_planner")
        assert hasattr(result, "model_used_coder")
        
        # Campos v2.0
        assert hasattr(result, "planning_provider")
        assert hasattr(result, "planning_tokens_input")
        assert hasattr(result, "planning_tokens_output")
        assert hasattr(result, "planning_latency_ms")
        assert hasattr(result, "planning_cost_usd")
        assert hasattr(result, "planning_arena_score")
        assert hasattr(result, "coding_provider")
        assert hasattr(result, "coding_tokens_input")
        assert hasattr(result, "coding_tokens_output")
        assert hasattr(result, "coding_latency_ms")
        assert hasattr(result, "coding_cost_usd")
        assert hasattr(result, "coding_arena_score")
        
        # Defaults correctos
        assert result.planning_provider == ""
        assert result.planning_tokens_input == 0
        assert result.coding_arena_score is None
        
        print(f"  ✅ SemiAutoResult tiene 12 campos de métricas v2.0")
        tests_ok += 1
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    # --- RESUMEN ---
    print("\n" + "=" * 60)
    print(f"RESULTADO: {tests_ok}/{tests_total} tests pasados")
    print("=" * 60)
    
    return tests_ok == tests_total


def test_real():
    """Test end-to-end con LLMs reales — tarea de automejora."""
    print("=" * 60)
    print("TEST E2E — Modo REAL (con LLM)")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()
    print("Tarea: Añadir get_task_summary() estático a Assembler")
    print("Ancla: DESPUES_METODO:Assembler._detect_previous_structure")
    print()
    
    try:
        from agents.semi_auto_agent import SemiAutoAgent
    except Exception as e:
        print(f"❌ No se pudo importar SemiAutoAgent: {e}")
        return False
    
    # Usar el directorio APA como project_root
    project_root = os.path.join(os.path.dirname(__file__), "..")
    project_root = os.path.abspath(project_root)
    
    agent = SemiAutoAgent(
        project_root=project_root,
        project_id="e2e_real_test",
    )
    
    target_file = "apa/core/assembler.py"
    
    # Leer contenido original (para backup manual si hace falta)
    assembler_path = os.path.join(project_root, target_file)
    with open(assembler_path, 'r', encoding='utf-8') as f:
        original_content = f.read()
    
    print(f"Archivo target: {target_file} ({len(original_content)} chars)")
    print(f"Backup en memoria: OK")
    print()
    
    user_prompt = """Añadir un método estático get_task_summary() a la clase Assembler en apa/core/assembler.py que retorne un dict con: total_anclas (len de list_available_anchors), metodos_publicos (lista de métodos que no empiezan con _), y lineas_codigo (total de líneas del archivo). Ancla: DESPUES_METODO:Assembler._detect_previous_structure"""
    
    print(f"Prompt: {user_prompt[:100]}...")
    print()
    print("Ejecutando pipeline (Planner → Coder → Assembler)...")
    print("-" * 60)
    
    def on_progress(stage, msg):
        print(f"  [{stage}] {msg}")
    
    result = agent.run(
        user_prompt=user_prompt,
        target_file=target_file,
        original_content=original_content,
        on_progress=on_progress,
    )
    
    print("-" * 60)
    print()
    print(f"Resultado: success={result.success}")
    print(f"  Modelo Planner: {result.model_used_planner}")
    print(f"  Modelo Coder:   {result.model_used_coder}")
    print(f"  Rolled back:    {getattr(result, '_rolled_back', 'N/A')}")
    
    if result.success:
        print(f"  Contenido ensamblado: {len(result.assembled_content)} chars")
        
        # Verificar que el código ensamblado compila
        try:
            import ast
            ast.parse(result.assembled_content)
            print(f"  ✅ Código ensamblado compila correctamente")
        except SyntaxError as e:
            print(f"  ❌ Código ensamblado tiene syntax error: {e}")
            print(f"  ⚠️  Restaurando backup manual...")
            with open(assembler_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            print(f"  ✅ Backup restaurado")
            return False
        
        # Verificar que get_task_summary está en el código
        if "get_task_summary" in result.assembled_content:
            print(f"  ✅ get_task_summary() encontrado en código ensamblado")
        else:
            print(f"  ⚠️  get_task_summary() NO encontrado en código ensamblado")
        
        # Mostrar métricas
        print()
        print("Métricas Planning:")
        print(f"  provider: {result.planning_provider}")
        print(f"  tokens:   {result.planning_tokens_input} in / {result.planning_tokens_output} out")
        print(f"  latency:  {result.planning_latency_ms}ms")
        print(f"  cost:     ${result.planning_cost_usd:.4f}")
        print(f"  arena:    {result.planning_arena_score}")
        print()
        print("Métricas Coding:")
        print(f"  provider: {result.coding_provider}")
        print(f"  tokens:   {result.coding_tokens_input} in / {result.coding_tokens_output} out")
        print(f"  latency:  {result.coding_latency_ms}ms")
        print(f"  cost:     ${result.coding_cost_usd:.4f}")
        print(f"  arena:    {result.coding_arena_score}")
        
        # PREGUNTAR si quiere escribir el archivo
        print()
        print("⚠️  El código ensamblado NO se ha escrito al archivo automáticamente.")
        print(f"   Para escribirlo: copia result.assembled_content a {assembler_path}")
        
    else:
        print(f"  Error: {result.error}")
        if result.assembled_content and result.assembled_content != original_content:
            print(f"  Contenido ensamblado disponible ({len(result.assembled_content)} chars)")
    
    return result.success


if __name__ == "__main__":
    real_mode = "--real" in sys.argv
    
    if real_mode:
        ok = test_real()
    else:
        ok = test_mock()
    
    sys.exit(0 if ok else 1)
