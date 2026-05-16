# apa/core/pool.py
# v1.5 — free_first ranking: get_ranked_entries(free_first=True)
#         ordena modelos gratuitos ANTES que de pago cuando no hay
#         modelos verificados (unknown status). Esto resuelve el
#         bug crítico donde modelos de pago sin crédito (Anthropic,
#         OpenAI) con Arena score alto siempre ganan sobre modelos
#         gratuitos funcionales (GitHub, Groq, OpenRouter).
#         D-1/D-2 se respeta para modelos verified (available),
#         pero para unknown se prefiere free-first como heurística
#         práctica (si no sabemos si funciona, mejor probar gratis).
#
# CAMBIOS v1.5 vs v1.4:
#   - NUEVO: get_ranked_entries(free_first=False) — cuando True,
#     modelos is_free=True se ordenan ANTES que is_free=False.
#     Dentro de cada tier (free/paid), se mantiene el orden por score.
#     Lo usa select_model_entry() PASO 2 para preferir modelos
#     gratuitos cuando no hay modelos verificados.
#   - NUEVO: Test 11 — free_first ranking validation.
#
# CAMBIOS v1.4 vs v1.3:
#   - NUEVO: reset_transient_statuses() — resetea rate_limited y
#     temporarily_unavailable de vuelta a 'unknown'. Se usa entre
#     rankings del stress test para que un modelo rate-limited en
#     'planning' pueda reintentarse en 'coding'. Los rate limits
#     son transitorios (por minuto/hora) y es probable que hayan
#     expirado cuando llegamos al siguiente ranking.
#   - NUEVO: get_working_entries() — retorna entries con status
#     'available' (ya verificadas como funcionales). Lo usa el
#     stress test para contar modelos que funcionan sin re-test.
#   - FIX: payment_required y failed NO se resetean (son permanentes).
#
# CAMBIOS v1.3 vs v1.2:
#   - NUEVO: mark_provider_paid_models(provider_name) — marca TODOS los
#     modelos de pago (is_free=False) de un provider como payment_required.
#     Se usa cuando el provider retorna 402/insufficient_quota para un
#     modelo de pago: si uno falla por pago, TODOS los de pago también fallarán.
#   - NUEVO: mark_provider_rate_limited(provider_name, cooldown_seconds=120) —
#     marca todos los modelos FREE de un provider como temporarily_unavailable
#     con cooldown. Cuando OpenRouter retorna 429 rate_limit para un modelo free,
#     los demás modelos free del mismo provider probablemente también están
#     rate-limited. El cooldown evita desperdiciar intentos en el mismo provider.
#   - NUEVO: get_free_entries() — retorna entries gratuitas ordenadas por score.
#     Lo usa el stress test para el fallback a modelos gratuitos.
#   - FIX: empty_response → se marca como 'failed' (permanente), no como
#     'temporarily_unavailable'. Un modelo que retorna HTTP 200 pero sin
#     contenido está roto y no va a funcionar en reintentos.
#
# v1.2 — mark_provider_paid_models() (añadido por el Director)
# v1.1 — Fix rankings: arena_scores por categoría, scoring por task_type,
#         penalización de payment_required en composite_score.
# v1.0 — Sprint 1: Pool con composite key (provider, model_id),
#         3-layer ranking (APA > Arena > Provider Confidence),
#         operaciones de salud, integración con model_health.
#
# DECISIONES ARQUITECTÓNICAS:
#   P-1: Composite key (provider, model_id) — mismo LLM en 2 providers = 2 entries
#   P-2: Provider Confidence — cada provider tiene confidence_score
#   P-3: 3-Layer Ranking — APA > Arena ELO > Provider Confidence
#   D-1/D-2: No free_first bias para VERIFIED models — ranking drives selection
#   D-1b/D-2b: free_first para UNKNOWN models — heuristic: try free before paid
#   D-5: payment_required status
#   APA Ranking formula: DEFERRED (placeholder = arena_score por ahora)
#
# ============================================================================
import sys
import os
import time
import logging
import threading
import enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.settings import settings
from core.normalizer import normalize_model_id

# ============================================================================
# Logging setup
# ============================================================================
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
logger.propagate = False


