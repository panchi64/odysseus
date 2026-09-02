"""Conversation compaction — folding a thread's older turns into a utility-model summary.

**The product's only context reduction** (`AE-5.4`, `CHAT-4`), and the only one that ever
existed for a good reason: it fires on *measured pressure*, when a thread's footprint has
actually reached the operator's share of the model's context window. Everything else that
used to shrink content — digesting prior-turn tool results, capping an attachment's inline
text, trimming a code run's stdout — fired unconditionally, on turns under no pressure at
all, and has been removed. A large tool result now rides into context whole; the run's own
context-overflow stop is what catches a pathological turn.

Three properties make this safe to run automatically:

- **It never fires underneath reasoning in flight.** The trigger sits in the orchestrator
  prelude, before the agent runs, and measures what the turn *about to run* will cost. The
  one exception is the recovery: when a provider refuses a request as over-long, the turn
  folds once and re-sends that same request — between two requests, with nothing in
  flight, which is the only mid-turn moment at which folding is safe.
- **Nothing is destroyed.** The summary is appended as a new checkpoint node; the turns it
  covers stay in the tree, in the operator's transcript, and in cross-chat search. Only
  what is *re-sent to the model* narrows (``ConversationStore.model_history``). A rewind
  above the checkpoint restores the full replay for free.
- **It is still not a safety net.** A fold gets *one* attempt at an overflow. A request
  that is too big after it is too big for a reason folding cannot reach, and the run stops
  with a context notice rather than re-folding a thread down to nothing. Compaction lowers
  the pressure; it never silently drops content to force a fit.

What the summarizer is allowed to read, and how the text it produces is trusted afterwards,
live next door: :mod:`agent.compaction_transcript` renders the fold (tool output fenced,
turns chunked to fit rather than elided) and :mod:`agent.compaction_summary` handles what
comes back (anchors carried across folds verbatim, tool-sourced facts fenced on the way
into the checkpoint). This module owns *when* a thread folds and *what is recorded*.

``auto_compact_keep_turns`` is **3** by default, and is an operator setting beside the
threshold rather than a config-only knob. The boundary is a turn start, so the last three
exchanges are replayed word for word under the summary: a summary is at its most lossy
about the work in flight, which is exactly the work the next turn continues. 0 is still a
legal choice — the summary then *is* the whole replay — and the operator makes it in
Settings, not in a deploy's environment.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.config import Settings, get_settings
from prompts.utility import COMPACT_PREAMBLE
from runs.events import CompactionReason
from runs.overhead import TurnOverhead
from services.conversation_view import estimate_footprint, estimate_tokens
from services.conversations import CompactionPlan, ConversationStore, context_footprint
from services.settings_store import (
    SettingsStore,
    get_auto_compact,
    resolve_compaction_enabled,
)

from .compaction_summary import (
    carried_anchors,
    fence_tool_facts,
    merge_anchors,
    summarize_chunks,
)
from .compaction_transcript import transcript_chunks
from .history import revealed_tools

logger = logging.getLogger(__name__)

# Output-capped base settings, merged under the caller's reasoning-off settings and
# per-call `max_tokens` — the same shape `agent/title.py` uses, and for the same reason: a
# runtime that ignores the reasoning-off lever emits its `<think>` block as response
# tokens, so the budget has to cover the thinking *and* the summary.
_BASE_SETTINGS: ModelSettings = {"max_tokens": 2048, "temperature": 0.2}


@dataclass(frozen=True)
class AutoCompactPolicy:
    """The effective conversation-compaction policy for one turn.

    Resolved at the route (operator default folded with the per-conversation override) and
    handed to the orchestrator, the same way the per-turn request limit is — so the engine
    never reads the settings store itself."""

    enabled: bool
    threshold: float
    keep_turns: int


@dataclass(frozen=True)
class CompactionOutcome:
    """What a compaction actually folded, for the event the run emits."""

    message_id: str
    summary: str
    messages_compacted: int
    # What the fold cost, in coarse `estimate_tokens` terms: over the folded messages, and
    # over the summary that replaced them. The same proxy the trigger measures with, so
    # the divider's "~62k → ~4k" is consistent with the gauge the operator was watching.
    tokens_before: int
    tokens_after: int
    # The rendered turn the divider follows, so a live client places it where a reload will.
    after_message_id: str | None
    # What triggered this fold, echoed back from the caller. Carried on the outcome rather
    # than only on the caller's own event because it is also what was written onto the
    # checkpoint — one value, so the divider a reload draws names the same cause the live
    # one did.
    reason: CompactionReason = "threshold"


def build_auto_compact_policy(
    settings: Settings,
    *,
    enabled: bool | None = None,
    threshold: float | None = None,
    keep_turns: int | None = None,
) -> AutoCompactPolicy:
    """Resolve the effective policy from the config defaults, with optional operator
    overrides.

    ``keep_turns`` takes ``None`` for "not overridden" rather than treating 0 as unset: 0 is
    a choice the operator can make (the summary becomes the whole replay), so it has to be
    distinguishable from an absent preference."""
    return AutoCompactPolicy(
        enabled=settings.auto_compact_enabled if enabled is None else enabled,
        threshold=settings.auto_compact_threshold if threshold is None else threshold,
        keep_turns=settings.auto_compact_keep_turns if keep_turns is None else keep_turns,
    )


async def resolve_auto_compact_policy(
    store: SettingsStore, owner_id: str, *, override: bool | None = None
) -> AutoCompactPolicy:
    """The effective policy for one turn: the operator's stored preferences, with a
    conversation's on/off ``override`` folded in on top.

    The one place the precedence lives, so the interactive path and the scheduler's
    unattended one can't disagree about whether compaction is on."""
    stored = await get_auto_compact(store, owner_id)
    return build_auto_compact_policy(
        get_settings(),
        enabled=resolve_compaction_enabled(override, stored.enabled),
        threshold=stored.threshold,
        keep_turns=stored.keep_turns,
    )


