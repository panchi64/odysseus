"""The context gauge and the room check — the footprint arithmetic a turn is measured by.

Two pure readings over a message list. :func:`turn_metrics` is the thread's cumulative
readout, emitted live as each response lands and stashed as the run's terminal metrics;
:func:`no_room_for` is the yes/no the verifier asks before spending a second full pass at
the turn's peak pressure. They sit together because they are the same arithmetic seen from
two sides — what the replay costs against the window it has to fit in — and apart from
``engine.py`` because the turn, the two folds and the verifier all read them, and none of
those is the reason this file would change.

Neither reads settings for itself: the value arrives as a keyword, so the caller that
already resolved one settings object measures every frame of a turn against it.
"""

from __future__ import annotations

from pydantic_ai import ModelMessage, ModelRequest, UserPromptPart

from core.config import Settings
from runs import Run, RunMetrics, total_timings
from services.context_budget import compose
from services.conversation_view import estimate_footprint, estimate_tokens
from services.conversations import (
    conversation_totals,
    footprint_or_estimate,
    last_request_usage,
)


def turn_metrics(run: Run, messages: list[ModelMessage], *, settings: Settings) -> RunMetrics:
    """The thread's cumulative readout, counted off ``messages`` — the full replayed
    history, not just this run's own additions.

    **Derived, not accumulated.** ``messages`` is everything on the active path, and
    each stored response carries the usage the provider reported for it, so every count
    and token here is a fresh sum over the path. That is what makes the figures survive
    a reload, a rewind and a version switch without a counter to keep in step: the same
    ``conversation_totals`` runs on a cold load and produces the same answer. It is also
    why this no longer takes a ``base``/``usage`` pair — the run's own ``RunUsage``
    covers only the current run, and adding it to a path-derived total would count this
    turn twice.

    Time is the exception, and the only thing still carried on the Run: it isn't in the
    message blobs. ``run.prior_timings`` holds the persisted total for the turns before
    this one, and ``run.timer`` holds this run's own, so the two add.

    ``context_used`` is the *footprint* — the last response's prompt+generation, not the
    path's summed tokens — so a long thread doesn't overstate fullness. Built in one
    place so the live per-step frames (the context gauge) and the stashed terminal
    metrics never diverge.

    **Fold-aware.** A response that landed *before* this run's most recent compaction
    reported its prompt size against a history that no longer exists, so the footprint is
    read only from ``run.fold_boundary`` onward. Until the first post-fold response lands
    there is nothing measured to read, and the estimate stands in — which is the whole
    point: without it the gauge would sit pinned at the pre-fold figure through the very
    turn the fold made room for, and the operator would watch a compaction change nothing.
    ``last_request_usage`` still reads the whole path: which model spoke last, and what its
    cache did, are facts about a request, not about the current replay."""
    counts = conversation_totals(messages)
    timings = run.prior_timings + total_timings(run.timer.responses)
    # The boundary decides which *reported* figures may still be believed, not what the
    # estimate covers: the estimate is always over the whole replay, because the whole
    # replay is what the next request carries. Same helper the cold read calls, so a
    # thread reopened after a run reports the figure the live frames did.
    footprint = footprint_or_estimate(
        messages,
        run.context_overhead,
        fallback_overhead_tokens=settings.context_overhead_fallback_tokens,
        reported_from=messages[min(run.fold_boundary, len(messages)) :],
    )
    return RunMetrics(
        steps=counts.steps,
        tool_calls=counts.tool_calls,
        turns=counts.turns,
        input_tokens=counts.input_tokens,
        output_tokens=counts.output_tokens,
        cache_read_tokens=counts.cache_read_tokens,
        # A thread whose responses all predate the stopwatch reports no time rather
        # than none-elapsed — the same absent-not-zero rule the token counts follow.
        llm_ms=timings.llm_ms or None,
        tool_ms=timings.tool_ms or None,
        ttft_ms_total=timings.ttft_ms_total or None,
        ttft_samples=timings.ttft_samples,
        context_window=run.context_window,
        context_used=footprint,
        context_thresholds=run.context_thresholds,
        # The split of that footprint. Scaled to the provider's own total, so the parts
        # always add up to the figure beside them even though each is an estimate.
        context_parts=compose(footprint, run.context_overhead, messages),
        # The last request on its own — read off the same path as everything else, so a
        # reload reports the route and the cache figures the live turn did.
        last_request=last_request_usage(messages),
    )


def no_room_for(
    run: Run,
    messages: list[ModelMessage],
    nudge: str,
    *,
    threshold: float | None,
    settings: Settings,
) -> bool:
    """Whether replaying ``messages`` plus ``nudge`` would already be over the operator's
    share of the window. ``False`` whenever there is no window or no threshold to measure
    against — the same rule the compaction trigger follows, for the same reason."""
    if not run.context_window or not threshold or threshold <= 0:
        return False
    projected = estimate_footprint(
        messages,
        run.context_overhead,
        fallback_overhead_tokens=settings.context_overhead_fallback_tokens,
    ) + estimate_tokens([ModelRequest(parts=[UserPromptPart(content=nudge)])])
    return projected >= run.context_window * threshold