# ============================================================================
# HealthStatus — Enum canónico para estados de salud (D-3/D-4/D-5)
# ============================================================================
class HealthStatus(enum.Enum):
    """Estados de salud de un modelo en el pool.

    D-3: rate_limited   — HTTP 429 → cooldown
    D-4: failed         — HTTP 5xx / error permanente
    D-5: payment_required — HTTP 402 → necesita pago
    F10: temporarily_unavailable — error transitorio → cooldown corto
    """
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"
    PAYMENT_REQUIRED = "payment_required"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    UNKNOWN = "unknown"


# ============================================================================
# Exports explícitos
# ============================================================================
__all__ = [
    "HealthStatus",
    "PoolEntry",
    "Pool",
    "VALID_HEALTH_STATUSES",
    "pool",
]


# ============================================================================
# PoolEntry — unidad atómica del pool
# ============================================================================
@dataclass
class PoolEntry:
    """Entrada del pool identificada por composite key (provider, model_id).

    P-1: Dos entries pueden compartir model_id pero diferir en provider.
    Ejemplo: ("openrouter", "anthropic/claude-opus-4-6") y
             ("anthropic", "claude-opus-4-6") son DOS entries independientes.
    """
    provider: str
    model_id: str          # ID original del provider (ej: "anthropic/claude-opus-4-6" en openrouter)
    context_length: int = 8192
    is_free: bool = False

    # --- 3-Layer Ranking (P-3) ---
    arena_score: Optional[float] = None   # Capa 2: Arena ELO normalizado 0-100 (general)
    provider_confidence: float = 50.0     # Capa 3: Provider Confidence (P-2)
    apa_score: Optional[float] = None     # Capa 1: APA ranking (DEFERRED = arena_score)

    # v1.1: Scores por categoría Arena (para ranking por task_type)
    # Ej: {"coding": 85.3, "hard_prompts": 82.1, "general": 80.0}
    arena_scores: Dict[str, float] = field(default_factory=dict)

    # --- Health status ---
    health_status: str = "unknown"  # available | rate_limited | failed | payment_required | unknown
    verified_at: Optional[float] = None

    # --- Metadata ---
    capabilities: List[str] = field(default_factory=list)
    pricing: Dict[str, Any] = field(default_factory=dict)

    @property
    def composite_key(self) -> Tuple[str, str]:
        """P-1: Clave compuesta (provider, model_id)."""
        return (self.provider, self.model_id)

    @property
    def effective_apa_score(self) -> float:
        """Retorna APA score si existe, sino arena_score, sino provider_confidence.
        APA Ranking formula is DEFERRED — placeholder = arena_score.
        """
        if self.apa_score is not None:
            return self.apa_score
        if self.arena_score is not None:
            return self.arena_score
        return self.provider_confidence

    @property
    def composite_score(self) -> float:
        """P-3: Score compuesto 3-capas con pesos.

        APA Ranking formula is DEFERRED by Director:
        "los modelamos posteriormente"

        Mientras tanto, se usa un esquema simple:
          - Si APA score existe: se usa directamente
          - Si no: weighted = 0.6 * arena + 0.4 * confidence
          - v1.1: payment_required → score = 0 (no se selecciona)
        """
        # v1.1: Modelos sin crédito no deben aparecer en el ranking
        if self.health_status == "payment_required":
            return 0.0
        if self.apa_score is not None:
            return self.apa_score
        arena = self.arena_score if self.arena_score is not None else 0.0
        conf = self.provider_confidence
        return 0.6 * arena + 0.4 * conf

    def task_score(self, task_type: Optional[str] = None) -> float:
        """v1.1: Score para un tipo de tarea específico.

        Usa arena_scores[category] si está disponible y task_type coincide.
        Si no, cae a composite_score.

        Mapeo de task_type → categorías Arena (por prioridad):
          planning    → hard_prompts, expert, general
          evaluation  → math, hard_prompts, expert, general
          generation  → creative_writing, coding, instruction_following, general
          coding      → coding, hard_prompts, webdev, general
          correction  → coding, instruction_following, general
        """
        # payment_required siempre devuelve 0
        if self.health_status == "payment_required":
            return 0.0

        if not task_type or not self.arena_scores:
            return self.composite_score

        # Mapeo de task_type → categorías Arena (actualizado al dataset 2026)
        category_map = {
            "planning":    ["hard_prompts", "expert", "general"],
            "evaluation":  ["math", "hard_prompts", "expert", "general"],
            "generation":  ["creative_writing", "coding", "instruction_following", "general"],
            "coding":      ["coding", "hard_prompts", "webdev", "general"],
            "correction":  ["coding", "instruction_following", "general"],
        }
        categories = category_map.get(task_type, ["general"])

        # Buscar la primera categoría disponible en arena_scores
        for cat in categories:
            if cat in self.arena_scores:
                return 0.6 * self.arena_scores[cat] + 0.4 * self.provider_confidence

        # Fallback a composite_score
        return self.composite_score


