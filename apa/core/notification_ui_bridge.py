# apa/core/notification_ui_bridge.py
# v3.0 — MOTOR UNICO DE RENDERIZADO DE NOTIFICACIONES
#
# Este modulo es el UNICO lugar donde se define como se ven las notificaciones.
# Tanto app.py (FastAPI/web) como ensamblador_gui.py (tkinter) consumen
# este mismo codigo. Cero logica de render duplicada.
#
# Lo que contiene este motor:
#   1) Datos: format_event(), get_full_summary(), get_event_color(), etc.
#   2) Web:   NOTIF_CSS, NOTIF_SECTION_HTML, NOTIF_JS — todo el HTML/CSS/JS
#   3) Tkinter: render_events_to_text(), configure_tkinter_tags(),
#              get_summary_display_data()
#
# Si cambias un color, un layout o un formato AQUI, ambas interfaces
# se actualizan automaticamente.
#
# USO (app.py):
#   from core.notification_ui_bridge import (
#       NOTIF_CSS, NOTIF_TAB_BUTTON, NOTIF_SECTION_HTML, NOTIF_JS,
#       format_event, get_full_summary, get_event_summary,
#       create_bridge_callback, EVENT_TYPES_LIST,
#   )
#
# USO (ensamblador_gui.py):
#   from core.notification_ui_bridge import (
#       configure_tkinter_tags, render_events_to_text,
#       get_summary_display_data, SUMMARY_LABELS_CONFIG,
#       format_event, get_full_summary, get_event_summary,
#       create_bridge_callback, EVENT_TYPES_LIST,
#       EVENT_LABEL_MAP, EVENT_PREFIX_COLOR_MAP, EVENT_SPECIFIC_COLOR_MAP,
#   )
#
# ARCHIVO: notification_ui_bridge.py
# DESTINO: apa/core/notification_ui_bridge.py

import sys
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Callable

# Import seguro: funciona en 3 escenarios:
#   1) Directo:  python apa/core/notification_ui_bridge.py
#   2) Modulo:   from core.notification_ui_bridge import ...  (sys.path apunta a apa/)
#   3) Absoluto: from apa.core.notification_ui_bridge import ...
_here = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_here)       # apa/
_grandparent = os.path.dirname(_parent) # APA/
for _p in (_parent, _grandparent):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# CRITICAL: Deduplication of module references.
if 'apa.core.notifications' in sys.modules and 'core.notifications' not in sys.modules:
    sys.modules['core.notifications'] = sys.modules['apa.core.notifications']
elif 'core.notifications' in sys.modules and 'apa.core.notifications' not in sys.modules:
    sys.modules['apa.core.notifications'] = sys.modules['core.notifications']
elif ('apa.core.notifications' in sys.modules and 'core.notifications' in sys.modules
      and sys.modules['apa.core.notifications'] is not sys.modules['core.notifications']):
    sys.modules['core.notifications'] = sys.modules['apa.core.notifications']

from core.notifications import (
    register_callback, unregister_callback,
    get_recent_events, get_events_by_type,
    EVT_HEALTH_MODEL_VERIFIED, EVT_HEALTH_MODEL_FAILED,
    EVT_HEALTH_MODEL_RATE_LIMITED, EVT_HEALTH_MODEL_REMOVED,
    EVT_HEALTH_CYCLE_START, EVT_HEALTH_CYCLE_END,
    EVT_HEALTH_FLUSH_DISK, EVT_HEALTH_CACHE_LOADED,
    EVT_HEALTH_POOL_SYNCED,
    EVT_ARENA_REFRESH_START, EVT_ARENA_REFRESH_COMPLETE,
    EVT_ARENA_REFRESH_FAILED, EVT_ARENA_CACHE_LOADED,
    EVT_ARENA_CATEGORY_LOADED, EVT_ARENA_TOP_MODELS,
    EVT_POOL_POPULATED, EVT_POOL_MODEL_UPDATED, EVT_POOL_SYNC_BATCH,
    EVT_SYSTEM_SHUTDOWN, EVT_SYSTEM_ERROR, EVT_SYSTEM_STARTUP,
)


# ============================================================================
# CONSTANTES COMPARTIDAS — colores, etiquetas, configuracion del resumen
# ============================================================================

EVENT_PREFIX_COLOR_MAP = {
    'health': '#3b82f6',    # Azul
    'arena':  '#14b8a6',    # Teal
    'pool':   '#8b5cf6',    # Purpura
    'system': '#ef4444',    # Rojo
}

EVENT_SPECIFIC_COLOR_MAP = {
    EVT_HEALTH_MODEL_VERIFIED:    '#22c55e',
    EVT_HEALTH_MODEL_FAILED:      '#ef4444',
    EVT_HEALTH_MODEL_RATE_LIMITED: '#f59e0b',
    EVT_HEALTH_MODEL_REMOVED:     '#a855f7',
    EVT_ARENA_REFRESH_COMPLETE:   '#22c55e',
    EVT_ARENA_REFRESH_FAILED:     '#ef4444',
    EVT_ARENA_CATEGORY_LOADED:    '#06b6d4',
    EVT_ARENA_TOP_MODELS:         '#0ea5e9',
    EVT_SYSTEM_ERROR:             '#ef4444',
    EVT_SYSTEM_SHUTDOWN:          '#f59e0b',
    EVT_SYSTEM_STARTUP:           '#64748b',
}

