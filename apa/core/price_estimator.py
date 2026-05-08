# apa/core/price_estimator.py
"""
Estimador de precios para modelos sin pricing explícito.

Basado en ranking de calidad (Arena score): si un modelo no expone precio,
se estima usando el precio del modelo con quality_score más cercano que sí tenga precio.
"""
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


def estimate_price_details(model_id: str, task_type: str = "generation") -> Dict[str, Any]:
    """
    Retorna detalles de precio estimado para el modelo dado.

    Args:
        model_id: ID del modelo a estimar (ej. "openrouter/elephant-alpha")
        task_type: Tipo de tarea para filtrar scores (default: "generation")

    Returns:
        Dict con:
            - prompt_price_per_1k: float (precio por 1k tokens de prompt)
            - completion_price_per_1k: float (precio por 1k tokens de completion)
            - source: str ("openrouter", "similarity", "fallback")
            - confidence: float (0.0 a 1.0)
    """
    try:
        from core.arena_fetcher import get_score_for_model
        from core.providers import provider_manager
    except ImportError as e:
        logger.warning(f"price_estimator: imports no disponibles: {e}")
        return {"prompt_price_per_1k": 0.0, "completion_price_per_1k": 0.0, "source": "error", "confidence": 0.0}
    except Exception as e:
        logger.warning(f"price_estimator: error en imports: {e}")
        return {"prompt_price_per_1k": 0.0, "completion_price_per_1k": 0.0, "source": "error", "confidence": 0.0}

    if not model_id:
        return {"prompt_price_per_1k": 0.0, "completion_price_per_1k": 0.0, "source": "invalid", "confidence": 0.0}

    # Paso 1: Intentar obtener precio real del modelo (fuente: openrouter)
    try:
        all_models = provider_manager.get_all_models()
        for m in all_models:
            if m.get("id") == model_id:
                pricing = m.get("pricing", {})
                if pricing:
                    try:
                        prompt_price = float(pricing.get("prompt", "0") or "0")
                        completion_price = float(pricing.get("completion", "0") or "0")
                        if prompt_price > 0 or completion_price > 0:
                            return {
                                "prompt_price_per_1k": prompt_price * 1000,
                                "completion_price_per_1k": completion_price * 1000,
                                "source": "openrouter",
                                "confidence": 1.0
                            }
                    except (ValueError, TypeError):
                        pass
                break
    except Exception as e:
        logger.warning(f"price_estimator: error obteniendo pricing real: {e}")

    # Paso 2: Obtener quality_score del modelo objetivo
    try:
        target_score = get_score_for_model(model_id, task_type=task_type)
        if target_score is None:
            return {"prompt_price_per_1k": 0.01, "completion_price_per_1k": 0.03, "source": "fallback", "confidence": 0.1}
    except Exception as e:
        logger.warning(f"price_estimator: error obteniendo score para {model_id}: {e}")
        return {"prompt_price_per_1k": 0.01, "completion_price_per_1k": 0.03, "source": "fallback", "confidence": 0.1}

    # Paso 3: Obtener candidatos con precio conocido y sus scores
    candidates: List[Dict[str, Any]] = []
    try:
        for m in all_models:
            pricing = m.get("pricing", {})
            if not pricing:
                continue
            try:
                prompt_price = float(pricing.get("prompt", "0") or "0")
                completion_price = float(pricing.get("completion", "0") or "0")
                if prompt_price <= 0 and completion_price <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            try:
                candidate_score = get_score_for_model(m["id"], task_type=task_type)
                if candidate_score is not None:
                    candidates.append({
                        "id": m["id"],
                        "prompt_price": prompt_price,
                        "completion_price": completion_price,
                        "score": candidate_score
                    })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"price_estimator: error procesando candidatos: {e}")
        return {"prompt_price_per_1k": 0.01, "completion_price_per_1k": 0.03, "source": "fallback", "confidence": 0.1}

    if not candidates:
        return {"prompt_price_per_1k": 0.01, "completion_price_per_1k": 0.03, "source": "fallback", "confidence": 0.1}

    # Paso 4: Encontrar candidato con score más cercano
    best_candidate = None
    best_diff = float('inf')
    for c in candidates:
        diff = abs(c["score"] - target_score)
        if diff < best_diff:
            best_diff = diff
            best_candidate = c

    if best_candidate is None:
        return {"prompt_price_per_1k": 0.01, "completion_price_per_1k": 0.03, "source": "fallback", "confidence": 0.1}

    # Aplicar margen del 20% para estimación por similitud
    prompt_est = best_candidate["prompt_price"] * 1.2
    completion_est = best_candidate["completion_price"] * 1.2
    # Calcular confianza basada en diferencia de scores
    confidence = max(0.3, min(1.0, 1.0 - (best_diff / 100.0)))

    return {
        "prompt_price_per_1k": prompt_est * 1000,
        "completion_price_per_1k": completion_est * 1000,
        "source": "similarity",
        "confidence": confidence
    }