# ============================================================================
# VALID_HEALTH_STATUSES — D-3/D-4/D-5
# ============================================================================
VALID_HEALTH_STATUSES = {
    "available",                # Probe OK — listo para usar
    "rate_limited",             # HTTP 429 — cooldown (D-3)
    "failed",                   # HTTP 404/401/403 — error permanente
    "payment_required",         # HTTP 402 — necesita pago (D-5)
    "temporarily_unavailable",  # F10: Error transitorio — cooldown corto (timeout, connection, etc.)
    "unknown",                  # Sin verificar aún
}


# ============================================================================
# Pool — gestiona entries con composite key
# ============================================================================
class Pool:
    """Pool de modelos con composite key (provider, model_id).

    P-1: Mismo modelo en 2 providers = 2 entries independientes.
    P-3: Ranking 3-capas: APA > Arena > Provider Confidence.
    """

    def __init__(self):
        self._entries: Dict[Tuple[str, str], PoolEntry] = {}
        self._lock = threading.Lock()

    # --- Operaciones CRUD ---

    def add_entry(self, entry: PoolEntry) -> None:
        """Agrega o actualiza una entrada en el pool."""
        if not entry.provider or not entry.model_id:
            return
        with self._lock:
            self._entries[entry.composite_key] = entry

    def get_entry(self, provider: str, model_id: str) -> Optional[PoolEntry]:
        """Obtiene una entrada por composite key."""
        with self._lock:
            return self._entries.get((provider, model_id))

    def remove_entry(self, provider: str, model_id: str) -> bool:
        """Elimina una entrada del pool."""
        with self._lock:
            return self._entries.pop((provider, model_id), None) is not None

    def get_all_entries(self) -> List[PoolEntry]:
        """Retorna todas las entries del pool."""
        with self._lock:
            return list(self._entries.values())

    def size(self) -> int:
        """Número de entries en el pool."""
        with self._lock:
            return len(self._entries)

    # --- Operaciones de salud (D-3/D-4/D-5) ---

    def mark_available(self, provider: str, model_id: str) -> None:
        """Marca una entrada como available (probe OK)."""
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry:
                entry.health_status = "available"
                entry.verified_at = time.time()

    def mark_rate_limited(self, provider: str, model_id: str) -> None:
        """D-3: Marca como rate_limited (HTTP 429 → cooldown)."""
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry and entry.health_status != "available":
                entry.health_status = "rate_limited"
                entry.verified_at = time.time()

    def mark_failed(self, provider: str, model_id: str) -> None:
        """Marca como failed (HTTP 404/401/403 — error permanente)."""
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry and entry.health_status != "available":
                entry.health_status = "failed"
                entry.verified_at = time.time()

    def mark_payment_required(self, provider: str, model_id: str) -> None:
        """D-5: Marca como payment_required (HTTP 402)."""
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry and entry.health_status != "available":
                entry.health_status = "payment_required"
                entry.verified_at = time.time()

    def mark_temporarily_unavailable(self, provider: str, model_id: str) -> None:
        """F10: Marca como temporarily_unavailable (error transitorio con cooldown).

        A diferencia de 'failed' que es permanente, este estado tiene cooldown
        corto (60s) y el modelo puede ser re-seleccionado tras expirar.
        No sobreescribe 'available'.
        """
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry and entry.health_status != "available":
                entry.health_status = "temporarily_unavailable"
                entry.verified_at = time.time()

    def mark_provider_paid_models(self, provider_name: str) -> int:
        """v1.2/v1.3: Marca TODOS los modelos de pago de un provider como payment_required.

        Cuando un provider retorna 402/insufficient_quota para un modelo de pago,
        significa que la cuenta no tiene crédito. Si uno falla por pago, TODOS
        los de pago del mismo provider también fallarán.

        Solo marca modelos con is_free=False (de pago).
        Los modelos gratuitos del mismo provider NO se afectan.

        Retorna: número de modelos marcados.
        """
        marked = 0
        with self._lock:
            for key, entry in self._entries.items():
                if entry.provider == provider_name and not entry.is_free:
                    if entry.health_status != "available":
                        entry.health_status = "payment_required"
                        entry.verified_at = time.time()
                        marked += 1
        return marked

    def reset_transient_statuses(self) -> int:
        """v1.4: Resetea estados transitorios a 'unknown' para reusar modelos.

        Los estados rate_limited y temporarily_unavailable son transitorios:
        - rate_limited: HTTP 429 → el cooldown ya expiró entre rankings
        - temporarily_unavailable: timeout/connection → probablemente recuperado

        Estos modelos DEBEN poder reintentarse para otros task types.
        Un modelo rate-limited en 'planning' puede funcionar en 'coding'.

        NO resetea estados permanentes:
        - payment_required: la cuenta no tiene crédito → permanente
        - failed: empty_response, not_found, auth → el modelo está roto
        - available: ya funciona → no tocar

        Retorna: número de entries reseteadas.
        """
        reset_count = 0
        with self._lock:
            for entry in self._entries.values():
                if entry.health_status in ("rate_limited", "temporarily_unavailable"):
                    entry.health_status = "unknown"
                    entry.verified_at = None
                    reset_count += 1
        return reset_count

    def get_working_entries(self) -> List[PoolEntry]:
        """v1.4: Retorna entries verificadas como funcionales (status='available').

        Lo usa el stress test para contar modelos que ya funcionan
        sin necesidad de re-testearlos para cada ranking.
        """
        with self._lock:
            return [e for e in self._entries.values() if e.health_status == "available"]

    def mark_provider_rate_limited(self, provider_name: str, cooldown_seconds: int = 120) -> int:
        """v1.3: Marca todos los modelos FREE de un provider como temporarily_unavailable.

        Cuando OpenRouter retorna 429 rate_limit para un modelo free, es probable
        que otros modelos free del mismo provider también estén rate-limited
        (OpenRouter tiene rate limits por cuenta para el tier gratuito).

        El cooldown por defecto es 120s (2 minutos), mayor que el cooldown
        normal de 60s para temporarily_unavailable, porque los rate limits
        de la cuenta tardan más en resetearse.

        Solo marca modelos con is_free=True (gratuitos).
        Los modelos de pago NO se afectan (ya estarán como payment_required
        si el provider no tiene crédito).

        Retorna: número de modelos marcados.
        """
        marked = 0
        now = time.time()
        with self._lock:
            for key, entry in self._entries.items():
                if entry.provider == provider_name and entry.is_free:
                    if entry.health_status not in ("available", "payment_required"):
                        entry.health_status = "temporarily_unavailable"
                        # Usar cooldown más largo para rate limits de provider
                        # El cooldown normal es 60s; aquí usamos cooldown_seconds
                        # Para implementar esto, verified_at = now - (60 - cooldown_seconds)
                        # Así el cooldown de get_ranked_entries() (que usa 60s)
                        # se extiende efectivamente a cooldown_seconds.
                        # Ejemplo: cooldown_seconds=120, verificamos a now - 60
                        # → quedan 120s - 60s = 60s de cooldown restante.
                        # Espera, eso no es correcto. Mejor simplificar:
                        # verified_at = now - 60 + (cooldown_seconds - 60)
                        # → verified_at = now + (cooldown_seconds - 60)
                        # → el cooldown de 60s se cumple en now + cooldown_seconds
                        entry.verified_at = now + (cooldown_seconds - 60)
                        marked += 1
        return marked

    # --- Operaciones de ranking (P-3) ---

    def set_arena_score(self, provider: str, model_id: str, score: float) -> None:
        """Establece el Arena ELO score (Capa 2)."""
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry:
                entry.arena_score = score
                # APA placeholder: si no hay APA score, hereda arena score
                if entry.apa_score is None:
                    entry.apa_score = score

    def set_provider_confidence(self, provider: str, confidence: float) -> None:
        """P-2: Establece confidence_score para todas las entries de un provider."""
        with self._lock:
            for key, entry in self._entries.items():
                if entry.provider == provider:
                    entry.provider_confidence = confidence

    def set_apa_score(self, provider: str, model_id: str, score: float) -> None:
        """Establece el APA score (Capa 1). Formula DEFERRED."""
        with self._lock:
            entry = self._entries.get((provider, model_id))
            if entry:
                entry.apa_score = score

    # --- Consultas de ranking ---

    def get_ranked_entries(
        self,
        task_type: Optional[str] = None,
        min_context: int = 0,
        only_available: bool = False,
        exclude_statuses: Optional[List[str]] = None,
        free_first: bool = False,
    ) -> List[PoolEntry]:
        """Retorna entries ordenadas por composite_score descendente.

        P-3: 3-Layer Ranking — APA > Arena ELO > Provider Confidence.
        D-1/D-2: No free_first bias para VERIFIED (only_available=True).
        D-1b/D-2b: free_first para UNKNOWN models — heurística práctica.

        v1.5: free_first=True ordena modelos gratuitos ANTES que de pago.
        Esto es crucial cuando no hay modelos verificados (PASO 2 de
        select_model_entry): los modelos unknown de pago tienen scores
        altos (Arena 90+) pero fallarán si no hay crédito, mientras
        que los modelos gratuitos (Arena 65-85) probablemente funcionen.

        Con free_first=True:
        - Tier 1: modelos is_free=True, ordenados por score descendente
        - Tier 2: modelos is_free=False, ordenados por score descendente
        Sin free_first (default=False): orden puro por score (D-1/D-2 clásico).

        Args:
            task_type: Tipo de tarea (para filtrar por contexto mínimo)
            min_context: Context length mínimo (0 = sin filtro)
            only_available: Si True, solo entries con health_status="available"
            exclude_statuses: Lista de statuses a excluir (ej: ["payment_required", "failed"])
            free_first: Si True, modelos gratuitos se ordenan ANTES que de pago
        """
        # Contexto mínimo por task_type
        if task_type and min_context == 0:
            min_context = {
                "planning": 16000,
                "evaluation": 8000,
                "generation": 8000,
                "coding": 4000,
                "correction": 4000,
            }.get(task_type, 0)

        exclude = set(exclude_statuses or [])
        if only_available:
            # F10: temporarily_unavailable también se excluye de "only_available"
            # pero NO de la selección general (PASO 2 de select_model_entry)
            exclude.update({"rate_limited", "failed", "payment_required", "unknown", "temporarily_unavailable"})

        # F10: Limpiar estados temporarily_unavailable expirados (cooldown 60s)
        now = time.time()
        with self._lock:
            for entry in self._entries.values():
                if entry.health_status == "temporarily_unavailable" and entry.verified_at:
                    if now - entry.verified_at >= 60:  # 60s cooldown
                        entry.health_status = "unknown"  # Vuelve a ser seleccionable

        with self._lock:
            candidates = []
            for entry in self._entries.values():
                # Filtro de contexto
                if entry.context_length < min_context:
                    continue
                # Filtro de status
                if entry.health_status in exclude:
                    continue
                candidates.append(entry)

        # v1.5: Ordenar — free_first o ranking puro
        # D-1/D-2 clásico: ranking puro por score (para verified models)
        # D-1b/D-2b: free_first para unknown models (heurística práctica)
        if free_first:
            # Dos tiers: free (tier=0) va ANTES que paid (tier=1)
            # Dentro de cada tier, ordenar por score descendente
            candidates.sort(
                key=lambda e: (0 if e.is_free else 1, -e.task_score(task_type)),
            )
        else:
            # D-1/D-2: Ranking puro por score (sin free bias)
            # payment_required → score=0 → cae al final automáticamente.
            candidates.sort(key=lambda e: e.task_score(task_type), reverse=True)
        return candidates

    def get_entries_for_model(self, model_id: str) -> List[PoolEntry]:
        """Retorna todas las entries para un model_id (puede haber múltiples providers)."""
        with self._lock:
            return [e for e in self._entries.values() if e.model_id == model_id]

    def get_available_entries(self) -> List[PoolEntry]:
        """Retorna entries con health_status='available'."""
        with self._lock:
            return [e for e in self._entries.values() if e.health_status == "available"]

    def get_entries_by_status(self, status: str) -> List[PoolEntry]:
        """Retorna entries con un health_status específico."""
        with self._lock:
            return [e for e in self._entries.values() if e.health_status == status]

    def get_free_entries(
        self,
        task_type: Optional[str] = None,
        min_context: int = 0,
        exclude_statuses: Optional[List[str]] = None,
    ) -> List[PoolEntry]:
        """v1.3: Retorna entries gratuitas (is_free=True) ordenadas por score.

        Lo usa el stress test para el fallback a modelos gratuitos cuando
        la tasa de éxito global es < 50%.

        Args:
            task_type: Tipo de tarea (para scoring por categoría)
            min_context: Context length mínimo (0 = sin filtro)
            exclude_statuses: Lista de statuses a excluir
        """
        exclude = set(exclude_statuses or [])
        # F10: Limpiar estados temporarily_unavailable expirados (cooldown 60s)
        now = time.time()
        with self._lock:
            for entry in self._entries.values():
                if entry.health_status == "temporarily_unavailable" and entry.verified_at:
                    if now - entry.verified_at >= 60:
                        entry.health_status = "unknown"

        with self._lock:
            candidates = []
            for entry in self._entries.values():
                if not entry.is_free:
                    continue
                if entry.context_length < min_context:
                    continue
                if entry.health_status in exclude:
                    continue
                candidates.append(entry)

        # Ordenar por score (task_score si hay task_type, sino composite_score)
        candidates.sort(key=lambda e: e.task_score(task_type), reverse=True)
        return candidates

    def health_summary(self) -> Dict[str, int]:
        """Retorna resumen de salud: {status: count}."""
        with self._lock:
            summary: Dict[str, int] = {}
            for entry in self._entries.values():
                st = entry.health_status
                summary[st] = summary.get(st, 0) + 1
            return summary

    def clear(self) -> None:
        """Limpia el pool."""
        with self._lock:
            self._entries.clear()


