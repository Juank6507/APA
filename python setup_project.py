from pathlib import Path

def main():
    root = Path("apa")

    files = {
        "core/__init__.py": '"""Módulo core. Contiene la lógica central de orquestación y planificación del agente APA."""',
        "core/orchestrator.py": '"""Orquestador principal del APA. Coordina el ciclo completo: recibe spec, genera plan, distribuye tareas a agentes y gestiona el estado del proyecto."""',
        "core/planner.py": '"""Planificador de tareas. Descompone las especificaciones en pasos ejecutables y determina el orden de ejecución."""',
        "core/router.py": '"""Router de modelos LLM. Consulta OpenRouter en tiempo real, filtra modelos gratuitos y selecciona el más adecuado según el tipo de tarea."""',
        "core/loop.py": '"""Bucle principal de ejecución. Gestiona el ciclo de retroalimentación, validación continua y reintento ante fallos."""',
        "mcp/__init__.py": '"""Paquete MCP. Implementación de la capa de comunicación estructurada entre componentes del sistema."""',
        "mcp/server.py": '"""Servidor MCP. Gestiona conexiones, enruta solicitudes a los agentes y mantiene el estado de las sesiones activas."""',
        "agents/__init__.py": '"""Paquete de agentes. Colección de módulos especializados en generación y corrección autónoma de código."""',
        "agents/generator.py": '"""Agente generador de código. Recibe una tarea del plan y produce código Python ejecutable para cumplir su objetivo."""',
        "agents/corrector.py": '"""Agente corrector de código. Analiza errores de ejecución, genera parches y valida la corrección antes de integrar cambios."""',
        "skills/__init__.py": '"""Módulo de habilidades. Almacena y carga herramientas reutilizables que los agentes pueden invocar durante la ejecución."""',
        "sandbox/.gitkeep": "",
        "interface/__init__.py": '"""Paquete de interfaz. Contiene los componentes para la exposición y gestión de la UI web local."""',
        "interface/app.py": '"""Aplicación web local. Expone endpoints HTTP y renderiza la interfaz para interactuar con el agente APA."""',
        "config/settings.py": '"""Configuración global. Gestiona rutas, parámetros de conexión SSH/NAS y variables de entorno del sistema."""',
        "tests/.gitkeep": "",
        "specs/example.md": "# Spec de ejemplo\nObjetivo: suma dos números enteros y retorna el resultado.\nInputs: dos enteros a y b.\nOutput esperado: un entero con el valor de a + b.\nCriterio de éxito: suma(2, 3) retorna 5.",
        "requirements.txt": ""
    }

    created = 0
    omitted = 0

    for rel_path, content in files.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            print(f"OMITIDO: {file_path}")
            omitted += 1
        else:
            file_path.write_text(content, encoding="utf-8")
            print(f"CREADO: {file_path}")
            created += 1

    print("=== APA setup completo ===")
    print(f"Creados: {created} archivos")
    print(f"Omitidos: {omitted} archivos")

if __name__ == "__main__":
    main()