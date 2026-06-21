"""The pre-flight memory guard — pure decision logic.

``serve`` refuses a model that can't fit alongside what's already resident, naming the
models to stop. The async gathering (detect the budget, load the rows) stays in the
service; this module holds the size math and the refusal, so it's trivially testable and
has one reason to change. Best-effort by design — an unsizable model (free-text, not in
the catalog) or an unknown budget skips the check (degrade toward allowing).
"""

from __future__ import annotations

from collections.abc import Iterable

from core.exceptions import ServingUnavailableError
from models.serving import ManagedModel

from . import catalog
from .models import EngineKind, ServeState

# States that hold memory right now — what the guard sums against the budget.
RESIDENT_STATES = frozenset({ServeState.running.value, ServeState.starting.value})


def human_gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


def check(
    *,
    engine: EngineKind,
    repo: str,
    resident_rows: Iterable[ManagedModel],
    usable_budget: int | None,
) -> None:
    """Raise ``ServingUnavailableError`` if ``repo`` won't fit within ``usable_budget``
    alongside ``resident_rows`` (which must already exclude ``repo``). A model we can't
    size or an unknown budget is allowed through."""
    need = catalog.bytes_for(engine, repo)
    if need is None or usable_budget is None:
        return
    resident = list(resident_rows)
    committed = sum(catalog.bytes_for(EngineKind(r.engine), r.hf_repo) or 0 for r in resident)
    if need + committed <= usable_budget:
        return
    free = max(usable_budget - committed, 0)
    running = ", ".join(r.hf_repo for r in resident) or "none currently"
    raise ServingUnavailableError(
        f"not enough memory to serve {repo}: it needs ~{human_gb(need)} but only "
        f"~{human_gb(free)} of the ~{human_gb(usable_budget)} budget is free. "
        f"Stop a running model to make room (currently running: {running})."
    )