# ============================================================================
# Instancia global del pool
# ============================================================================
pool = Pool()


# ============================================================================
# VALIDACIÓN AUTOCONTENIDA
# ============================================================================
def _run_validation() -> None:
    """Validación autocontenida — 8 tests para Sprint 1."""
    import sys

    test_results = []
    test_pool = Pool()  # Pool limpio para tests

    # --- Test 1: PoolEntry composite key ---
    try:
        e1 = PoolEntry(provider="openrouter", model_id="anthropic/claude-opus-4-6")
        assert e1.composite_key == ("openrouter", "anthropic/claude-opus-4-6")
        e2 = PoolEntry(provider="anthropic", model_id="claude-opus-4-6")
        assert e2.composite_key == ("anthropic", "claude-opus-4-6")
        # P-1: Mismo modelo, distinto provider = distintas keys
        assert e1.composite_key != e2.composite_key
        test_results.append(("P1: Composite key (provider, model_id)", True))
    except AssertionError as e:
        test_results.append(("P1: Composite key (provider, model_id)", False))

    # --- Test 2: 3-Layer Ranking ---
    try:
        e = PoolEntry(provider="openrouter", model_id="test-model",
                      arena_score=80.0, provider_confidence=60.0)
        # APA placeholder = arena_score
        assert e.apa_score is None
        assert e.effective_apa_score == 80.0  # Falls back to arena
        # Composite score sin APA: 0.6*80 + 0.4*60 = 48+24 = 72.0
        assert e.composite_score == 72.0
        # Con APA score explícito
        e.apa_score = 95.0
        assert e.composite_score == 95.0
        test_results.append(("P3: 3-Layer Ranking (APA>Arena>Conf)", True))
    except AssertionError:
        test_results.append(("P3: 3-Layer Ranking (APA>Arena>Conf)", False))

    # --- Test 3: Health operations ---
    try:
        e = PoolEntry(provider="groq", model_id="llama3-70b")
        assert e.health_status == "unknown"
        test_pool.add_entry(e)

        test_pool.mark_available("groq", "llama3-70b")
        e = test_pool.get_entry("groq", "llama3-70b")
        assert e.health_status == "available"

        test_pool.mark_rate_limited("groq", "llama3-70b")
        # available should NOT be overwritten by rate_limited
        e = test_pool.get_entry("groq", "llama3-70b")
        assert e.health_status == "available"
        test_results.append(("D3/D4: Health ops (available no overwrite)", True))
    except AssertionError:
        test_results.append(("D3/D4: Health ops (available no overwrite)", False))

    # --- Test 4: payment_required status (D-5) ---
    try:
        e = PoolEntry(provider="openrouter", model_id="paid-model")
        test_pool.add_entry(e)
        test_pool.mark_payment_required("openrouter", "paid-model")
        e = test_pool.get_entry("openrouter", "paid-model")
        assert e.health_status == "payment_required"
        # payment_required should NOT overwrite available
        e2 = PoolEntry(provider="openrouter", model_id="available-model")
        test_pool.add_entry(e2)
        test_pool.mark_available("openrouter", "available-model")
        test_pool.mark_payment_required("openrouter", "available-model")
        e2 = test_pool.get_entry("openrouter", "available-model")
        assert e2.health_status == "available"
        test_results.append(("D5: payment_required status", True))
    except AssertionError:
        test_results.append(("D5: payment_required status", False))

    # --- Test 5: No free_first bias (D-1/D-2) ---
    try:
        pool_test = Pool()
        free_entry = PoolEntry(provider="openrouter", model_id="free-model",
                               is_free=True, arena_score=50.0, provider_confidence=40.0)
        paid_entry = PoolEntry(provider="openrouter", model_id="paid-model",
                               is_free=False, arena_score=90.0, provider_confidence=80.0)
        pool_test.add_entry(free_entry)
        pool_test.add_entry(paid_entry)

        ranked = pool_test.get_ranked_entries()
        # Paid debe ir primero porque tiene mejor score, NO porque sea free
        assert ranked[0].model_id == "paid-model"
        assert ranked[0].composite_score > ranked[1].composite_score
        test_results.append(("D1/D2: No free_first bias", True))
    except AssertionError:
        test_results.append(("D1/D2: No free_first bias", False))

    # --- Test 6: set_provider_confidence (P-2) ---
    try:
        pool_test2 = Pool()
        pool_test2.add_entry(PoolEntry(provider="groq", model_id="model-a", provider_confidence=50.0))
        pool_test2.add_entry(PoolEntry(provider="groq", model_id="model-b", provider_confidence=50.0))
        pool_test2.add_entry(PoolEntry(provider="openrouter", model_id="model-c", provider_confidence=50.0))

        pool_test2.set_provider_confidence("groq", 85.0)

        e_a = pool_test2.get_entry("groq", "model-a")
        e_b = pool_test2.get_entry("groq", "model-b")
        e_c = pool_test2.get_entry("openrouter", "model-c")

        assert e_a.provider_confidence == 85.0
        assert e_b.provider_confidence == 85.0
        assert e_c.provider_confidence == 50.0  # No afectado
        test_results.append(("P2: Provider Confidence por provider", True))
    except AssertionError:
        test_results.append(("P2: Provider Confidence por provider", False))

    # --- Test 7: get_ranked_entries con filtros ---
    try:
        pool_test3 = Pool()
        pool_test3.add_entry(PoolEntry(provider="openrouter", model_id="small-ctx",
                                       context_length=4000, arena_score=90.0))
        pool_test3.add_entry(PoolEntry(provider="openrouter", model_id="big-ctx",
                                       context_length=128000, arena_score=80.0))

        # Filtrar por contexto
        ranked = pool_test3.get_ranked_entries(min_context=8000)
        assert len(ranked) == 1
        assert ranked[0].model_id == "big-ctx"

        # Excluir payment_required
        pool_test3.add_entry(PoolEntry(provider="openrouter", model_id="no-pay",
                                       arena_score=95.0, health_status="payment_required"))
        ranked = pool_test3.get_ranked_entries(exclude_statuses=["payment_required"])
        model_ids = [e.model_id for e in ranked]
        assert "no-pay" not in model_ids
        test_results.append(("Ranking con filtros (ctx, status)", True))
    except AssertionError:
        test_results.append(("Ranking con filtros (ctx, status)", False))

    # --- Test 8: health_summary ---
    try:
        pool_test4 = Pool()
        pool_test4.add_entry(PoolEntry(provider="p1", model_id="m1", health_status="available"))
        pool_test4.add_entry(PoolEntry(provider="p1", model_id="m2", health_status="available"))
        pool_test4.add_entry(PoolEntry(provider="p1", model_id="m3", health_status="rate_limited"))
        pool_test4.add_entry(PoolEntry(provider="p1", model_id="m4", health_status="payment_required"))
        pool_test4.add_entry(PoolEntry(provider="p1", model_id="m5", health_status="unknown"))

        summary = pool_test4.health_summary()
        assert summary["available"] == 2
        assert summary["rate_limited"] == 1
        assert summary["payment_required"] == 1
        assert summary["unknown"] == 1
        test_results.append(("health_summary aggregation", True))
    except AssertionError:
        test_results.append(("health_summary aggregation", False))

    # --- Test 9: task_score with arena_scores (v1.1) ---
    try:
        e = PoolEntry(provider="openrouter", model_id="test-coder",
                      arena_score=70.0, provider_confidence=70.0,
                      arena_scores={"coding": 85.0, "general": 70.0, "hard_prompts": 75.0})
        # coding task → uses "coding" score: 0.6*85 + 0.4*70 = 51+28 = 79.0
        assert e.task_score("coding") == 79.0
        # planning task → uses "hard_prompts" score: 0.6*75 + 0.4*70 = 45+28 = 73.0
        assert e.task_score("planning") == 73.0
        # No task_type → falls back to composite_score: 0.6*70 + 0.4*70 = 70.0
        assert e.task_score(None) == 70.0
        test_results.append(("v1.1: task_score por categoría", True))
    except AssertionError:
        test_results.append(("v1.1: task_score por categoría", False))

    # --- Test 10: payment_required score = 0 (v1.1) ---
    try:
        e = PoolEntry(provider="openrouter", model_id="paid-model",
                      arena_score=95.0, provider_confidence=90.0)
        assert e.composite_score > 0  # Normal: paid pero no marcado
        e.health_status = "payment_required"
        assert e.composite_score == 0.0  # Marcado: score = 0
        assert e.task_score("coding") == 0.0  # task_score también
        test_results.append(("v1.1: payment_required → score=0", True))
    except AssertionError:
        test_results.append(("v1.1: payment_required → score=0", False))

    # --- Test 11: free_first ranking (v1.5) ---
    try:
        pool_ff = Pool()
        # Free model with LOWER score than paid
        pool_ff.add_entry(PoolEntry(
            provider="groq", model_id="GRQ:free-model",
            is_free=True, arena_score=70.0, provider_confidence=70.0,
        ))
        # Paid model with HIGHER score
        pool_ff.add_entry(PoolEntry(
            provider="anthropic", model_id="ANT:paid-model",
            is_free=False, arena_score=93.0, provider_confidence=90.0,
        ))
        # Free model with medium score
        pool_ff.add_entry(PoolEntry(
            provider="github", model_id="GHU:free-model-2",
            is_free=True, arena_score=85.0, provider_confidence=70.0,
        ))

        # Sin free_first: paid model primero (D-1/D-2 clásico)
        ranked_normal = pool_ff.get_ranked_entries(free_first=False)
        assert ranked_normal[0].model_id == "ANT:paid-model", \
            f"Expected paid first, got {ranked_normal[0].model_id}"

        # Con free_first: free models primero, ordenados por score
        ranked_ff = pool_ff.get_ranked_entries(free_first=True)
        assert ranked_ff[0].is_free, \
            f"Expected free first, got {ranked_ff[0].model_id}"
        assert ranked_ff[0].model_id == "GHU:free-model-2", \
            f"Expected highest-scored free first, got {ranked_ff[0].model_id}"
        assert ranked_ff[1].is_free, \
            f"Expected free second, got {ranked_ff[1].model_id}"
        assert not ranked_ff[2].is_free, \
            f"Expected paid last, got {ranked_ff[2].model_id}"

        test_results.append(("v1.5: free_first ranking", True))
    except AssertionError as e:
        test_results.append(("v1.5: free_first ranking", False))

    # --- Reporte ---
    passed = sum(1 for _, ok in test_results if ok)
    failed = len(test_results) - passed
    print(f"\n{'='*60}")
    print(f"pool.py v1.5 — Sprint 1 Validation")
    print(f"{'='*60}")
    for name, ok in test_results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\nResultado: {passed}/{len(test_results)} PASS, {failed} FAIL")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    _run_validation()