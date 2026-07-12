"""Shared types for the research pipeline.

The frozen plan going in, the evidence ledger built up round over round, the
capabilities/bounds the orchestrator is handed (:class:`ResearchDeps`), and the report
handed back out (:class:`ResearchResult`). Nothing here talks to a model, a service, or
the Run substrate directly — that happens in ``agents.py`` and ``pipeline.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_ai.settings import ModelSettings

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from services.search import SearchService
    from services.webfetch import BrowserFetcher


class ResearchPlan(BaseModel):
    """The frozen plan a run starts from — mirrors the REST ``ResearchOut.plan`` shape
    (``{objective, angles, notes?}``). The pre-run clarify/intake/refine surface that
    produces it is a separate (later) batch's concern; this is just the data the
    orchestrator consumes. ``angles`` seeds round 1's open gaps."""

    objective: str
    angles: list[str] = []
    notes: str | None = None


class EvidenceClaim(BaseModel):
    """One extracted finding, attributed to the page it came from. The pipeline stamps
    ``source_url``/``source_title`` itself after the extraction call returns — the
    extraction model is never asked for them — so attribution can't be hallucinated
    onto the wrong source."""

    claim: str
    source_url: str
    source_title: str | None = None


@dataclass
class EvidenceLedger:
    """The run's evidence, accumulated round over round — the writer's *only* input
    (DR-1.3). ``sources`` preserves first-seen order, which is also the order the
    pipeline emits ``citation.added`` in, so a source's position here is the same
    ``[n]`` the writer is told to cite it as (mirrors the chat surface's Sources-row,
    which is likewise numbered by position — see ``agent/translate.py``)."""

    sources: dict[str, str | None] = field(default_factory=dict)
    claims: list[EvidenceClaim] = field(default_factory=list)

    def add_source(self, url: str, title: str | None) -> bool:
        """Register a used source; True the first time a URL is added (new) — the
        caller emits ``citation.added`` only on that transition."""
        if url in self.sources:
            return False
        self.sources[url] = title
        return True

    def add_claims(self, claims: list[EvidenceClaim]) -> None:
        self.claims.extend(claims)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def claim_count(self) -> int:
        return len(self.claims)

    def source_index(self, url: str) -> int | None:
        """The 1-based citation number for ``url`` (its position in first-seen
        order), or ``None`` if it was never added."""
        if url not in self.sources:
            return None
        return list(self.sources).index(url) + 1

    def render_sources(self) -> str:
        """The numbered source list handed to the writer — ``[n]`` here is exactly
        the number the writer must cite that source as."""
        if not self.sources:
            return "(none)"
        return "\n".join(
            f"[{i}] {title or url} — {url}"
            for i, (url, title) in enumerate(self.sources.items(), start=1)
        )

    def render_claims(self) -> str:
        """Every gathered claim, each tagged with its source's citation number."""
        if not self.claims:
            return "(no evidence gathered yet)"
        return "\n".join(
            f"[{self.source_index(c.source_url)}] {c.claim}" for c in self.claims
        )


class SearchUnavailableError(Exception):
    """Raised when web search returned no usable results across
    ``ResearchDeps.empty_rounds_abort`` consecutive rounds (DR-4.1). The message is
    the clear, operator-facing explanation — the caller (the routes/model wiring
    batch) lets this propagate to a terminal ``error`` rather than a fabricated
    report, carrying this text verbatim."""


@dataclass
class ResearchResult:
    """What a completed run hands back — the report plus the stats the REST
    contract's ``ResearchOut.stats`` surfaces (duration, rounds, sources, queries,
    model)."""

    report: str
    rounds: int
    sources: int
    queries: int
    duration_s: float
    model: str


# What the orchestrator emits with: matches ``Run.emit``'s signature (a typed event
# body in, the stamped ``Event`` — or nothing — out) without importing ``runs.Run``,
# so this stays callable from a plain list-appending fake in tests.
EventEmitter = Callable[[BaseModel], object]
CancelCheck = Callable[[], bool]


def _never_cancelled() -> bool:
    return False


@dataclass
class ResearchDeps:
    """Everything the pipeline needs, injected by its caller — capabilities plus this
    run's resolved bounds, so the pipeline itself never reads global settings or the
    model registry directly (that happens in the routes/model wiring batch that builds
    this).

    ``main_model``/``main_settings`` drive planning (gap selection, answer refinement)
    and the final report (synthesis/writing); ``utility_model``/``utility_settings``
    drive the cheap background calls (evidence extraction, the comprehensiveness
    judge) — the same main/utility split the chat engine uses for titling/
    verification, resolved via ``services.registry.resolve_background``. ``search``/
    ``fetcher`` are ``None`` when that capability is unavailable — a worker then
    treats every call as if it degraded (see ``pipeline._search_one``/``_read_one``).
    """

    owner_id: str
    main_model: Model
    utility_model: Model
    main_settings: ModelSettings | None = None
    utility_settings: ModelSettings | None = None
    search: SearchService | None = None
    fetcher: BrowserFetcher | None = None
    # This run's resolved bounds — defaults mirror ``core.config.Settings``'s
    # research_* fields; the caller passes the operator's actual configured values.
    max_rounds: int = 4
    time_limit_s: float = 900.0
    round_floor: int = 2
    max_concurrency: int = 4
    empty_rounds_abort: int = 2
    # Cooperative cancellation, polled at a step boundary (between rounds, and again
    # between a round's search and read batches) — mirrors the engine's own redundant
    # `cancel_requested` check (see `agent/engine.py`'s `report_progress`). Defaults to
    # "never cancelled" so a caller that doesn't wire cancellation still runs.
    cancel_requested: CancelCheck = _never_cancelled
