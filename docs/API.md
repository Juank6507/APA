# API.md

## Base URL
No aplica (proyecto sin endpoints HTTP).

## Autenticación
No aplica.

## Funciones y clases públicas principales

### CorrectorAgent (corrector.py)
- `__init__()`
- `_clean_code_response(text)`
- `analyze_error(code, execution_result, task)`
- `_build_fix_prompt_with_dependencies(task, code, error_message, attempt)`
- `_call_ollama_for_simple_correction(model_id, system_prompt, user_prompt, max_tokens, temperature)`
- `correct(task, code, execution_result, attempt, current_model, project_id)`
- `correction_loop(task, initial_code, initial_execution, max_attempts)`
- `_generate_diagnosis(history, final_execution)`
- `analyze_error(self, code, execution_result, task)`
- `correct(self, task, code, execution_result, attempt, current_model, project_id)`
- `correction_loop(self, task, initial_code, initial_execution, max_attempts)`
- `test_b2_ollama_simple_error()`

### DocumenterAgent (documenter.py)
- `__init__()`
- `_format_stats(stats)`
- `_clean_markdown_wrapper(content)`
- `_generate_costs_section(project_path)`
- `generate_readme(context, stats, signatures)`
- `generate_configuration_doc(context, stats, env_vars)`
- `generate_api_doc(context, stats, signatures)`
- `generate_development_doc(context, stats, signatures)`
- `document_project(project_path, output_path)`
- `document_generated_files(project_id, files)`
- `gen_doc(name, func_and_args)`
- `extract_signatures(project_path)`
- `extract_env_variables(project_path)`
- `generate_readme(self, context, stats, signatures)`
- `generate_configuration_doc(self, context, stats, env_vars)`
- `generate_api_doc(self, context, stats, signatures)`
- `generate_development_doc(self, context, stats, signatures)`
- `document_project(self, project_path, output_path)`
- `document_generated_files(self, project_id, files)`

### GeneratorAgent (generator.py)
- `__init__()`
- `_clean_code_response(text)`
- `_build_user_prompt(task)`
- `_build_enriched_prompt(task, base_prompt)`
- `normalize_filename(name)`