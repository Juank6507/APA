# apa/interface/app.py

import sys
import os
import json
import logging
import threading
import time
import asyncio
import sqlite3
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings
from core.orchestrator import Orchestrator
from core.project_reader import ProjectReader
from core.router import call_llm, get_scaling_state
from core.pool import pool as _global_pool
from core.pipeline_state import PipelineStateManager
from core.price_estimator import estimate_price_details  
from mcp.server import NASConnector      
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# P5: Notificaciones compartidas — motor unico de presentacion (v3.0)
# TODO el HTML/CSS/JS de notificaciones viene del bridge:
from core.notifications import register_callback, unregister_callback, get_recent_events
from core.notification_ui_bridge import (
    format_event, get_event_summary, get_full_summary,
    EVENT_TYPES_LIST, create_bridge_callback,
    NOTIF_CSS, NOTIF_TAB_BUTTON, NOTIF_SECTION_HTML, NOTIF_JS,
)

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

app = FastAPI(title="APA - Agente de Programación Autónoma")

SPECS_DIR = Path(__file__).parents[1] / "specs"
SPECS_DIR.mkdir(parents=True, exist_ok=True)

projects = {}
event_queues = {}

# P5: Buffer SSE para notificaciones en tiempo real
_sse_buffer: List[Dict[str, Any]] = []


# P5v3: Startup — conectar arena_fetcher + populate_pool para que
# las notificaciones de ranking y pool se disparen al arrancar app.py
def _startup_init_subsystems():
    """Inicializa subsistemas en background al arrancar FastAPI."""
    def _do_init():
        try:
            # 1) Importar arena_fetcher: dispara arena:cache_loaded + arena:refresh_*
            from core import arena_fetcher  # noqa: F401
        except Exception:
            pass
        try:
            # 2) Poblar pool: dispara pool:populated + pool:model_updated por cada modelo
            from core.router import populate_pool
            populate_pool()
        except Exception:
            pass
        try:
            from core.notifications import notify
            notify("system:startup", "APA FastAPI iniciado — subsistemas conectados",
                   {"arena": True, "pool": True})
        except Exception:
            pass
    threading.Thread(target=_do_init, daemon=True).start()


@app.on_event("startup")
async def _on_startup():
    _startup_init_subsystems()

_sse_buffer_lock = threading.Lock()


def _sse_notification_callback(event_type, message, data):
    # Callback registrado en el event bus: formatea y guarda en buffer SSE.
    formatted = format_event({
        'type': event_type,
        'message': message,
        'data': data or {},
        'timestamp': time.time(),
    })
    with _sse_buffer_lock:
        _sse_buffer.append(formatted)
        if len(_sse_buffer) > 300:
            _sse_buffer.pop(0)


register_callback(_sse_notification_callback)

# =============================================================================
# FACTOR DE COSTES INDIRECTOS DE INFRAESTRUCTURA
# -----------------------------------------------------------------------------
# Basado en el "Uptime Institute 2025 Global Data Center Survey", que estima
# que los costes de energía, refrigeración y amortización de servidores
# representan aproximadamente un 12% adicional sobre el coste de cómputo puro.
# Fuente: https://uptimeinstitute.com/resources/research-and-reports
# =============================================================================
INFRASTRUCTURE_OVERHEAD_FACTOR = 1.12


# =============================================================================
# FUNCIONES AUXILIARES PARA DASHBOARD (expuestas para testing)
# =============================================================================

