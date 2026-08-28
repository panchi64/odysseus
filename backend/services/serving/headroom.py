"""The pre-flight memory guard — pure decision logic.

``serve`` refuses a model that can't fit alongside what's already resident, naming the
models to stop. The async gathering (detect the budget, size the candidate live from
HuggingFace, sum the resident artifacts on disk) stays in the service; this module holds
the size math and the refusal, so it's trivially testable and has one reason to change.
Best-effort by design — a model we couldn't size (HF unreachable) or an unknown budget
skips the check (degrade toward allowing).
"""

from __future__ import annotations

from collections.abc import Iterable

from core.exceptions import ServingUnavailableError

from .models import ServeState

# States that hold memory right now — what the guard sums against the budget.
RESIDENT_STATES = frozenset({ServeState.running.value, ServeState.starting.value})


def human_gb(n: int) -> str:
    return f"{n / 1024**3:.1f} GB"


def check(
    *,
    repo: str,
    need_bytes: int | None,
    resident: Iterable[tuple[str, int]],
    usable_budget: int | None,
) -> None:
    """Raise ``ServingUnavailableError`` if ``repo`` (needing ``need_bytes``) won't fit
    within ``usable_budget`` alongside ``resident`` — ``(repo, size_bytes)`` pairs that
    must already exclude ``repo``. A candidate we couldn't size or an unknown budget is
    allowed through (degrade toward allowing)."""
    if need_bytes is None or usable_budget is None:
        return
    resident = list(resident)
    committed = sum(size for _, size in resident)
    if need_bytes + committed <= usable_budget:
        return
    free = max(usable_budget - committed, 0)
    running = ", ".join(name for name, _ in resident) or "none currently"
    raise ServingUnavailableError(
        f"not enough memory to serve {repo}: it needs ~{human_gb(need_bytes)} but only "
        f"~{human_gb(free)} of the ~{human_gb(usable_budget)} budget is free. "
        f"Stop a running model to make room (currently running: {running})."
    )