def should_compact(
    messages: list[ModelMessage],
    window: int | None,
    threshold: float,
    *,
    overhead: TurnOverhead | None = None,
    incoming_tokens: int = 0,
    settings: Settings | None = None,
) -> bool:
    """Whether the turn *about to run* would reach the operator's share of the window.

    **Projected, not retrospective.** The history's own footprint is what the last turn
    cost; the number that matters is what this turn will cost, which is that plus the
    operator's new prompt, its attachments and the per-turn context appended to it
    (``incoming_tokens``). Measuring only the history is why a threshold had to sit at 95%
    to be safe — it left the incoming turn to fit in whatever the previous one happened not
    to use.

    The two sources of the current size are taken at their **maximum**: the provider's own
    reported prompt size (exact, but absent on the local servers this workspace mostly
    talks to, and stale the moment anything is added), and the estimate over the messages
    plus this thread's measured brief + tool schemas. Whichever reads larger is the one
    that decides — under-reading here is what lets a thread walk into the overflow the fold
    exists to prevent.

    ``False`` when the endpoint declares no window: there is nothing to measure against,
    and compacting on a guess would fold a thread that was never under pressure."""
    if not window or threshold <= 0:
        return False
    cfg = settings or get_settings()
    reported = context_footprint(messages) or 0
    estimated = estimate_footprint(
        messages, overhead, fallback_overhead_tokens=cfg.context_overhead_fallback_tokens
    )
    return max(reported, estimated) + max(0, incoming_tokens) >= window * threshold