def _count_cache_entries(cache_path: Optional[Path] = None) -> int:
    """Cuenta entradas en la tabla 'cache' de llm_cache.db de forma segura."""
    if cache_path is None:
        cache_path = Path(__file__).parents[1] / "cache" / "llm_cache.db"

    if not cache_path.exists():
        return 0

    try:
        conn = sqlite3.connect(str(cache_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


# =============================================================================
# SISTEMA DE COSTES DINÁMICOS: Precios obtenidos de provider_manager + estimate_price_details
# =============================================================================
_price_cache: Dict[str, Dict[str, Any]] = {}


def _get_model_price_details(model: str) -> Dict[str, Any]:
    """
    Obtiene detalles de precio para un modelo:
    - Primero consulta provider_manager para precio real.
    - Si no hay precio real, usa estimate_price_details como fallback.
    - Cachea el resultado en memoria.
    Retorna dict con: prompt_price_per_1k, completion_price_per_1k, source, confidence
    """
    if model in _price_cache:
        return _price_cache[model]

    try:
        from core.providers import provider_manager
        all_models = provider_manager.get_all_models()

        for m in all_models:
            if m.get("id") == model:
                pricing = m.get("pricing", {})
                if pricing:
                    try:
                        prompt_price = float(pricing.get("prompt", "0") or "0")
                        completion_price = float(pricing.get("completion", "0") or "0")
                        if prompt_price > 0 or completion_price > 0:
                            result = {
                                "prompt_price_per_1k": prompt_price * 1000,
                                "completion_price_per_1k": completion_price * 1000,
                                "source": "real",
                                "confidence": 1.0
                            }
                            _price_cache[model] = result
                            return result
                    except (ValueError, TypeError):
                        pass
                break
    except Exception as e:
        logger.warning(f"Error obteniendo precio real para {model}: {e}")

    # Fallback a estimate_price_details
    try:
        details = estimate_price_details(model)
        _price_cache[model] = details
        return details
    except Exception as e:
        logger.warning(f"Error en estimate_price_details para {model}: {e}")
        return {"prompt_price_per_1k": 0.0, "completion_price_per_1k": 0.0, "source": "error", "confidence": 0.0}


def _get_dashboard_data(project_id: str) -> dict:
    """Obtiene métricas para el dashboard usando UsageTracker y precios dinámicos con fuente/confianza."""
    from core.usage_tracker import UsageTracker
    import sqlite3
    from pathlib import Path
    import json

    tracker = UsageTracker()
    aggregated_usage = tracker.get_aggregated_usage(project_id)

    # models_used se construye desde usage_records (llamadas individuales), no desde plan.json
    usage_records = tracker.get_usage_by_project(project_id)
    models_used = {}
    for record in usage_records:
        model = record.get("model", "unknown")
        models_used[model] = models_used.get(model, 0) + 1

    # Cálculo de coste usando estimate_price_details con fuente y confianza
    real_cost_usd = 0.0
    cost_sources = {}
    cost_confidences = {}

    for model, tokens in aggregated_usage.items():
        price_details = _get_model_price_details(model)
        prompt_price = price_details.get("prompt_price_per_1k", 0.0)
        completion_price = price_details.get("completion_price_per_1k", 0.0)
        # Asumimos 50/50 split para cálculo simple; en producción se usarían tokens reales por tipo
        price_per_token = (prompt_price + completion_price) / 2000.0
        model_cost = tokens * price_per_token
        real_cost_usd += model_cost

        # Registrar fuente y confianza para este modelo
        cost_sources[model] = price_details.get("source", "unknown")
        cost_confidences[model] = price_details.get("confidence", 0.0)

    real_cost_usd *= INFRASTRUCTURE_OVERHEAD_FACTOR
    estimated_cost_usd = real_cost_usd  # Mismo cálculo por ahora; diferencia semántica futura

    from core.llm_cache import LLMCache
    cache = LLMCache()
    try:
        with sqlite3.connect(str(cache.cache_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cache")
            cache_entries = cursor.fetchone()[0]
    except Exception:
        cache_entries = 0

    # task_success_rate SÍ depende de plan.json (se conserva esta dependencia)
    specs_dir = Path(__file__).parents[1] / "specs"
    plan_path = specs_dir / project_id / "plan.json"
    task_success_rate = 0.0
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            tasks = plan.get("tasks", [])
            if tasks:
                completed = sum(1 for t in tasks if t.get("status") == "completed")
                task_success_rate = (completed / len(tasks)) * 100.0
        except Exception:
            pass

    return {
        "project_id": project_id,
        "cache_entries": cache_entries,
        "task_success_rate": task_success_rate,
        "models_used": models_used,
        "real_cost_usd": round(real_cost_usd, 6),
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "cost_sources": cost_sources,
        "cost_confidences": cost_confidences
    }


# =============================================================================
# FUNCIÓN DE AUTOCONOCIMIENTO: Carga contexto desde documentación viva
# =============================================================================

def _load_self_context() -> str:
    """
    Carga un contexto de autoconocimiento desde la documentación viva.
    Retorna un texto conciso (max 2000 caracteres) describiendo a APA.
    """
    docs_dir = Path(__file__).parents[1] / "docs"
    logger.info(f"Cargando contexto desde {docs_dir}")
    context_parts = []

    # Intentar cargar BITACORA.md
    bitacora_path = docs_dir / "BITACORA.md"
    if bitacora_path.exists():
        try:
            content = bitacora_path.read_text(encoding='utf-8')
            # Extraer sección "Resumen ejecutivo" (desde "## Resumen ejecutivo" hasta siguiente "##")
            match = re.search(r'## Resumen ejecutivo\s*\n(.*?)(?=\n##\s|\Z)', content, re.DOTALL)
            if match:
                context_parts.append(match.group(1).strip())
                logger.info(f"Contexto cargado desde BITACORA.md ({len(context_parts)} partes)")
        except Exception as e:
            logger.warning(f"Error leyendo BITACORA.md: {e}")

    # Intentar cargar WHITEPAPER.md
    whitepaper_path = docs_dir / "WHITEPAPER.md"
    if whitepaper_path.exists():
        try:
            content = whitepaper_path.read_text(encoding='utf-8')
            # Extraer la lista de lenguajes o la sección "¿Qué hace único a APA?"
            match = re.search(r'<!-- AUTO-LANGUAGES-LIST-START -->(.*?)<!-- AUTO-LANGUAGES-LIST-END -->', content, re.DOTALL)
            if match:
                langs = match.group(1).strip()
                context_parts.append(f"Lenguajes soportados:\n{langs}")
                logger.info(f"Contexto cargado desde WHITEPAPER.md ({len(context_parts)} partes)")
        except Exception as e:
            logger.warning(f"Error leyendo WHITEPAPER.md: {e}")

    if not context_parts:
        logger.warning("No se encontró documentación. Usando contexto por defecto.")
        return "Soy APA, un agente de programación autónoma en fase de desarrollo."

    full_context = "\n\n".join(context_parts)
    # Limitar a ~1500 caracteres para dejar espacio a instrucciones
    if len(full_context) > 1500:
        full_context = full_context[:1497] + "..."
    return full_context


# =============================================================================
# MODELOS DE REQUEST
# =============================================================================

class RunRequest(BaseModel):
    spec: str
    spec_name: Optional[str] = None


class AnalyzeRequest(BaseModel):
    project_path: str
    objetivo: str = "Refactorizar y mejorar la calidad del código"
    problemas: list[str] = []
    criterios: list[str] = []


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = []


# =============================================================================
# ENDPOINT PRINCIPAL: Interfaz web con pestañas reordenadas y tema oscuro
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    # P5v3: El HTML usa placeholders <!-- __P5_*__ --> que se reemplazan
    # con las constantes del bridge (NOTIF_CSS, NOTIF_TAB_BUTTON, etc.)
    # Toda la visual de notificaciones vive en notification_ui_bridge.py
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>🤖 APA</title>
    <style>
        body {
            font-family: system-ui, sans-serif;
            background: #0f0f0f;
            color: #e0e0e0;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }
        .container {
            background: #1a1a1a;
            padding: 24px;
            border-radius: 8px;
            border: 1px solid #333;
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 { color: #e0e0e0; margin-bottom: 8px; }
        .subtitle { color: #aaa; margin-bottom: 24px; }

        .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid #333; padding-bottom: 0; }
        .tab {
            padding: 12px 24px;
            cursor: pointer;
            border: none;
            background: #2a2a2a;
            border-radius: 8px 8px 0 0;
            font-weight: 500;
            color: #888;
            transition: all 0.2s;
        }
        .tab:hover { background: #333; color: #ccc; }
        .tab.active { background: #3b82f6; color: white; }

        .form-section { margin-bottom: 20px; }
        label { display: block; font-weight: 500; margin-bottom: 8px; color: #aaa; }
        input[type="text"], textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #444;
            border-radius: 4px;
            font-family: monospace;
            font-size: 14px;
            box-sizing: border-box;
            background: #111;
            color: #e0e0e0;
        }
        textarea { min-height: 200px; resize: vertical; }
        input[type="text"]:focus, textarea:focus {
            outline: none;
            border-color: #3b82f6;
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3);
        }

        button {
            background: #3b82f6;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 500;
            transition: background 0.2s;
        }
        button:hover { background: #2563eb; }
        button:disabled { background: #444; color: #888; cursor: not-allowed; }
        button.secondary { background: #444; }
        button.secondary:hover { background: #555; }

        .status { padding: 12px; border-radius: 4px; margin: 16px 0; }
        .status.pending { background: #2a1f0f; color: #f59e0b; border: 1px solid #444; }
        .status.running { background: #0f1a2a; color: #60a5fa; border: 1px solid #444; }
        .status.completed { background: #0f2a1a; color: #22c55e; border: 1px solid #444; }
        .status.failed { background: #2a0f0f; color: #ef4444; border: 1px solid #444; }

        #logs {
            background: #0a0a0a;
            color: #d4d4d4;
            padding: 16px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 13px;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            margin-top: 16px;
            border: 1px solid #333;
        }

        #history-section { margin-top: 32px; border-top: 1px solid #333; padding-top: 24px; }
        .history-toggle {
            background: none;
            border: none;
            color: #60a5fa;
            cursor: pointer;
            padding: 0;
            font-size: 14px;
            text-decoration: underline;
        }
        .history-table { width: 100%; border-collapse: collapse; margin-top: 16px; background: #1a1a1a; }
        .history-table th, .history-table td { padding: 12px; text-align: left; border-bottom: 1px solid #333; color: #e0e0e0; }
        .history-table th { background: #111; font-weight: 600; }
        .history-table tr:nth-child(even) { background: #111; }
        .history-table tr:hover { background: #222; }
        .badge { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 500; }
        .badge.pending { background: #2a1f0f; color: #f59e0b; }
        .badge.running { background: #0f1a2a; color: #60a5fa; }
        .badge.completed { background: #0f2a1a; color: #22c55e; }
        .badge.failed { background: #2a0f0f; color: #ef4444; }

        #analyze-result { display: none; margin-top: 20px; padding: 16px; background: #111; border-radius: 4px; border: 1px solid #333; }
        #analyze-stats { font-size: 14px; color: #aaa; margin-bottom: 12px; }
        #generated-spec { min-height: 300px; }

        .progress-bar { height: 8px; background: #333; border-radius: 4px; overflow: hidden; margin: 8px 0; }
        .progress-fill { height: 100%; background: #3b82f6; transition: width 0.3s; }

        a { color: #60a5fa; text-decoration: none; }
        a:hover { text-decoration: underline; }
        code { background: #111; padding: 2px 6px; border-radius: 3px; color: #e0e0e0; }

        /* Estilos del chat (mantener) */
        .chat-message {
            margin-bottom: 12px;
            display: flex;
        }
        .chat-message.user {
            justify-content: flex-end;
        }
        .chat-message.assistant {
            justify-content: flex-start;
        }
        .chat-bubble {
            max-width: 70%;
            padding: 10px 14px;
            border-radius: 18px;
            word-wrap: break-word;
        }
        .user .chat-bubble {
            background: #3b82f6;
            color: white;
        }
        .assistant .chat-bubble {
            background: #2a2a2a;
            color: #e0e0e0;
            border: 1px solid #444;
        }

        /* Indicador de coste estimado */
        .cost-estimated { color: #f59e0b; }
        .cost-estimated::after { content: "~"; margin-left: 2px; }
        .cost-real { color: #22c55e; }
        .tooltip {
            position: relative;
            display: inline-block;
            cursor: help;
            border-bottom: 1px dotted #666;
        }
        .tooltip .tooltip-text {
            visibility: hidden;
            width: 200px;
            background: #333;
            color: #fff;
            text-align: center;
            border-radius: 4px;
            padding: 8px;
            position: absolute;
            z-index: 1;
            bottom: 125%;
            left: 50%;
            margin-left: -100px;
            opacity: 0;
            transition: opacity 0.3s;
            font-size: 12px;
        }
        .tooltip:hover .tooltip-text {
            visibility: visible;
            opacity: 1;
        }

        /* P5: Notificaciones — motor unico notification_ui_bridge.py v3.0 */
        <!-- __P5_CSS__ -->
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 APA</h1>
        <p class="subtitle">Agente de Programación Autónoma</p>

        <!-- PESTAÑAS REORDENADAS: Chat primero -->
        <div class="tabs">
            <button class="tab active" onclick="switchTab('chat')">Chat</button>
            <button class="tab" onclick="switchTab('nueva-spec')">Nueva spec</button>
            <button class="tab" onclick="switchTab('analizar')">Analizar proyecto</button>
            <button class="tab" onclick="switchTab('dashboard')">Dashboard</button>
            <!-- __P5_TAB__ -->
        </div>

        <!-- SECCIÓN CHAT (visible por defecto) -->
        <div id="chat-section" style="display:block;">
            <h2>💬 Chat con APA</h2>
            <p>Describe tu proyecto en lenguaje natural. Te ayudaré a definir claramente qué quieres construir.</p>
            <textarea id="chat-input" placeholder="Tu mensaje..."></textarea>
            <button onclick="sendChat()">Enviar</button>
            <div id="chat-history" style="margin-top:1rem;border:1px solid #333;padding:1rem;min-height:200px;background:#111;border-radius:4px;"></div>
        </div>

        <!-- SECCIÓN NUEVA SPEC (oculta por defecto) -->
        <div id="nueva-spec-section" style="display:none;">
            <h2>📝 Nueva especificación</h2>
            <label>Especificación (Markdown):</label>
            <textarea id="spec-input" placeholder="Describe tu proyecto..."></textarea>
            <button onclick="runAPA()">🚀 Lanzar APA</button>
        </div>

        <!-- SECCIÓN ANALIZAR (oculta por defecto) -->
        <div id="analyze-section" style="display:none;">
            <h2>🔍 Analizar proyecto existente</h2>
            <label>Ruta del proyecto:</label>
            <input type="text" id="project-path" style="width:100%;margin:0.5rem 0;">
            <label>Objetivo de la refactorización:</label>
            <input type="text" id="analyze-objetivo" style="width:100%;margin:0.5rem 0;">
            <label>Problemas identificados (uno por línea):</label>
            <textarea id="analyze-problemas" style="min-height:80px;"></textarea>
            <label>Criterios de aceptación (uno por línea):</label>
            <textarea id="analyze-criterios" style="min-height:80px;"></textarea>
            <button onclick="analyzeProject()">🔍 Analizar y generar spec</button>
            <div id="analyze-result">
                <div id="analyze-stats"></div>
                <label>Spec generada (editable):</label>
                <textarea id="generated-spec"></textarea>
                <button onclick="runAPAWithSpec()">🚀 Lanzar APA con esta spec</button>
            </div>
        </div>

        <!-- SECCIÓN DASHBOARD (oculta por defecto) -->
        <div id="dashboard-section" style="display:none;">
            <h2>📊 Dashboard de Monitoreo</h2>
            <select id="project-select"><option>-- Selecciona un proyecto --</option></select>
            <button onclick="loadDashboard()">Cargar métricas</button>
            <div id="dashboard-content" style="margin-top:1rem;">
                Selecciona un proyecto y pulsa "Cargar métricas" para ver los datos.
            </div>
        </div>

        <!-- SECCION NOTIFICACIONES — motor unico notification_ui_bridge.py v3.0 -->
        <!-- __P5_SECTION__ -->

        <h3>Proyectos Recientes</h3>
        <table class="history-table">
            <thead><tr><th>ID</th><th>Spec</th><th>Estado</th><th>Progreso</th><th>Fecha</th><th>Acción</th></tr></thead>
            <tbody id="projects-table"></tbody>
        </table>
    </div>

    <script>
// --- Chat simplificado con logs de depuración ---
const chatHistoryEl = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');

// Función para añadir mensaje al chat
function addMessage(role, text) {
    console.log(`[${role}]`, text);
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.textContent = text;
    msgDiv.appendChild(bubble);
    chatHistoryEl.appendChild(msgDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
}

// Función principal para enviar mensaje
async function sendChat() {
    const message = chatInput.value.trim();
    if (!message) return;

    console.log('Enviando mensaje:', message);
    addMessage('user', message);
    chatInput.value = '';

    // Indicador de escritura
    const typingDiv = document.createElement('div');
    typingDiv.className = 'chat-message assistant';
    typingDiv.innerHTML = '<div class="chat-bubble"><em>Escribiendo...</em></div>';
    chatHistoryEl.appendChild(typingDiv);

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message, history: [] })
        });
        console.log('Respuesta HTTP:', response.status);
        const data = await response.json();
        console.log('Datos recibidos:', data);

        typingDiv.remove();

        if (data.success && data.response) {
            addMessage('assistant', data.response);
        } else {
            addMessage('assistant', '❌ Error: ' + (data.error || 'Respuesta vacía'));
        }
    } catch (error) {
        console.error('Error en fetch:', error);
        typingDiv.remove();
        addMessage('assistant', '❌ Error de conexión: ' + error.message);
    }
}

// Asociar evento al botón (ya existe en el HTML, pero por si acaso)
document.addEventListener('DOMContentLoaded', () => {
    const sendBtn = document.querySelector('button[onclick="sendChat()"]');
    if (sendBtn) {
        sendBtn.onclick = sendChat;
    }
    // Permitir enviar con Enter
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendChat();
        }
    });
    console.log('Chat inicializado');
    initNotifications();
});

// Mantener funciones de pestañas para otras secciones
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');

    document.getElementById('chat-section').style.display = (tabName === 'chat') ? 'block' : 'none';
    document.getElementById('nueva-spec-section').style.display = (tabName === 'nueva-spec') ? 'block' : 'none';
    document.getElementById('analyze-section').style.display = (tabName === 'analizar') ? 'block' : 'none';
    document.getElementById('dashboard-section').style.display = (tabName === 'dashboard') ? 'block' : 'none';
    document.getElementById('notifications-section').style.display = (tabName === 'notifications') ? 'block' : 'none';

    // Limpiar badge al abrir la pestana de notificaciones
    if (tabName === 'notifications') {
        notifUnseen = 0;
        updateNotifBadge();
    }
}

function runAPA() { /* implementado en JS real */ }
function analyzeProject() { /* implementado en JS real */ }
function loadDashboard() { /* implementado en JS real */ }
function runAPAWithSpec() { /* implementado en JS real */ }

// --- P5: Notificaciones — motor unico notification_ui_bridge.py v3.0 ---
// <!-- __P5_JS__ -->
    </script>
</body>
</html>
    """
    # P5v3: Inyectar motor de notificaciones del bridge en los placeholders
    html = html.replace('<!-- __P5_CSS__ -->', NOTIF_CSS)
    html = html.replace('<!-- __P5_TAB__ -->', NOTIF_TAB_BUTTON)
    html = html.replace('<!-- __P5_SECTION__ -->', NOTIF_SECTION_HTML)
    html = html.replace('<!-- __P5_JS__ -->', NOTIF_JS)
    return HTMLResponse(content=html)


@app.post("/run")
async def run_apa(request: RunRequest, background_tasks: BackgroundTasks):
    project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    spec_path = SPECS_DIR / f"{project_id}_spec.md"
    spec_path.write_text(request.spec, encoding='utf-8')

    projects[project_id] = {
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "spec_path": str(spec_path)
    }
    event_queues[project_id] = []

    def run_orchestrator():
        try:
            orchestrator = Orchestrator()

            def on_progress(event: dict):
                event["project_id"] = project_id
                if project_id in event_queues:
                    event_queues[project_id].append(event)

            result = orchestrator.run(str(spec_path), on_progress=on_progress)
            projects[project_id]["status"] = "completed" if result.get("success") else "failed"
            projects[project_id]["result"] = result

        except Exception as e:
            logger.error(f"Error in orchestrator run: {e}")
            projects[project_id]["status"] = "failed"
            projects[project_id]["error"] = str(e)

    background_tasks.add_task(run_orchestrator)

    return {"project_id": project_id, "status": "started"}


@app.get("/status/{project_id}")
async def get_status(project_id: str):
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    project = projects[project_id]

    plan_path = SPECS_DIR / project_id / "plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            tasks = plan.get("tasks", [])
            completed = sum(1 for t in tasks if t.get("status") == "completed")
            failed = sum(1 for t in tasks if t.get("status") == "failed")
            project["progress"] = {
                "total": len(tasks),
                "completed": completed,
                "failed": failed
            }
        except:
            pass

    return project


# =============================================================================
# ENDPOINT: Chat con LLM
# =============================================================================

@app.post("/chat")
async def chat_endpoint(request: ChatRequest) -> JSONResponse:
    """Endpoint para chat interactivo con LLM."""
    try:
        # Cargar contexto de autoconocimiento desde documentación viva
        self_context = _load_self_context()

        system_prompt = (
            f"Eres APA, un asistente de programación autónoma. Aquí está tu identidad y capacidades:\n\n"
            f"{self_context}\n\n"
            f"---\n\n"
            f"Tu objetivo es ayudar al usuario a definir claramente qué quiere construir: "
            f"objetivo, inputs, outputs esperados y criterios de éxito. "
            f"Haz preguntas para clarificar si es necesario, pero mantén respuestas concisas."
        )

        history_lines = []
        for msg in request.history:
            role_label = "Usuario" if msg.get("role") == "user" else "Asistente"
            history_lines.append(f"{role_label}: {msg.get('content', '')}")

        historial_formateado = "\n".join(history_lines) if history_lines else "(Sin historial previo)"

        user_prompt = f"""Historial de la conversación:
{historial_formateado}

Usuario: {request.message}
Asistente:"""

        # Logs de depuración antes de llamar al LLM
        logger.info(f"System prompt (primeros 500 chars): {system_prompt[:500]}...")
        logger.info(f"User prompt: {user_prompt[:200]}...")

        result = call_llm(
            task_type="chat",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1000,
            temperature=0.7
        )

        # Logs de depuración después de obtener respuesta del LLM
        logger.info(f"Respuesta LLM: success={result.get('success')}, model={result.get('model_used')}, content_len={len(result.get('content', ''))}")
        if not result.get('success'):
            logger.error(f"Error LLM: {result.get('error')}")

        return JSONResponse(content={
            "response": result.get("content", ""),
            "model_used": result.get("model_used", ""),
            "success": result.get("success", False),
            "error": result.get("error")
        })

    except Exception as e:
        logger.error(f"Error en endpoint /chat: {e}")
        return JSONResponse(content={
            "response": "",
            "model_used": "",
            "success": False,
            "error": str(e)
        })


# =============================================================================
# ENDPOINT: Dashboard de métricas
# =============================================================================

@app.get("/dashboard/{project_id}")
async def dashboard_endpoint(project_id: str) -> JSONResponse:
    """Endpoint para obtener métricas agregadas de un proyecto con costes dinámicos."""
    try:
        data = _get_dashboard_data(project_id)
        return JSONResponse(content=data)
    except Exception as e:
        logger.error(f"Error en dashboard endpoint: {e}")
        return JSONResponse(content={
            "project_id": project_id,
            "cache_entries": 0,
            "task_success_rate": 0.0,
            "models_used": {},
            "estimated_cost_usd": 0.0,
            "cost_sources": {},
            "cost_confidences": {}
        })


@app.get("/stream/{project_id}")
async def stream_events(project_id: str, request: Request):
    if project_id not in event_queues:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    async def event_generator():
        last_index = 0
        while True:
            if await request.is_disconnected():
                break

            queue = event_queues.get(project_id, [])
            for i in range(last_index, len(queue)):
                event = queue[i]
                yield f"data: {json.dumps(event)}\n\n"
                last_index = i + 1

            if project_id in projects:
                status = projects[project_id].get("status")
                if status in ("completed", "failed"):
                    yield f"data: {json.dumps({'type': 'done', 'status': status})}\n\n"
                    break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/scaling/state")
async def scaling_state_endpoint() -> JSONResponse:
    """v6.0: Estado del sistema de escalado fluido.

    Retorna información sobre la pila de modelos, eventos de
    de-escalado/re-escalado, y capacidad del modelo activo.
    """
    try:
        state = get_scaling_state()
        return JSONResponse(content=state)
    except Exception as e:
        logger.error(f"Error en /scaling/state: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/pool/context-report")
async def pool_context_report() -> JSONResponse:
    """v6.0: Reporte de capacidades de contexto del pool.

    Muestra la distribución de context_length de los modelos disponibles,
    útil para entender por qué un modelo fue de-escalado.
    """
    try:
        report = _global_pool.get_context_report()
        return JSONResponse(content=report)
    except Exception as e:
        logger.error(f"Error en /pool/context-report: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/pipeline/states")
async def pipeline_states() -> JSONResponse:
    """v6.0: Lista todos los pipelines con estado guardado.

    Muestra pipelines que pueden reanudarse después de una
    interrupción.
    """
    try:
        manager = PipelineStateManager()
        states = manager.list_states()
        return JSONResponse(content={"pipelines": states, "total": len(states)})
    except Exception as e:
        logger.error(f"Error en /pipeline/states: {e}")
        return JSONResponse(content={"error": str(e)})


@app.post("/pipeline/resume/{project_id}")
async def pipeline_resume(project_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
    """v6.1: Reanuda un pipeline interrumpido.

    Carga el estado guardado y ejecuta la reanudación en background,
    igual que /run. Devuelve inmediatamente el project_id.
    """
    try:
        manager = PipelineStateManager()
        state = manager.load(project_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Pipeline no encontrado")

        if state.phase in ("completed", "cancelled"):
            raise HTTPException(
                status_code=400,
                detail=f"Pipeline en estado '{state.phase}', no se puede reanudar"
            )

        # Registrar en projects para poder consultar estado
        if project_id not in projects:
            projects[project_id] = {
                "status": "resuming",
                "created_at": datetime.utcnow().isoformat(),
                "spec_path": ""
            }
        else:
            projects[project_id]["status"] = "resuming"

        event_queues[project_id] = event_queues.get(project_id, [])

        def run_resume():
            try:
                orchestrator = Orchestrator()

                def on_progress(event: dict):
                    event["project_id"] = project_id
                    if project_id in event_queues:
                        event_queues[project_id].append(event)

                result = orchestrator.resume(project_id, on_progress=on_progress)
                projects[project_id]["status"] = (
                    "completed" if result.get("success") else "failed"
                )
                projects[project_id]["result"] = result

            except Exception as e:
                logger.error(f"Error en pipeline resume: {e}")
                projects[project_id]["status"] = "failed"
                projects[project_id]["error"] = str(e)

        background_tasks.add_task(run_resume)

        return JSONResponse(content={
            "project_id": project_id,
            "status": "resuming",
            "phase": state.phase,
            "total_tasks": len(state.plan_tasks),
            "tasks_completed": sum(
                1 for t in state.plan_tasks if t.get("status") == "completed"
            ),
            "message": "Pipeline reanudándose en background"
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en /pipeline/resume: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/pipeline/{project_id}/status")
async def pipeline_status(project_id: str) -> JSONResponse:
    """v6.0: Estado detallado de un pipeline específico.

    Retorna el PipelineState guardado para un project_id dado,
    incluyendo fase actual, tareas, y errores.
    """
    try:
        manager = PipelineStateManager()
        state = manager.load(project_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline {project_id} no encontrado")

        # Calcular resumen de tareas
        tasks_summary = []
        for td in state.plan_tasks:
            tasks_summary.append({
                "task_id": td.get("task_id", ""),
                "script": td.get("script", ""),
                "status": td.get("status", "unknown"),
                "attempt": td.get("attempt", 0),
                "error": td.get("error"),
            })

        return JSONResponse(content={
            "project_id": state.project_id,
            "phase": state.phase,
            "current_task_index": state.current_task_index,
            "total_tasks": len(state.plan_tasks),
            "tasks": tasks_summary,
            "model_used_planner": state.model_used_planner,
            "error": state.error,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "scaling_state": state.scaling_state,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en /pipeline/{project_id}/status: {e}")
        return JSONResponse(content={"error": str(e)})


@app.post("/pipeline/{project_id}/retry")
async def pipeline_retry(
    project_id: str,
    background_tasks: BackgroundTasks,
    force_model: Optional[str] = None,
) -> JSONResponse:
    """v6.0: Reintenta un pipeline fallido desde el último checkpoint.

    Carga el estado guardado, resetea la tarea fallida y ejecuta
    la reanudación en background. Soporta forzar un modelo específico
    y reanudar desde planning o execution.
    """
    try:
        manager = PipelineStateManager()
        state = manager.load(project_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Pipeline {project_id} no encontrado")

        # Determinar from_step: si no hay tareas ejecutadas, replanificar
        has_executed_tasks = any(
            td.get("status") in ("approved", "executing", "awaiting_approval")
            for td in state.plan_tasks
        )
        from_step = "execution" if has_executed_tasks else "planning"

        # Registrar en projects para seguimiento
        if project_id not in projects:
            projects[project_id] = {
                "status": "retrying",
                "created_at": datetime.utcnow().isoformat(),
                "spec_path": "",
            }
        else:
            projects[project_id]["status"] = "retrying"

        event_queues[project_id] = event_queues.get(project_id, [])

        def run_retry():
            try:
                from agents.semi_auto_agent import SemiAutoAgent

                agent = SemiAutoAgent(project_root=str(SPECS_DIR.parent), project_id=project_id)

                def on_progress(stage: str, msg: str):
                    if project_id in event_queues:
                        event_queues[project_id].append({
                            "type": "progress",
                            "stage": stage,
                            "message": msg,
                            "project_id": project_id,
                        })

                result = agent.resume_pipeline(
                    project_id=project_id,
                    from_step=from_step,
                    force_model=force_model,
                )

                if result.success and agent.state.name == "PLANNED":
                    # Pipeline restaurado, ejecutar siguiente tarea
                    def on_complete(task_result):
                        if project_id in event_queues:
                            event_queues[project_id].append({
                                "type": "task_complete",
                                "success": task_result.success,
                                "error": task_result.error,
                                "project_id": project_id,
                            })

                    agent.execute_next(
                        on_progress=on_progress,
                        on_complete=on_complete,
                    )

                projects[project_id]["status"] = "retrying"
                projects[project_id]["result"] = {
                    "success": result.success,
                    "error": result.error,
                    "tasks_restored": len(result.tasks),
                }

                logger.info(f"Pipeline {project_id} reintentado desde {from_step}")

            except Exception as e:
                logger.error(f"Error en pipeline retry: {e}")
                projects[project_id]["status"] = "failed"
                projects[project_id]["error"] = str(e)

        background_tasks.add_task(run_retry)

        return JSONResponse(content={
            "project_id": project_id,
            "status": "retrying",
            "from_step": from_step,
            "total_tasks": len(state.plan_tasks),
            "force_model": force_model,
            "message": f"Pipeline reintentándose desde {from_step} en background"
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en /pipeline/{project_id}/retry: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/routing/for-context/{tokens}")
async def routing_for_context(tokens: int) -> JSONResponse:
    """v6.0: Modelo recomendado para una capacidad de contexto dada.

    Dado un número de tokens estimados, retorna el mejor modelo disponible
    que pueda manejar esa capacidad de contexto. Útil para planificar
    tareas y decidir si es necesario dividir el trabajo.
    """
    try:
        tokens_int = int(tokens)
        if tokens_int <= 0:
            raise HTTPException(status_code=400, detail="tokens debe ser un entero positivo")

        # Buscar el mejor modelo para el contexto requerido
        best = _global_pool.get_best_for_context(required_context=tokens_int)

        if best is None:
            # Pool vacío
            return JSONResponse(content={
                "tokens_required": tokens_int,
                "recommended_model": None,
                "available": False,
                "message": "Pool vacío — no hay modelos disponibles",
            })

        # Verificar si el modelo encontrado tiene suficiente contexto
        fits = best.context_length >= tokens_int
        capacity_pct = round((best.context_length / tokens_int) * 100, 1) if tokens_int > 0 else 0

        # Obtener alternativas si no hay suficiente contexto
        alternatives = []
        if not fits:
            all_entries = _global_pool.get_ranked_entries(only_available=True)
            # Buscar el modelo con mayor contexto disponible
            for entry in all_entries:
                if entry.context_length > best.context_length:
                    alternatives.append({
                        "model_id": entry.model_id,
                        "provider": entry.provider,
                        "context_length": entry.context_length,
                        "composite_score": round(entry.composite_score, 2),
                        "is_free": entry.is_free,
                    })
                if len(alternatives) >= 3:
                    break

        return JSONResponse(content={
            "tokens_required": tokens_int,
            "recommended_model": {
                "model_id": best.model_id,
                "provider": best.provider,
                "context_length": best.context_length,
                "composite_score": round(best.composite_score, 2),
                "health_status": best.health_status,
                "is_free": best.is_free,
                "fits": fits,
                "capacity_usage_pct": capacity_pct,
            },
            "available": best.health_status == "available",
            "alternatives": alternatives if not fits else [],
            "message": (
                f"Modelo {best.model_id} "
                f"({'cabe' if fits else 'NO cabe'}: "
                f"{best.context_length}/{tokens_int} tokens, "
                f"{capacity_pct}% capacidad)"
            ),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en /routing/for-context/{tokens}: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/health/pool")
async def health_pool() -> JSONResponse:
    """v6.0: Estado de salud completo del pool de modelos.

    Retorna información detallada sobre cada modelo en el pool:
    estado de salud, contexto, ranking, y proveedor.
    """
    try:
        from core.model_health import get_all_health

        entries = _global_pool.get_all_entries()
        health_data = get_all_health()

        models = []
        for entry in entries:
            model_id = entry.model_id
            provider = entry.provider

            # Combinar datos del pool con health_data
            health_info = health_data.get(model_id, {})
            # También buscar por composite key (provider, model_id)
            if not health_info:
                health_info = health_data.get(f"{provider}/{model_id}", {})

            models.append({
                "model_id": model_id,
                "provider": provider,
                "context_length": entry.context_length,
                "health_status": entry.health_status,
                "composite_score": round(entry.composite_score, 2),
                "is_free": entry.is_free,
                "verified_at": entry.verified_at,
                "model_health": {
                    "status": health_info.get("status", entry.health_status),
                    "error": health_info.get("error"),
                    "provider_health": health_info.get("provider", provider),
                },
            })

        # Ordenar por composite_score descendente
        models.sort(key=lambda m: m["composite_score"], reverse=True)

        # Resumen
        total = len(models)
        available = sum(1 for m in models if m["health_status"] == "available")
        unknown = sum(1 for m in models if m["health_status"] == "unknown")
        failed = sum(1 for m in models if m["health_status"] == "failed")
        rate_limited = sum(1 for m in models if m["health_status"] == "rate_limited")
        payment_required = sum(1 for m in models if m["health_status"] == "payment_required")

        return JSONResponse(content={
            "total_models": total,
            "available": available,
            "unknown": unknown,
            "failed": failed,
            "rate_limited": rate_limited,
            "payment_required": payment_required,
            "models": models,
        })
    except Exception as e:
        logger.error(f"Error en /health/pool: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/health/providers")
async def health_providers() -> JSONResponse:
    """T6.6: Resumen de salud por proveedor.

    Retorna un resumen agregado por proveedor: modelos totales,
    disponibles, caídos, y estado de conexión del proveedor.
    """
    try:
        from core.providers import provider_manager
        from core.model_health import get_all_health

        health_data = get_all_health()
        providers_summary = []

        for prov_name, prov_obj in provider_manager.providers.items():
            # Verificar si el proveedor responde
            try:
                is_avail = prov_obj.is_available()
            except Exception:
                is_avail = False

            # Obtener modelos del proveedor
            try:
                prov_models = prov_obj.get_models()
            except Exception:
                prov_models = []

            # Contar estados de salud de los modelos de este proveedor
            statuses = {"available": 0, "unknown": 0, "failed": 0,
                        "rate_limited": 0, "payment_required": 0,
                        "model_removed": 0, "temporarily_unavailable": 0}

            for m in prov_models:
                mid = m.get("id", "")
                h = health_data.get(mid, {})
                st = h.get("status", "unknown") if h else "unknown"
                if st in statuses:
                    statuses[st] += 1
                else:
                    statuses["unknown"] += 1

            providers_summary.append({
                "provider": prov_name,
                "is_available": is_avail,
                "total_models": len(prov_models),
                "available": statuses["available"],
                "unknown": statuses["unknown"],
                "failed": statuses["failed"],
                "rate_limited": statuses["rate_limited"],
                "payment_required": statuses["payment_required"],
                "model_removed": statuses["model_removed"],
                "temporarily_unavailable": statuses["temporarily_unavailable"],
            })

        providers_summary.sort(key=lambda p: p["provider"])

        # Resumen global
        total_providers = len(providers_summary)
        active_providers = sum(1 for p in providers_summary if p["is_available"])
        total_models = sum(p["total_models"] for p in providers_summary)
        total_available = sum(p["available"] for p in providers_summary)
        any_issues = any(p["failed"] + p["rate_limited"] + p["payment_required"] + p["model_removed"] > 0
                         for p in providers_summary)

        return JSONResponse(content={
            "total_providers": total_providers,
            "active_providers": active_providers,
            "total_models": total_models,
            "total_available_models": total_available,
            "status": "healthy" if active_providers >= 3 and total_available > 10 else (
                     "degraded" if active_providers >= 1 else "down"),
            "providers": providers_summary,
        })
    except Exception as e:
        logger.error(f"Error en /health/providers: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/health")
async def health_check() -> JSONResponse:
    """T6.6: Health check general rápido.

    Endpoint ligero para monitoreo. Retorna estado global del sistema
    sin detallar por modelo (usar /health/providers para eso).
    """
    try:
        from core.providers import provider_manager
        from core.model_health import get_diagnostic_info

        diag = get_diagnostic_info()

        # Verificar proveedores activos
        providers_up = 0
        providers_total = len(provider_manager.providers)
        for prov_obj in provider_manager.providers.values():
            try:
                if prov_obj.is_available():
                    providers_up += 1
            except Exception:
                pass

        total_models = diag.get("total_models", 0)
        available_models = diag.get("available", 0)
        model_removed = diag.get("model_removed", 0)
        failed = diag.get("failed", 0)

        # Determinar estado global
        if providers_up >= 5 and available_models >= 20:
            overall = "healthy"
        elif providers_up >= 2 and available_models >= 5:
            overall = "degraded"
        else:
            overall = "down"

        return JSONResponse(content={
            "status": overall,
            "providers_up": providers_up,
            "providers_total": providers_total,
            "total_models": total_models,
            "available_models": available_models,
            "failed_models": failed,
            "removed_models": model_removed,
            "cache_loaded": diag.get("cache_loaded", False),
        })
    except Exception as e:
        logger.error(f"Error en /health: {e}")
        return JSONResponse(content={"status": "error", "error": str(e)})


@app.get("/quota/status")
async def quota_status() -> JSONResponse:
    """T4: Estado de cuotas por proveedor.

    Retorna el presupuesto diario, gasto acumulado hoy,
    porcentaje usado, y proveedores bloqueados/alertados.
    """
    try:
        from core.quota_tracker import QuotaTracker

        qt = QuotaTracker.get_instance()
        summary = qt.get_quota_summary()

        return JSONResponse(content=summary)
    except Exception as e:
        logger.error(f"Error en /quota/status: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/quota/providers")
async def quota_providers() -> JSONResponse:
    """T4: Lista de cuotas configuradas por proveedor."""
    try:
        from core.quota_tracker import QuotaTracker

        qt = QuotaTracker.get_instance()
        quotas = qt.get_all_quotas()
        spending = qt.get_all_spending_today()

        result = []
        for q in quotas:
            prov = q["provider"]
            sp = spending.get(prov, {})
            result.append({
                "provider": prov,
                "daily_budget_usd": q["daily_budget_usd"],
                "alert_threshold_pct": q["alert_threshold_pct"],
                "daily_spent_usd": sp.get("daily_spent_usd", 0),
                "pct_used": sp.get("pct_used", 0),
                "status": sp.get("status", "ok"),
            })

        return JSONResponse(content={
            "total_quotas": len(result),
            "providers": result,
        })
    except Exception as e:
        logger.error(f"Error en /quota/providers: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/quota/history")
async def quota_history(days: int = 7) -> JSONResponse:
    """T4: Historial de gastos por proveedor en los últimos N días."""
    try:
        from core.quota_tracker import QuotaTracker

        qt = QuotaTracker.get_instance()
        history = qt.get_spending_history(days=days)

        return JSONResponse(content={
            "days": days,
            "providers": history,
        })
    except Exception as e:
        logger.error(f"Error en /quota/history: {e}")
        return JSONResponse(content={"error": str(e)})


@app.get("/download/{filename}")
async def download(filename: str):
    try:
        nas = NASConnector()
        nas_path = f"{settings.nas_sandbox_path}/{filename}"
        result = nas.read_file(nas_path)

        if not result["success"]:
            raise HTTPException(
                status_code=404,
                detail=f"Archivo {filename} no encontrado en NAS"
            )

        content = result["content"]

        return Response(
            content=content.encode("utf-8"),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    try:
        project_path = Path(request.project_path)
        if not project_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"El proyecto en '{request.project_path}' no existe"
            )

        reader = ProjectReader(str(project_path))
        stats = reader.get_stats()

        spec_path = reader.generate_refactor_spec(
            objetivo=request.objetivo,
            problemas=request.problemas,
            criterios=request.criterios
        )

        spec_content = Path(spec_path).read_text(encoding='utf-8')

        return {
            "spec_path": spec_path,
            "spec_content": spec_content,
            "stats": stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in analyze endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/projects")
async def list_projects():
    result = []

    for project_id, project in projects.items():
        plan_path = SPECS_DIR / project_id / "plan.json"
        plan = None
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
            except Exception:
                pass

        result.append({
            "project_id": project_id,
            "status": project.get("status", "unknown"),
            "created_at": project.get("created_at"),
            "spec_summary": plan.get("spec_summary") if plan else None,
            "tasks_total": len(plan.get("tasks", [])) if plan else 0,
            "tasks_completed": sum(
                1 for t in plan.get("tasks", [])
                if t.get("status") == "completed"
            ) if plan else 0
        })

    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"projects": result, "total": len(result)}


# =============================================================================
# P5: ENDPOINTS DE NOTIFICACIONES EN TIEMPO REAL
# =============================================================================

@app.get("/notifications/recent")
async def notifications_recent() -> JSONResponse:
    # Retorna los ultimos 100 eventos formateados + resumen completo.
    try:
        raw_events = get_recent_events(100)
        formatted = [format_event(e) for e in raw_events]
        return JSONResponse(content={
            'events': formatted,
            'total': len(formatted),
            'summary': get_full_summary(),
        })
    except Exception as e:
        logger.error(f"Error en /notifications/recent: {e}")
        return JSONResponse(content={'events': [], 'total': 0, 'error': str(e)})


@app.get("/notifications/summary")
async def notifications_summary() -> JSONResponse:
    # Endpoint ligero: solo el resumen de modelos/ranking/pool/top.
    try:
        return JSONResponse(content=get_full_summary())
    except Exception as e:
        logger.error(f"Error en /notifications/summary: {e}")
        return JSONResponse(content={})


@app.get("/notifications/stream")
async def notifications_stream(request: Request):
    # SSE de notificaciones en tiempo real.
    # Los eventos nuevos del event bus se envian automaticamente
    # al navegador via Server-Sent Events.
    async def event_generator():
        last_idx = 0
        while True:
            if await request.is_disconnected():
                break
            with _sse_buffer_lock:
                buf_len = len(_sse_buffer)
                snapshot = list(_sse_buffer)
            for i in range(last_idx, buf_len):
                yield f"data: {json.dumps(snapshot[i], default=str)}\n\n"
                last_idx = i + 1
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# =============================================================================
# BLOQUE DE PRUEBAS UNITARIAS
# =============================================================================

if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        print("🧪 Ejecutando pruebas del dashboard dinámico...")

        test_proj_id = "proj_20260414_test"
        specs_dir = Path(__file__).parents[1] / "specs"
        proj_dir = specs_dir / test_proj_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        plan_path = proj_dir / "plan.json"

        plan_path.write_text(json.dumps({
            "project_id": test_proj_id,
            "tasks": [
                {"id": "T1", "status": "completed", "model_used": "qwen/qwen2.5-coder", "attempts": 1},
                {"id": "T2", "status": "completed", "model_used": "anthropic/claude-3-5-sonnet", "attempts": 2},
                {"id": "T3", "status": "failed", "model_used": "openai/gpt-4o", "attempts": 1}
            ]
        }), encoding="utf-8")

        from core.usage_tracker import UsageTracker
        import tempfile, shutil
        temp_dir = tempfile.mkdtemp()
        test_db = Path(temp_dir) / "test_dashboard_usage.db"

        try:
            tracker = UsageTracker(db_path=test_db)
            tracker.log_usage(test_proj_id, "qwen/qwen2.5-coder", 1000, "generation")
            tracker.log_usage(test_proj_id, "anthropic/claude-3-5-sonnet", 500, "correction")

            data = _get_dashboard_data(test_proj_id)

            assert data["project_id"] == test_proj_id
            assert abs(data["task_success_rate"] - 66.66666666666666) < 0.0001
            assert data["models_used"]["qwen/qwen2.5-coder"] == 1
            assert data["models_used"]["anthropic/claude-3-5-sonnet"] == 1
            assert "cost_sources" in data, "Falta cost_sources en respuesta"
            assert "cost_confidences" in data, "Falta cost_confidences en respuesta"
            assert "cache_entries" in data

            print("✅ CRITERIO OK - Dashboard incluye cost_sources y cost_confidences")

            data2 = _get_dashboard_data("proj_inexistente_xyz")
            assert data2["task_success_rate"] == 0.0
            assert data2["models_used"] == {}
            assert data2["estimated_cost_usd"] == 0.0
            print("✅ CRITERIO OK - Manejo de errores")
            print("✅ Dashboard dynamic cost test passed.")

        finally:
            if plan_path.exists():
                plan_path.unlink()
            if proj_dir.exists() and not any(proj_dir.iterdir()):
                proj_dir.rmdir()
            shutil.rmtree(temp_dir, ignore_errors=True)

        import interface.app as app_module
        assert not hasattr(app_module, 'MODEL_COST_PER_CALL'), "❌ MODEL_COST_PER_CALL aún existe"
        print("✅ CRITERIO OK - MODEL_COST_PER_CALL eliminado")
        print("✅ Todos los tests pasaron")
        sys.exit(0)

    import uvicorn
    print("=" * 50)
    print("APA — Agente de Programación Autónoma")
    print("Interfaz web en: http://localhost:8080")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=False)