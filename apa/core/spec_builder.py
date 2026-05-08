# apa/core/spec_builder.py
import sys
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

# Añadir el directorio padre al path para permitir imports relativos al ejecutar directamente
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.router import call_llm

logger = logging.getLogger(__name__)


class SpecBuilder:
    """
    Clase responsable de convertir una conversación de chat en una especificación
    de proyecto en formato Markdown compatible con APA.
    """

    def __init__(self):
        """Inicializa el SpecBuilder con el system prompt para generación de specs."""
        self.system_prompt = """
Eres un asistente especializado en extraer especificaciones de proyectos software a partir de conversaciones.
Analiza la conversación proporcionada y genera una especificación en formato Markdown con las siguientes secciones:
Título del proyecto (inventa uno descriptivo)
Objetivo: (qué debe hacer el proyecto)
Inputs: (lista de entradas, tipos, formatos)
Output esperado: (qué produce el sistema)
Criterio de éxito: (cómo verificar que funciona correctamente)
Si se mencionan múltiples archivos, añade una sección "Archivos:" con una lista de rutas y descripciones breves.
Responde ÚNICAMENTE con el contenido Markdown de la especificación, sin explicaciones adicionales.
"""

    def build_spec(self, conversation_history: List[Dict[str, str]]) -> str:
        """
        A partir del historial de chat, genera una especificación en formato Markdown.
        
        Args:
            conversation_history: Lista de dicts con keys "role" y "content".
            
        Returns:
            str: Contenido Markdown de la especificación generada.
            
        Raises:
            ValueError: Si conversation_history está vacío.
            RuntimeError: Si el LLM falla o retorna contenido vacío.
        """
        if not conversation_history:
            raise ValueError("conversation_history no puede estar vacío")
        
        # 1. Formatear la conversación como texto legible
        conversation_text = ""
        for msg in conversation_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                conversation_text += f"Usuario: {content}\n"
            elif role == "assistant":
                conversation_text += f"Asistente: {content}\n"
        
        # 2. Llamar al LLM
        result = call_llm(
            task_type="spec_generation",
            system_prompt=self.system_prompt,
            user_prompt=f"Conversación:\n{conversation_text}",
            max_tokens=1500,
            temperature=0.3
        )
        
        if not result.get("success"):
            raise RuntimeError(f"LLM failed to generate spec: {result.get('error')}")
        
        content = result.get("content", "").strip()
        if not content:
            raise RuntimeError("LLM returned empty content for spec generation")
        
        return content

    def save_spec(self, spec_content: str, output_path: Optional[Path] = None) -> Path:
        """
        Guarda la especificación en disco.
        
        Args:
            spec_content: Contenido Markdown de la especificación.
            output_path: Ruta opcional donde guardar. Si es None, se usa apa/specs/ con timestamp.
            
        Returns:
            Path: Ruta donde se guardó el archivo.
        """
        if output_path is None:
            specs_dir = Path(__file__).parent.parent / "specs"
            specs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = specs_dir / f"spec_chat_{timestamp}.md"
        
        output_path.write_text(spec_content, encoding="utf-8")
        logger.info(f"Spec saved to {output_path}")
        return output_path

    def is_ready(self, conversation_history: List[Dict[str, str]]) -> bool:
        """
        Evalúa si la conversación contiene suficiente información 
        para generar una spec válida (D4).
        
        Args:
            conversation_history: Lista de mensajes del chat.
            
        Returns:
            bool: True si se detectan objetivo, inputs, output y criterio de éxito.
        """
        # Extraer solo mensajes del usuario
        user_text = " ".join(
            msg.get("content", "") for msg in conversation_history 
            if msg.get("role") == "user"
        ).lower()
        
        if not user_text.strip():
            return False
        
        # Palabras clave por categoría
        objetivo_kw = ["quiero", "necesito", "objetivo", "crear", "implementar", "desarrollar", "hacer", "construir"]
        inputs_kw = ["input", "recibe", "entrada", "parámetro", "argumento", "archivo", "csv", "json"]
        output_kw = ["output", "retorna", "devuelve", "salida", "imprime", "genera", "respuesta"]
        criterio_kw = ["criterio", "éxito", "debe", "tiene que", "esperado", "assert", "prueba"]
        
        tiene_objetivo = any(kw in user_text for kw in objetivo_kw)
        tiene_inputs = any(kw in user_text for kw in inputs_kw)
        tiene_output = any(kw in user_text for kw in output_kw)
        tiene_criterio = any(kw in user_text for kw in criterio_kw)
        
        return all([tiene_objetivo, tiene_inputs, tiene_output, tiene_criterio])


if __name__ == "__main__":
    builder = SpecBuilder()

    # ========================================
    # Pruebas de is_ready() (D4)
    # ========================================
    print("🧪 Ejecutando pruebas de is_ready()...")

    # Caso 1: Conversación completa (debe retornar True)
    hist_completo = [
        {"role": "user", "content": "Quiero una API que sume dos números. Recibe a y b como enteros. Retorna la suma en JSON. Debe pasar un test con assert."}
    ]
    assert builder.is_ready(hist_completo) == True, "❌ Caso completo falló"
    print("  ✓ Caso completo: True")

    # Caso 2: Conversación incompleta (falta criterio de éxito) → False
    hist_incompleto = [
        {"role": "user", "content": "Quiero una función que sume dos números."}
    ]
    assert builder.is_ready(hist_incompleto) == False, "❌ Caso incompleto falló"
    print("  ✓ Caso incompleto: False")

    # Caso 3: Conversación vacía → False
    assert builder.is_ready([]) == False, "❌ Caso vacío falló"
    print("  ✓ Caso vacío: False")

    print("✅ Tests de is_ready() pasados.\n")

    # ========================================
    # Pruebas existentes (build_spec / save_spec)
    # ========================================
    test_history = [
        {"role": "user", "content": "Quiero una API que sume dos números"},
        {"role": "assistant", "content": "¿Qué inputs recibe? ¿Qué debe retornar?"},
        {"role": "user", "content": "Recibe a y b como enteros, retorna la suma en JSON"}
    ]

    try:
        spec = builder.build_spec(test_history)
        print("=== Spec generada ===")
        print(spec)
        assert "Objetivo" in spec, "Falta Objetivo"
        assert "Criterio de éxito" in spec, "Falta Criterio de éxito"
        print("\n✅ Spec generada correctamente")
        
        # Probar guardado
        saved_path = builder.save_spec(spec)
        print(f"✅ Spec guardada en {saved_path}")
        
        # Limpieza de archivo de prueba
        if saved_path.exists():
            saved_path.unlink()
            
    except Exception as e:
        print(f"⚠️ Prueba de LLM omitida o fallida (requiere conexión/keys): {e}")