async def compact_conversation(
    store: ConversationStore,
    conversation_id: str,
    *,
    model: Model,
    reason: CompactionReason,
    reasoning_off: ModelSettings | None = None,
    keep_turns: int | None = None,
    settings: Settings | None = None,
    max_input_tokens: int | None = None,
    on_plan: Callable[[CompactionPlan], None] | None = None,
) -> CompactionOutcome | None:
    """Fold this conversation's older turns into a summary checkpoint, or ``None`` when
    there was nothing to fold, the summarizer failed, or the plan went stale.

    The one path both callers share — the engine's automatic trigger and the operator's
    manual "compact now" — so the two can't drift on what gets folded or how it's recorded.

    A **summarizer** failure is swallowed here (it degrades to "no compaction"), but a store
    failure is not: the operator pressing "compact now" should be told the write failed, not
    that there was nothing to fold. The automatic caller wraps this so a turn never dies for
    a compaction it only wanted as an optimization.

    ``on_plan`` is called once the fold is known and *before* the summarizer runs — the one
    moment at which what is about to be folded can be announced, since the summarizer call
    is the seconds-long part. The engine emits ``compaction.started`` from it; a caller with
    nothing to announce passes nothing.

    ``max_input_tokens`` overrides the configured transcript budget, so a turn that has
    resolved the summarizer's own context window can hold the input inside it.

    ``reason`` is required rather than defaulted, and travels all the way onto the stored
    checkpoint. Each of the three callers knows which trigger it is — the threshold, the
    mid-turn overflow recovery, the operator's own button — and a default here would let a
    new one silently record the most common answer instead of its own."""
    cfg = settings or get_settings()
    plan = await store.compaction_plan(
        conversation_id,
        keep_turns=cfg.auto_compact_keep_turns if keep_turns is None else keep_turns,
    )
    if plan is None:
        return None
    if on_plan is not None:
        on_plan(plan)
    summary = await summarize_history(
        model,
        plan.messages,
        reasoning_off=reasoning_off,
        timeout_s=cfg.auto_compact_timeout_s,
        max_tokens=cfg.auto_compact_max_tokens,
        max_input_tokens=(
            cfg.auto_compact_input_max_tokens if max_input_tokens is None else max_input_tokens
        ),
    )
    if not summary:
        return None
    # Labelled on the way in, not on the way out: the stored text is what both the model
    # replays and the operator reads, and it needs to announce itself as a summary in both
    # places. The same framed text rides the event, so the divider a live client draws and
    # the one a reload draws are the same string.
    labelled = f"{COMPACT_PREAMBLE}\n\n{summary}"
    message_id = store.record_compaction(
        conversation_id,
        summary=labelled,
        through_id=plan.through_id,
        expected_leaf_id=plan.expected_leaf_id,
        reason=reason,
        # A fold must not quietly un-reveal a dormant group. The messages it replaces are
        # the only record that the model ever loaded the browser (or the mailbox), and the
        # library reads that record fresh on every request — so what the folded stretch
        # revealed is carried onto the checkpoint, and the thread keeps the tools it was
        # working with. Read off `plan.messages` rather than the whole thread: the retained
        # tail still carries its own reveals, and a *previous* checkpoint's carried delta is
        # inside this fold, so a second fold inherits the first's without special-casing.
        revealed_tools=revealed_tools(plan.messages),
    )
    if message_id is None:
        # The active leaf moved while the summary was being written (a version switch or a
        # rewind — the conversation claim blocks runs, not navigation). The summary now
        # describes a path the operator isn't on, so drop it rather than graft it.
        logger.info("compaction for %s discarded: the active leaf moved", conversation_id)
        return None
    return CompactionOutcome(
        message_id=message_id,
        summary=labelled,
        messages_compacted=len(plan.messages),
        # Measured over the same two things the projection re-measures on a cold read —
        # the folded messages, and the stored checkpoint text — so the live divider and
        # the reloaded one report the same numbers.
        tokens_before=estimate_tokens(plan.messages),
        tokens_after=estimate_tokens([ModelRequest(parts=[UserPromptPart(labelled)])]),
        after_message_id=plan.anchor_id,
        reason=reason,
    )


async def summarize_history(
    model: Model,
    messages: list[ModelMessage],
    *,
    reasoning_off: ModelSettings | None = None,
    timeout_s: float | None = None,
    max_tokens: int | None = None,
    max_input_tokens: int | None = None,
) -> str | None:
    """Summarize a stretch of conversation into the briefing that will stand in for it, or
    ``None`` on any failure.

    The history is rendered to a **plain-text transcript** rather than replayed as
    ``message_history`` (:mod:`agent.compaction_transcript`). Replaying a main-model
    transcript into a different model means handing it that model's tool calls, thinking
    parts and provider-specific shapes — a reliable source of 400s — and the summarizer
    needs to *read* the exchange, not continue it.

    **A transcript larger than the summarizer's window is chunked, not cut.** It splits at
    turn boundaries into pieces that fit ``max_input_tokens``, each is summarized (map) and
    the partial summaries are merged into one (reduce). The alternative — eliding the
    middle — throws away whatever happened in the middle of the thread, which is usually
    where the work was. All of it runs under **one** ``timeout_s`` deadline, so a chunked
    fold can't outlast the single-call budget the run allowed for it.

    Best-effort and isolated, like titling: a model error or timeout leaves the thread
    uncompacted rather than failing the turn it was about to make room for, and any
    ``<think>`` block a runtime leaked into the output is stripped from **every** call
    before it can become the thread's standing memory."""
    chunks = transcript_chunks(messages, max_input_tokens=max_input_tokens)
    if not chunks:
        return None
    settings: ModelSettings = {**_BASE_SETTINGS, **(reasoning_off or {})}
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    summary = await summarize_chunks(model, chunks, settings=settings, timeout_s=timeout_s)
    if not summary:
        return None
    # Anchors are what a re-summarized summary loses first, so a second fold carries the
    # previous checkpoint's exact paths, ids and numbers across verbatim rather than asking
    # a model to restate them one more time.
    summary = merge_anchors(summary, carried_anchors(messages))
    # Fenced on the way out, because this text is stored as a user-shaped checkpoint the
    # main model replays as its own memory: the one section that repeats what a page or a
    # document said must stay marked as data.
    return fence_tool_facts(summary)