EVENT_LABEL_MAP = {
    'health': 'Salud',
    'arena':  'Arena',
    'pool':   'Pool',
    'system': 'Sistema',
}

EVENT_TYPES_LIST = [
    EVT_HEALTH_MODEL_VERIFIED, EVT_HEALTH_MODEL_FAILED,
    EVT_HEALTH_MODEL_RATE_LIMITED, EVT_HEALTH_MODEL_REMOVED,
    EVT_HEALTH_CYCLE_START, EVT_HEALTH_CYCLE_END,
    EVT_HEALTH_FLUSH_DISK, EVT_HEALTH_CACHE_LOADED,
    EVT_HEALTH_POOL_SYNCED,
    EVT_ARENA_REFRESH_START, EVT_ARENA_REFRESH_COMPLETE,
    EVT_ARENA_REFRESH_FAILED, EVT_ARENA_CACHE_LOADED,
    EVT_ARENA_CATEGORY_LOADED, EVT_ARENA_TOP_MODELS,
    EVT_POOL_POPULATED, EVT_POOL_MODEL_UPDATED, EVT_POOL_SYNC_BATCH,
    EVT_SYSTEM_SHUTDOWN, EVT_SYSTEM_ERROR, EVT_SYSTEM_STARTUP,
]

# Configuracion de labels del resumen: (key en summary, etiqueta visible, color)
SUMMARY_LABELS_CONFIG = [
    ('total',                  'Total',         '#d4d4d4'),
    ('available',              'Disponibles',   '#22c55e'),
    ('unknown',                'Sin verificar', '#f59e0b'),
    ('payment_required',       'Sin creditos',  '#ef4444'),
    ('rate_limited',           'Rate limit',    '#fb923c'),
    ('failed',                 'Fallos',        '#dc2626'),
    ('model_removed',          'Eliminados',    '#a855f7'),
    ('temporarily_unavailable','Temp.no disp.', '#94a3b8'),
]


# ============================================================================
# FUNCIONES CORE — formato, resumen, callback puente
# ============================================================================

def get_event_color(event_type: str) -> str:
    """Retorna el color hex para un tipo de evento."""
    specific = EVENT_SPECIFIC_COLOR_MAP.get(event_type)
    if specific:
        return specific
    prefix = event_type.split(':')[0] if ':' in event_type else 'system'
    return EVENT_PREFIX_COLOR_MAP.get(prefix, '#9ca3af')


def get_event_label(event_type: str) -> str:
    """Retorna la etiqueta legible para un tipo de evento."""
    prefix = event_type.split(':')[0] if ':' in event_type else 'system'
    return EVENT_LABEL_MAP.get(prefix, prefix.capitalize())


_MAX_MSG_LENGTH = 130


def _compact_list(items: list, max_show: int = 5) -> str:
    """Compacta una lista larga de strings."""
    if not items:
        return ''
    if len(items) <= max_show:
        return ', '.join(items)
    shown = ', '.join(str(x) for x in items[:max_show])
    return f"{shown} +{len(items) - max_show} mas"


def _truncate_message(msg: str, max_len: int = _MAX_MSG_LENGTH) -> str:
    """Trunca un mensaje si excede max_len caracteres."""
    if len(msg) <= max_len:
        return msg
    for delim in (')', ']', '}'):
        idx = msg.rfind(delim, 0, max_len)
        if idx > max_len * 0.5:
            return msg[:idx + 1] + '...'
    idx = msg.rfind(',', 0, max_len)
    if idx > max_len * 0.5:
        return msg[:idx] + '...'
    idx = msg.rfind('.', 0, max_len)
    if idx > max_len * 0.5:
        return msg[:idx + 1] + '..'
    idx = msg.rfind(' ', 0, max_len)
    if idx > max_len * 0.4:
        return msg[:idx] + '...'
    return msg[:max_len - 3] + '...'