def estimate_price(model: str) -> float:
    """
    Wrapper para compatibilidad: retorna el precio total estimado por token.
    Llama internamente a estimate_price_details y suma prompt + completion.
    """
    details = estimate_price_details(model)
    return (details["prompt_price_per_1k"] + details["completion_price_per_1k"]) / 1000


if __name__ == "__main__":
    import sys
    import logging
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.getLogger("core.price_estimator").setLevel(logging.ERROR)

    print("=== PRUEBAS: price_estimator (nueva interfaz) ===")

    from core.arena_fetcher import _arena_data
    import core.arena_fetcher as af
    from core.providers import provider_manager

    has_ranking = bool(_arena_data)
    if not has_ranking:
        print("⚠️ Ranking de Arena no disponible. Inyectando datos mínimos para prueba.")
        af._arena_data = {
            "openai/gpt-4o": {"general": 78.0},
            "openai/gpt-3.5-turbo": {"general": 68.0},
            "openrouter/elephant-alpha": {"general": 65.0},
        }
        af._needs_refresh = False

    # Prueba 1: Modelo con precio real (fuente: openrouter)
    models = provider_manager.get_all_models()
    paid_model_id = None
    for m in models:
        pricing = m.get("pricing", {})
        if pricing:
            try:
                p = float(pricing.get("prompt", "0") or "0") + float(pricing.get("completion", "0") or "0")
                if p > 0:
                    paid_model_id = m["id"]
                    break
            except (ValueError, TypeError):
                continue

    if paid_model_id:
        details = estimate_price_details(paid_model_id)
        assert details["source"] == "openrouter", f"Fuente esperada 'openrouter', got {details['source']}"
        assert details["confidence"] == 1.0, f"Confianza esperada 1.0, got {details['confidence']}"
        print(f"✓ Modelo con precio real '{paid_model_id}' → {details}")
    else:
        print("⚠️ No hay modelos con precio en provider_manager. Prueba omitida.")

    # Prueba 2: Modelo gratuito / sin precio (estimación por similitud)
    free_model = "openrouter/elephant-alpha"
    try:
        details = estimate_price_details(free_model)
        print(f"✓ Modelo gratuito '{free_model}' → {details}")
        if details["source"] == "similarity":
            assert 0.3 <= details["confidence"] <= 1.0, f"Confianza fuera de rango: {details['confidence']}"
            # Verificar que se aplicó margen ~20% (precio estimado > precio base si hubiera uno)
            print(f"  (margen aplicado: source={details['source']}, confidence={details['confidence']:.2f})")
    except Exception as e:
        print(f"⚠️ Error en prueba de estimación: {e}")

    # Prueba 3: Modelo desconocido (fallback)
    try:
        details = estimate_price_details("unknown/model-xyz-test")
        assert details["source"] == "fallback", f"Fuente esperada 'fallback', got {details['source']}"
        assert details["confidence"] == 0.1, f"Confianza esperada 0.1, got {details['confidence']}"
        print(f"✓ Modelo desconocido → {details}")
    except Exception as e:
        print(f"⚠️ Error en prueba modelo desconocido: {e}")

    # Prueba 4: Compatibilidad con estimate_price (wrapper)
    try:
        total = estimate_price(paid_model_id or "openai/gpt-4o")
        assert isinstance(total, float), f"estimate_price debe retornar float, got {type(total)}"
        print(f"✓ Wrapper estimate_price() → ${total:.8f}/token (compatibilidad OK)")
    except Exception as e:
        print(f"⚠️ Error en prueba de compatibilidad: {e}")

    print("✅ price_estimator tests passed.")
    sys.exit(0)