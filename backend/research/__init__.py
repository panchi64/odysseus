"""Deep research — a rounds-based orchestrator on the Run substrate.

plan → per round: analyst picks gaps → dynamic fan-out of search/read workers →
merge into the evidence ledger → analyst refines the evolving answer + gap list →
comprehensiveness judge → loop or write. Bounded by rounds + wall-clock time, same
substrate (Run, event protocol) as chat and agent — same skeleton, different driver.
See docs/architecture/README.md (§5) and this package's ``CLAUDE.md`` for the exact
event frames :func:`run_research` emits.

This is the pipeline **core** only: no routes, no model resolution, no Run/app
wiring yet (that's the next batch, which builds an ``Orchestrator`` closure around
:func:`run_research`, and the ``ResearchPlan``/``ResearchDeps`` it's handed).
"""

from __future__ import annotations

from .dedupe import DedupeSets, canonicalize_url, normalize_query
from .pipeline import run_research
from .state import (
    EvidenceClaim,
    EvidenceLedger,
    ResearchDeps,
    ResearchPlan,
    ResearchResult,
    SearchUnavailableError,
)

__all__ = [
    "run_research",
    "ResearchPlan",
    "ResearchDeps",
    "ResearchResult",
    "EvidenceClaim",
    "EvidenceLedger",
    "SearchUnavailableError",
    "DedupeSets",
    "normalize_query",
    "canonicalize_url",
]