def format_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Formatea un evento crudo del event bus para presentacion UI."""
    evt_type = event.get('type', '')
    ts = event.get('timestamp', time.time())
    raw_msg = event.get('message', '')
    data = event.get('data', {})

    try:
        time_str = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
    except (ValueError, OSError):
        time_str = '--:--:--'

    prefix = evt_type.split(':')[0] if ':' in evt_type else 'system'

    if 'categories' in data and isinstance(data['categories'], (list, dict)):
        cats = list(data['categories'].keys()) if isinstance(data['categories'], dict) else data['categories']
        compacted = _compact_list(sorted(cats), max_show=5)
        import re as _re
        raw_msg = _re.sub(r'\([^)]{20,}\)$', f'({compacted})', raw_msg)

    msg = _truncate_message(raw_msg)

    return {
        'type':      evt_type,
        'message':   msg,
        'data':      data,
        'timestamp': ts,
        'time_str':  time_str,
        'color':     get_event_color(evt_type),
        'category':  get_event_label(evt_type),
        'prefix':    prefix,
    }


def get_event_summary() -> Dict[str, Any]:
    """Retorna estadisticas de los eventos en el buffer."""
    events = get_recent_events(50)
    summary: Dict[str, Any] = {'total': len(events), 'by_prefix': {}}
    for e in events:
        p = e.get('type', '').split(':')[0] if ':' in e.get('type', '') else 'system'
        summary['by_prefix'][p] = summary['by_prefix'].get(p, 0) + 1
    return summary


def _dedup_module(short_name: str) -> None:
    s1 = f'core.{short_name}'
    s2 = f'apa.core.{short_name}'
    if s1 in sys.modules and s2 in sys.modules and sys.modules[s1] is not sys.modules[s2]:
        sys.modules[s1] = sys.modules[s2]
    elif s1 in sys.modules and s2 not in sys.modules:
        sys.modules[s2] = sys.modules[s1]
    elif s2 in sys.modules and s1 not in sys.modules:
        sys.modules[s1] = sys.modules[s2]


def get_full_summary() -> Dict[str, Any]:
    """Resumen completo de modelos, ranking, pool, providers y top modelos.

    Consumido por ambas interfaces (app.py y ensamblador_gui.py).
    """
    for _m in ('notifications', 'pool', 'providers', 'router',
               'arena_fetcher', 'model_health'):
        _dedup_module(_m)

    result: Dict[str, Any] = {
        'models': {}, 'arena': {}, 'pool': {},
        'providers': {}, 'top_planning': [], 'top_coding': [],
    }

    try:
        from core.model_health import get_diagnostic_info
        diag = get_diagnostic_info()
        result['models'] = {
            'total':                   diag.get('total_models', 0),
            'available':               diag.get('available', 0),
            'unknown':                 diag.get('unknown', 0),
            'payment_required':        diag.get('payment_required', 0),
            'rate_limited':            diag.get('rate_limited', 0),
            'failed':                  diag.get('failed', 0),
            'model_removed':           diag.get('model_removed', 0),
            'temporarily_unavailable': diag.get('temporarily_unavailable', 0),
        }
    except Exception:
        pass

    try:
        from core.arena_fetcher import is_arena_ranking_available
        result['arena']['available'] = is_arena_ranking_available()
    except Exception:
        result['arena']['available'] = False

    try:
        from core.arena_fetcher import _arena_data, _refresh_lock
        with _refresh_lock:
            result['arena']['total_ranked'] = len(_arena_data)
    except Exception:
        result['arena']['total_ranked'] = 0

    _pool_obj = None
    try:
        from core.pool import pool as _pool_singleton
        _pool_obj = _pool_singleton
    except Exception:
        pass
    if _pool_obj is None:
        try:
            from apa.core.pool import pool as _pool_singleton
            _pool_obj = _pool_singleton
        except Exception:
            pass
    if _pool_obj is None:
        try:
            from core.router import _global_pool
            _pool_obj = _global_pool
        except Exception:
            pass
    try:
        if _pool_obj is not None:
            all_entries = _pool_obj.get_all_entries()
            result['pool']['total'] = len(all_entries)
            result['pool']['available'] = sum(
                1 for e in all_entries if e.health_status == 'available'
            )
            result['pool']['with_arena_score'] = sum(
                1 for e in all_entries if e.arena_score is not None
            )
    except Exception:
        result['pool'] = {'total': 0, 'available': 0, 'with_arena_score': 0}

    _prov_manager = None
    try:
        from core.providers import provider_manager as _pm
        _prov_manager = _pm
    except Exception:
        pass
    if _prov_manager is None:
        try:
            from apa.core.providers import provider_manager as _pm
            _prov_manager = _pm
        except Exception:
            pass
    try:
        if _prov_manager is not None:
            prov_list = []
            active_count = 0
            for name, prov_obj in _prov_manager.providers.items():
                is_avail = prov_obj.is_available()
                if is_avail:
                    active_count += 1
                model_count = 0
                try:
                    model_count = len(prov_obj.get_models())
                except Exception:
                    pass
                prov_list.append({
                    'name': name, 'available': is_avail,
                    'models': model_count, 'confidence': prov_obj.confidence_score,
                })
            prov_list.sort(key=lambda x: (-1 if x['available'] else 0, -x['confidence']))
            result['providers'] = {
                'active': active_count,
                'total': len(_prov_manager.providers),
                'list': prov_list[:10],
            }
    except Exception:
        result['providers'] = {'active': 0, 'total': 0, 'list': []}

    for task_key in ('top_planning', 'top_coding'):
        task_type = 'planning' if task_key == 'top_planning' else 'coding'
        top_list = []
        try:
            if _pool_obj is None:
                try:
                    from core.pool import pool as _pool_singleton
                    _pool_obj = _pool_singleton
                except Exception:
                    try:
                        from apa.core.pool import pool as _pool_singleton
                        _pool_obj = _pool_singleton
                    except Exception:
                        pass
            if _pool_obj is None:
                continue
            ranked = _pool_obj.get_ranked_entries(
                task_type=task_type, only_available=True)
            if not ranked:
                ranked = _pool_obj.get_ranked_entries(
                    task_type=task_type, only_available=False,
                    exclude_statuses=['payment_required', 'failed'])
            for entry in ranked[:3]:
                model_name = entry.model_id
                if '/' in model_name:
                    model_name = model_name.split('/', 1)[1]
                if ':' in model_name:
                    model_name = model_name.split(':', 1)[1]
                top_list.append({
                    'name':     model_name,
                    'score':    round(entry.task_score(task_type), 1),
                    'health':   entry.health_status,
                    'provider': entry.provider,
                })
        except Exception:
            pass
        result[task_key] = top_list

    return result


def create_bridge_callback(
    on_formatted_event: Callable[[Dict[str, Any]], None]
) -> Callable:
    """Crea y registra un callback puente."""
    _dedup_module('notifications')

    def _bridge_cb(event_type, message, data):
        formatted = format_event({
            'type': event_type,
            'message': message,
            'data': data or {},
            'timestamp': time.time(),
        })
        try:
            on_formatted_event(formatted)
        except Exception:
            pass

    register_callback(_bridge_cb)
    return _bridge_cb


# ============================================================================
# MOTOR DE RENDERIZADO WEB — HTML/CSS/JS
# ============================================================================
# Toda la visual de notificaciones de app.py esta aqui.
# app.py solo inyecta estas constantes en su HTML template.
# ============================================================================

NOTIF_CSS = """
/* P5: Notificaciones — motor unico notification_ui_bridge.py */
.notif-item {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 8px 12px; border-left: 3px solid #444;
    margin-bottom: 4px; border-radius: 0 4px 4px 0;
    background: #111; transition: background 0.2s;
}
.notif-item:hover { background: #1a1a1a; }
.notif-time { color: #888; font-family: monospace; white-space: nowrap; min-width: 65px; }
.notif-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #fff; white-space: nowrap; }
.notif-msg { color: #d4d4d4; flex: 1; word-break: break-word; }
#notif-list { background: #0a0a0a; border: 1px solid #333; border-radius: 4px; max-height: 500px; overflow-y: auto; padding: 8px; font-size: 13px; }
#notif-tab-badge { background: #ef4444; color: white; font-size: 11px; padding: 1px 6px; border-radius: 10px; margin-left: 6px; font-weight: 600; }
"""

NOTIF_TAB_BUTTON = """<button class="tab" id="notif-tab" onclick="switchTab('notifications')">Notificaciones<span id="notif-tab-badge" style="display:none;"></span></button>"""

NOTIF_SECTION_HTML = """
        <!-- SECCION NOTIFICACIONES — motor: notification_ui_bridge.py -->
        <div id="notifications-section" style="display:none;">
            <h2>&#x1F4E2; Notificaciones en Tiempo Real</h2>

            <!-- Panel resumen de modelos -->
            <div id="notif-summary" style="background:#111;border:1px solid #333;border-radius:6px;padding:12px;margin-bottom:12px;font-size:13px;">
                <div style="margin-bottom:8px;">
                    <span style="color:#888;font-size:12px;">MODELOS</span>
                    <span id="sm-total" style="margin-left:12px;color:#d4d4d4;font-weight:600;">Total: --</span>
                    <span id="sm-avail" style="margin-left:12px;color:#22c55e;">Disponibles: --</span>
                    <span id="sm-unknown" style="margin-left:12px;color:#f59e0b;">Sin verificar: --</span>
                    <span id="sm-payment" style="margin-left:12px;color:#ef4444;">Sin creditos: --</span>
                    <span id="sm-ratelimit" style="margin-left:12px;color:#fb923c;">Rate limit: --</span>
                    <span id="sm-failed" style="margin-left:12px;color:#dc2626;">Fallos: --</span>
                </div>
                <div style="margin-bottom:8px;">
                    <span style="color:#888;font-size:12px;">INFRAESTRUCTURA</span>
                    <span id="sm-arena" style="margin-left:12px;color:#14b8a6;">Ranking Arena: --</span>
                    <span id="sm-pool" style="margin-left:12px;color:#8b5cf6;">Pool: --</span>
                    <span id="sm-poolavail" style="margin-left:12px;color:#8b5cf6;">Pool dispon.: --</span>
                    <span id="sm-poolarena" style="margin-left:12px;color:#06b6d4;">Pool c/Arena: --</span>
                </div>
                <div style="margin-bottom:8px;">
                    <span style="color:#888;font-size:12px;">PROVEEDORES</span>
                    <span id="sm-provactive" style="margin-left:12px;color:#22c55e;">Activos: --</span>
                    <span id="sm-provtotal" style="margin-left:12px;color:#94a3b8;">Total: --</span>
                    <span id="sm-provlist" style="margin-left:12px;color:#d4d4d4;"></span>
                </div>
                <div style="margin-bottom:4px;">
                    <span style="color:#888;font-size:12px;">TOP PLANIFICACION</span>
                    <span id="sm-topplan" style="margin-left:12px;color:#3b82f6;">--</span>
                </div>
                <div>
                    <span style="color:#888;font-size:12px;">TOP CODIGO</span>
                    <span id="sm-topcode" style="margin-left:12px;color:#22c55e;">--</span>
                </div>
            </div>

            <div style="margin-bottom:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
                <label style="margin:0;color:#aaa;">Filtrar:</label>
                <select id="notif-filter" onchange="setNotifFilter(this.value)" style="padding:6px 12px;border:1px solid #444;border-radius:4px;background:#111;color:#e0e0e0;font-size:14px;">
                    <option value="all">Todos</option>
                    <option value="health">Salud</option>
                    <option value="arena">Arena</option>
                    <option value="pool">Pool</option>
                    <option value="system">Sistema</option>
                </select>
                <span id="notif-count" style="color:#888;font-size:14px;">0 eventos</span>
                <button class="secondary" onclick="clearNotifDisplay()" style="margin-left:auto;padding:6px 16px;font-size:13px;">Limpiar</button>
            </div>
            <div id="notif-list"></div>
        </div>
"""

NOTIF_JS = """
// --- P5: Notificaciones en tiempo real (SSE) — motor: notification_ui_bridge.js ---
let notifEvents = [];
let notifFilter = 'all';
let notifUnseen = 0;

function initNotifications() {
    fetch('/notifications/recent')
        .then(r => r.json())
        .then(data => {
            notifEvents = (data.events || []).reverse();
            renderNotifSummary(data.summary || {});
            renderNotifications();
        })
        .catch(() => {});

    const es = new EventSource('/notifications/stream');
    es.onmessage = function(e) {
        try {
            const evt = JSON.parse(e.data);
            notifEvents.unshift(evt);
            if (notifEvents.length > 100) notifEvents.pop();
            notifUnseen++;
            updateNotifBadge();
            if (document.getElementById('notifications-section').style.display !== 'none') {
                renderNotifications();
            }
        } catch(err) {}
    };
    es.onerror = function() { setTimeout(function() { es.close(); }, 5000); };

    setInterval(refreshNotifSummary, 15000);
}

function refreshNotifSummary() {
    fetch('/notifications/summary')
        .then(r => r.json())
        .then(data => {
            if (data) renderNotifSummary(data);
        })
        .catch(() => {});
}

function renderNotifSummary(s) {
    if (!s) return;
    const m = s.models || {};
    const a = s.arena || {};
    const p = s.pool || {};
    const pv = s.providers || {};
    const el = (id) => document.getElementById(id);
    if (el('sm-total')) el('sm-total').textContent = 'Total: ' + (m.total || 0);
    if (el('sm-avail')) el('sm-avail').textContent = 'Disponibles: ' + (m.available || 0);
    if (el('sm-unknown')) el('sm-unknown').textContent = 'Sin verificar: ' + (m.unknown || 0);
    if (el('sm-payment')) el('sm-payment').textContent = 'Sin creditos: ' + (m.payment_required || 0);
    if (el('sm-ratelimit')) el('sm-ratelimit').textContent = 'Rate limit: ' + (m.rate_limited || 0);
    if (el('sm-failed')) el('sm-failed').textContent = 'Fallos: ' + (m.failed || 0);
    if (el('sm-arena')) el('sm-arena').textContent = 'Ranking Arena: ' + (a.total_ranked || 0);
    if (el('sm-pool')) el('sm-pool').textContent = 'Pool: ' + (p.total || 0);
    if (el('sm-poolavail')) el('sm-poolavail').textContent = 'Pool dispon.: ' + (p.available || 0);
    if (el('sm-poolarena')) el('sm-poolarena').textContent = 'Pool c/Arena: ' + (p.with_arena_score || 0);

    if (el('sm-provactive')) el('sm-provactive').textContent = 'Activos: ' + (pv.active || 0) + '/' + (pv.total || 0);
    if (el('sm-provtotal')) el('sm-provtotal').textContent = '';
    const provNames = (pv.list || []).filter(pr => pr.available).slice(0, 6).map(pr => pr.name).join(', ');
    if (el('sm-provlist')) el('sm-provlist').textContent = provNames || '--';

    const topPlan = (s.top_planning || []);
    const topCode = (s.top_coding || []);
    if (el('sm-topplan')) {
        el('sm-topplan').textContent = topPlan.length
            ? topPlan.map((t, i) => '#' + (i+1) + ' ' + t.name + ' (' + t.score + ')').join('  |  ')
            : '--';
    }
    if (el('sm-topcode')) {
        el('sm-topcode').textContent = topCode.length
            ? topCode.map((t, i) => '#' + (i+1) + ' ' + t.name + ' (' + t.score + ')').join('  |  ')
            : '--';
    }
}

function renderNotifications() {
    const container = document.getElementById('notif-list');
    if (!container) return;
    const filtered = notifFilter === 'all'
        ? notifEvents
        : notifEvents.filter(e => e.prefix === notifFilter);
    container.innerHTML = '';
    if (filtered.length === 0) {
        container.innerHTML = '<div style="color:#666;padding:20px;text-align:center;">Sin eventos' +
            (notifFilter !== 'all' ? ' en esta categoria' : '') + '</div>';
    }
    for (const e of filtered) {
        const div = document.createElement('div');
        div.className = 'notif-item';
        div.style.borderLeftColor = e.color;
        div.innerHTML =
            '<span class="notif-time">' + e.time_str + '</span>' +
            '<span class="notif-badge" style="background:' + e.color + '">' + e.category + '</span>' +
            '<span class="notif-msg">' + e.message + '</span>';
        container.appendChild(div);
    }
    document.getElementById('notif-count').textContent = filtered.length + ' eventos';
}

function updateNotifBadge() {
    const badge = document.getElementById('notif-tab-badge');
    if (badge && notifUnseen > 0) {
        badge.textContent = notifUnseen > 99 ? '99+' : notifUnseen;
        badge.style.display = 'inline';
    } else if (badge) {
        badge.style.display = 'none';
    }
}

function setNotifFilter(val) {
    notifFilter = val;
    notifUnseen = 0;
    updateNotifBadge();
    renderNotifications();
}

function clearNotifDisplay() {
    notifEvents = [];
    notifUnseen = 0;
    updateNotifBadge();
    const container = document.getElementById('notif-list');
    if (container) container.innerHTML = '';
    document.getElementById('notif-count').textContent = '0 eventos';
}
"""


# ============================================================================
# MOTOR DE RENDERIZADO TKINTER — usado por ensamblador_gui.py
# ============================================================================
# Estas funciones renderizan eventos en un tk.Text widget usando los
# mismos colores, mismos formatos y misma logica que la web.
# el ensamblador NO tiene codigo de render propio: solo llama al bridge.
# ============================================================================

def _get_badge_tag(event_type: str) -> str:
    """Retorna el tag de badge para un tipo de evento."""
    if event_type in EVENT_SPECIFIC_COLOR_MAP:
        return "badge_" + event_type.replace(":", "_")
    prefix = event_type.split(":")[0] if ":" in event_type else "system"
    return "badge_" + prefix


def _get_msg_tag(event_type: str) -> str:
    """Retorna el tag de mensaje para un tipo de evento."""
    prefix = event_type.split(":")[0] if ":" in event_type else "system"
    return "msg_" + prefix


def configure_tkinter_tags(text_widget) -> None:
    """Configura los tags de color en un tk.Text widget.

    Debe llamarse UNA VEZ al crear el widget.
    Usa los mismos colores que EVENT_PREFIX_COLOR_MAP y EVENT_SPECIFIC_COLOR_MAP.
    """
    text_widget.tag_configure("time_tag",
        foreground="#888", font=("Consolas", 10))
    # Tags por prefijo
    for prefix, color in EVENT_PREFIX_COLOR_MAP.items():
        text_widget.tag_configure("badge_" + prefix,
            foreground=color, font=("Segoe UI", 10, "bold"))
        text_widget.tag_configure("msg_" + prefix,
            foreground="#d4d4d4", font=("Segoe UI", 10))
    # Tags especificos por tipo de evento (sobreescriben prefijo)
    for evt_type, color in EVENT_SPECIFIC_COLOR_MAP.items():
        tag_name = "badge_" + evt_type.replace(":", "_")
        text_widget.tag_configure(tag_name,
            foreground=color, font=("Segoe UI", 10, "bold"))
    # Separador sutil entre eventos
    text_widget.tag_configure("separator",
        foreground="#1a1a1a", font=("Segoe UI", 2))


def render_events_to_text(text_widget, formatted_events: List[Dict[str, Any]],
                          filter_prefix: str = None) -> int:
    """Renderiza eventos formateados en un tk.Text widget.

    Esta es la misma funcion que usa la web (renderNotifications en JS)
    pero para tkinter. Misma logica, mismo formato, mismos colores.

    Args:
        text_widget: tk.Text ya configurado con configure_tkinter_tags()
        formatted_events: lista de dicts de format_event()
        filter_prefix: si no es None, solo muestra eventos de ese prefijo

    Returns:
        Numero de eventos mostrados.
    """
    text_widget.config(state="normal")
    text_widget.delete("1.0", "end")

    shown = 0
    for evt in formatted_events:
        if filter_prefix and evt.get("prefix") != filter_prefix:
            continue
        _render_single_event(text_widget, evt)
        shown += 1

    if filter_prefix and shown == 0:
        text_widget.insert("end",
            f"  -- Sin eventos en categoria '{filter_prefix}' --\n",
            "time_tag")

    text_widget.config(state="disabled")
    text_widget.see("1.0")
    return shown


def _render_single_event(text_widget, evt: Dict[str, Any]) -> None:
    """Renderiza un solo evento como tarjeta con borde izquierdo de color.

    Formato visual identico a la web:
      ┃ HH:MM:SS  [CATEGORIA]  mensaje
      ─────────────────────────────────
    """
    evt_type = evt.get("type", "")
    color = evt.get("color", "#9ca3af")

    # Tag dinamico para el borde (color del evento)
    border_tag = "border_" + evt_type.replace(":", "_")
    text_widget.tag_configure(border_tag,
        foreground=color, font=("Segoe UI", 12, "bold"))

    badge_tag = _get_badge_tag(evt_type)
    msg_tag = _get_msg_tag(evt_type)

    text_widget.insert("end", " \u2503 ", border_tag)             # ┃ borde izquierdo
    text_widget.insert("end", evt.get("time_str", "--:--:--") + "  ", "time_tag")
    text_widget.insert("end", evt.get("category", "") + "  ", badge_tag)
    text_widget.insert("end", evt.get("message", "") + "\n", msg_tag)
    text_widget.insert("end", " \u2500" * 60 + "\n", "separator")  # ─── separador


def get_summary_display_data(summary_data: Dict[str, Any]) -> Dict[str, str]:
    """Retorna un dict clave->texto con los datos de resumen formateados.

    Consumido por ensamblador_gui.py para actualizar sus labels.
    Las claves coinciden con SUMMARY_LABELS_CONFIG + keys extra.

    Returns:
        {
            'total': '42', 'available': '38', ...,
            'arena_ranked': '371', 'arena_available': 'Si',
            'pool_total': '150', 'pool_available': '120', 'pool_arena': '85',
            'prov_active': '3/5', 'prov_names': 'openrouter, together',
            'top_planning': '#1 gpt-4o (95.3)  #2 ...',
            'top_coding': '#1 claude (92.1)  #2 ...',
            'status': 'Modelos: 38 disponibles de 42 totales | ...',
        }
    """
    m = summary_data.get('models', {})
    a = summary_data.get('arena', {})
    p = summary_data.get('pool', {})
    pv = summary_data.get('providers', {})

    result = {}

    # Modelos
    for key, label, color in SUMMARY_LABELS_CONFIG:
        result[key] = str(m.get(key, 0))

    # Infraestructura
    result['arena_ranked'] = str(a.get('total_ranked', 0))
    result['arena_available'] = "Si" if a.get('available') else "No"
    result['pool_total'] = str(p.get('total', 0))
    result['pool_available'] = str(p.get('available', 0))
    result['pool_arena'] = str(p.get('with_arena_score', 0))

    # Providers
    result['prov_active'] = f"{pv.get('active', 0)}/{pv.get('total', 0)}"
    prov_names = [pr['name'] for pr in pv.get('list', []) if pr.get('available')][:6]
    result['prov_names'] = ", ".join(prov_names) if prov_names else "Sin providers activos"

    # Top 3 planificacion
    tp = summary_data.get('top_planning', [])
    result['top_planning'] = "  ".join(
        f"#{i+1} {t['name']} ({t['score']})" for i, t in enumerate(tp)
    ) if tp else "--"

    # Top 3 codigo
    tc = summary_data.get('top_coding', [])
    result['top_coding'] = "  ".join(
        f"#{i+1} {t['name']} ({t['score']})" for i, t in enumerate(tc)
    ) if tc else "--"

    # Barra de estado
    result['status'] = (
        f"Modelos: {m.get('available',0)} disponibles de "
        f"{m.get('total',0)} totales | "
        f"Ranking: {a.get('total_ranked',0)} | "
        f"Pool: {p.get('total',0)}"
    )

    return result


# ============================================================================
# Test standalone
# ============================================================================

if __name__ == "__main__":
    from core.notifications import notify

    print("\n" + "=" * 60)
    print("TEST: notification_ui_bridge v3.0")
    print("=" * 60)

    # --- Tests core ---
    c1 = get_event_color(EVT_HEALTH_MODEL_VERIFIED)
    assert c1 == '#22c55e', f"Esperaba #22c55e, obtuve {c1}"
    print("  [PASS] get_event_color() tipo especifico -> verde")

    c2 = get_event_color(EVT_HEALTH_CYCLE_START)
    assert c2 == '#3b82f6', f"Esperaba #3b82f6, obtuve {c2}"
    print("  [PASS] get_event_color() prefijo health -> azul")

    l1 = get_event_label(EVT_ARENA_REFRESH_START)
    assert l1 == 'Arena', f"Esperaba Arena, obtuve {l1}"
    l2 = get_event_label(EVT_SYSTEM_ERROR)
    assert l2 == 'Sistema', f"Esperaba Sistema, obtuve {l2}"
    print("  [PASS] get_event_label() retorna etiquetas correctas")

    test_evt = {
        'type': EVT_HEALTH_MODEL_FAILED,
        'message': 'Modelo X fallo',
        'data': {'model': 'X'},
        'timestamp': time.time(),
    }
    fmt = format_event(test_evt)
    assert fmt['color'] == '#ef4444'
    assert fmt['category'] == 'Salud'
    assert fmt['prefix'] == 'health'
    assert fmt['time_str'] != '--:--:--'
    assert fmt['message'] == 'Modelo X fallo'
    print("  [PASS] format_event() campos correctos")

    fmt2 = format_event({
        'type': 'custom:algo_nuevo',
        'message': 'Test custom',
        'data': {},
    })
    assert fmt2['prefix'] == 'custom'
    assert fmt2['category'] == 'Custom'
    assert fmt2['color'] == '#9ca3af'
    print("  [PASS] format_event() tipo desconocido usa prefijo y gris")

    # --- Tests truncado ---
    long_msg = "Arena: 371 modelos en 31 categorias (chinese, coding, creative_writing, debate, deduction, finance, gaming, hard_reasoning, instruction_following, math, multilingual, roleplay, safe, science, spanish, summarization, tool_use, translation, vision)"
    fmt_long = format_event({
        'type': 'arena:refresh_complete',
        'message': long_msg,
        'data': {'categories': ['chinese','coding','creative_writing','debate','deduction','finance','gaming','hard_reasoning','instruction_following','math','multilingual','roleplay','safe','science','spanish','summarization','tool_use','translation','vision']},
        'timestamp': time.time(),
    })
    assert len(fmt_long['message']) <= 140, f"Mensaje muy largo: {len(fmt_long['message'])}"
    print(f"  [PASS] Truncado: {len(long_msg)} -> {len(fmt_long['message'])} chars")

    summary = get_event_summary()
    assert 'total' in summary
    assert 'by_prefix' in summary
    print("  [PASS] get_event_summary() retorna estructura correcta")

    collected = []
    def on_fmt(evt):
        collected.append(evt)
    cb = create_bridge_callback(on_fmt)
    notify(EVT_SYSTEM_ERROR, 'Test error bridge', {'test': True})
    assert len(collected) >= 1
    assert collected[-1]['type'] == EVT_SYSTEM_ERROR
    assert collected[-1]['color'] == '#ef4444'
    assert collected[-1]['category'] == 'Sistema'
    assert 'time_str' in collected[-1]
    unregister_callback(cb)
    print("  [PASS] create_bridge_callback() emite y formatea")

    assert EVT_HEALTH_MODEL_VERIFIED in EVENT_TYPES_LIST
    assert EVT_SYSTEM_ERROR in EVENT_TYPES_LIST
    assert len(EVENT_TYPES_LIST) == 21
    print("  [PASS] EVENT_TYPES_LIST tiene 21 tipos")

    assert set(EVENT_PREFIX_COLOR_MAP.keys()) == {'health', 'arena', 'pool', 'system'}
    print("  [PASS] EVENT_PREFIX_COLOR_MAP tiene 4 categorias")

    # --- Tests motor web ---
    assert 'notif-item' in NOTIF_CSS
    assert 'notif-badge' in NOTIF_CSS
    assert 'border-left' in NOTIF_CSS
    print("  [PASS] NOTIF_CSS contiene estilos de notificaciones")

    assert 'notif-section' in NOTIF_SECTION_HTML
    assert 'sm-total' in NOTIF_SECTION_HTML
    assert 'notif-list' in NOTIF_SECTION_HTML
    print("  [PASS] NOTIF_SECTION_HTML contiene panel de resumen y lista")

    assert 'initNotifications' in NOTIF_JS
    assert 'renderNotifications' in NOTIF_JS
    assert 'renderNotifSummary' in NOTIF_JS
    assert 'setNotifFilter' in NOTIF_JS
    assert 'clearNotifDisplay' in NOTIF_JS
    print("  [PASS] NOTIF_JS contiene todas las funciones de notificaciones")

    # --- Tests motor tkinter ---
    assert _get_badge_tag(EVT_HEALTH_MODEL_VERIFIED) == "badge_health_model_verified"
    assert _get_badge_tag('arena:refresh_start') == "badge_arena"
    assert _get_msg_tag('pool:populated') == "msg_pool"
    print("  [PASS] _get_badge_tag() y _get_msg_tag() retornan tags correctos")

    disp = get_summary_display_data({
        'models': {'total': 50, 'available': 40, 'unknown': 5, 'failed': 3,
                   'payment_required': 1, 'rate_limited': 1, 'model_removed': 0,
                   'temporarily_unavailable': 0},
        'arena': {'total_ranked': 371, 'available': True},
        'pool': {'total': 150, 'available': 120, 'with_arena_score': 85},
        'providers': {'active': 3, 'total': 5, 'list': [
            {'name': 'openrouter', 'available': True},
            {'name': 'together', 'available': True},
        ]},
        'top_planning': [{'name': 'gpt-4o', 'score': 95.3}],
        'top_coding': [{'name': 'claude', 'score': 92.1}],
    })
    assert disp['total'] == '50'
    assert disp['arena_ranked'] == '371'
    assert disp['arena_available'] == 'Si'
    assert disp['pool_total'] == '150'
    assert disp['prov_active'] == '3/5'
    assert 'openrouter' in disp['prov_names']
    assert '#1 gpt-4o (95.3)' in disp['top_planning']
    assert '#1 claude (92.1)' in disp['top_coding']
    assert 'Modelos: 40 disponibles' in disp['status']
    print("  [PASS] get_summary_display_data() retorna datos correctos")

    assert len(SUMMARY_LABELS_CONFIG) == 8
    print("  [PASS] SUMMARY_LABELS_CONFIG tiene 8 entradas")

    # --- Tests robustez ---
    collected2 = []
    broken_called = []
    def broken_ui(evt):
        broken_called.append(1)
        raise RuntimeError("Soy una UI rota")
    def good_ui(evt):
        collected2.append(evt)
    cb1 = create_bridge_callback(broken_ui)
    cb2 = create_bridge_callback(good_ui)
    notify(EVT_ARENA_REFRESH_START, 'Test roto + bueno', {})
    assert len(broken_called) >= 1
    assert len(collected2) >= 1
    unregister_callback(cb1)
    unregister_callback(cb2)
    print("  [PASS] Callback roto no afecta a otros callbacks")

    print("\n" + "=" * 60)
    print("  TODOS LOS TESTS PASARON - notification_ui_bridge v3.0 OK")
    print("=" * 60)
