"""Conversation compaction — folding a thread's older turns into a utility-model summary.

**The product's only context reduction** (`AE-5.4`, `CHAT-4`), and the only one that ever
existed for a good reason: it fires on *measured pressure*, when a thread's footprint has
actually reached the operator's share of the model's context window. Everything else that
used to shrink content — digesting prior-turn tool results, capping an attachment's inline
text, trimming a code run's stdout — fired unconditionally, on turns under no pressure at
all, and has been removed. A large tool result now rides into context whole; the run's own
context-overflow stop is what catches a pathological turn.

Three properties make this safe to run automatically:

- **It fires between turns, never inside one.** The trigger sits in the orchestrator
  prelude, before the agent runs, so it can't pull an output out from under reasoning that
  is already in flight.
- **Nothing is destroyed.** The summary is appended as a new checkpoint node; the turns it
  covers stay in the tree, in the operator's transcript, and in cross-chat search. Only
  what is *re-sent to the model* narrows (``ConversationStore.model_history``). A rewind
  above the checkpoint restores the full replay for free.
- **It is not a safety net.** A prompt that overruns the window anyway still stops the run
  with a context notice. Compaction lowers the pressure; it never absorbs an overflow, and
  it never silently drops content to force a fit.

``auto_compact_keep_turns`` is **0** by default: the summary *is* what the model replays,
and a retained tail would restate verbatim what the summary already covers, at the exact
moment the thread has no room for it. The setting survives because the boundary is a turn
start, so a non-zero value replays the last few exchanges word for word — but nothing after
the boundary is kept unless the operator asks for it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from core.config import Settings, get_settings
from core.serde import jsonable
from core.text import strip_think_blocks, tokens_to_chars, truncate_middle
from prompts.utility import COMPACT_INSTRUCTIONS, COMPACT_PREAMBLE
from runs.overhead import TurnOverhead
from services.conversation_view import estimate_tokens, flatten_content
from services.conversations import CompactionPlan, ConversationStore, context_footprint
from services.settings_store import (
    SettingsStore,
    get_auto_compact,
    resolve_compaction_enabled,
)

from .footprint import estimate_footprint, overhead_fallback_tokens
from .meta import make_utility_agent

logger = logging.getLogger(__name__)

# Output-capped base settings, merged under the caller's reasoning-off settings and
# per-call `max_tokens` — the same shape `agent/title.py` uses, and for the same reason: a
# runtime that ignores the reasoning-off lever emits its `<think>` block as response
# tokens, so the budget has to cover the thinking *and* the summary.
_BASE_SETTINGS: ModelSettings = {"max_tokens": 2048, "temperature": 0.2}

# Per-entry cap on a rendered tool result. The whole transcript is capped again below, but
# without this one enormous tool output could consume the entire budget and push every
# actual exchange out of the summarizer's view.
_TOOL_RESULT_CHARS = 2000


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


def build_auto_compact_policy(
    settings: Settings, *, enabled: bool | None = None, threshold: float | None = None
) -> AutoCompactPolicy:
    """Resolve the effective policy from the config defaults, with optional operator
    overrides."""
    return AutoCompactPolicy(
        enabled=settings.auto_compact_enabled if enabled is None else enabled,
        threshold=settings.auto_compact_threshold if threshold is None else threshold,
        keep_turns=settings.auto_compact_keep_turns,
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
        messages, overhead, fallback_overhead_tokens=overhead_fallback_tokens(cfg)
    )
    return max(reported, estimated) + max(0, incoming_tokens) >= window * threshold


async def compact_conversation(
    store: ConversationStore,
    conversation_id: str,
    *,
    model: Model,
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
    resolved the summarizer's own context window can hold the input inside it."""
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
    ``message_history``. Replaying a main-model transcript into a different model means
    handing it that model's tool calls, thinking parts and provider-specific shapes — a
    reliable source of 400s — and the summarizer needs to *read* the exchange, not continue
    it. Best-effort and isolated, like titling: a model error or timeout leaves the thread
    uncompacted rather than failing the turn it was about to make room for, and any
    ``<think>`` block a runtime leaked into the output is stripped before it can become the
    thread's standing memory."""
    transcript = render_transcript(messages, max_input_tokens=max_input_tokens)
    if not transcript.strip():
        return None
    settings: ModelSettings = {**_BASE_SETTINGS, **(reasoning_off or {})}
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    agent = make_utility_agent(model, output_type=str, instructions=COMPACT_INSTRUCTIONS)
    try:
        run = agent.run(transcript, model_settings=settings)
        # asyncio.TimeoutError is an Exception subclass (caught below); CancelledError is
        # not, so a cancelled run still propagates rather than degrading to "no summary".
        result = await (asyncio.wait_for(run, timeout_s) if timeout_s else run)
    except Exception as exc:  # noqa: BLE001 — compaction is best-effort, never fails a turn
        logger.warning("conversation compaction summary failed: %s", exc)
        return None
    # Reasoning was requested off, but the lever is best-effort: a runtime that ignores it
    # inlines the chain-of-thought as a `<think>…</think>` block in the content. Left in,
    # that block *becomes* the thread's memory — the model would replay the summarizer's
    # scratch reasoning as established fact for the rest of the conversation. Same call the
    # namer makes, and it handles the unclosed block a truncated think emits.
    return strip_think_blocks(result.output).strip() or None


def render_transcript(messages: list[ModelMessage], *, max_input_tokens: int | None = None) -> str:
    """Render a message list as a labelled plain-text transcript for the summarizer.

    Thinking parts are deliberately dropped: a model's scratch reasoning is the least
    durable thing in the history and the most expensive per token, and none of it is a fact
    the continuing thread needs. Tool calls and their results are kept — what the agent
    looked up, and what came back, is exactly the sort of detail that must survive.

    The result is capped **head-and-tail** (:func:`core.text.truncate_middle`): what is
    being folded is by definition most of the *main* model's window, and the utility model
    may be smaller. Keeping both ends holds on to how the thread started and where it
    currently stands, and elides the middle it can no longer afford."""
    lines = [line for line in (_render(message) for message in messages) if line]
    transcript = "\n\n".join(lines)
    if max_input_tokens is None:
        return transcript
    head, tail, elided = truncate_middle(transcript, tokens_to_chars(max_input_tokens))
    if not elided:
        return head
    return f"{head}\n\n[… {elided} characters of the middle omitted …]\n\n{tail}"


def _render(message: ModelMessage) -> str:
    """One message as labelled transcript lines, or "" when it carries nothing useful."""
    lines: list[str] = []
    if isinstance(message, ModelRequest):
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                text = flatten_content(part.content).strip()
                if text:
                    lines.append(f"OPERATOR: {text}")
            elif isinstance(part, ToolReturnPart):
                lines.append(f"TOOL {part.tool_name} returned: {_result_text(part.content)}")
            elif isinstance(part, RetryPromptPart):
                lines.append(f"TOOL {part.tool_name} failed: {part.model_response()}")
    elif isinstance(message, ModelResponse):
        for part in message.parts:
            if isinstance(part, TextPart):
                text = part.content.strip()
                if text:
                    lines.append(f"ASSISTANT: {text}")
            elif isinstance(part, ToolCallPart):
                lines.append(f"ASSISTANT called {part.tool_name}({part.args_as_json_str()})")
    return "\n".join(lines)


def _result_text(content: object) -> str:
    """A tool result as a bounded one-line string — JSON-shaped results serialized, then
    capped so no single output can crowd the whole transcript out of the budget."""
    if isinstance(content, str):
        text = content
    else:
        try:
            text = str(jsonable(content))
        except Exception:  # noqa: BLE001 — an unserializable result is still worth naming
            text = f"<{type(content).__name__}>"
    head, tail, elided = truncate_middle(text.strip(), _TOOL_RESULT_CHARS)
    return head if not elided else f"{head} […{elided} chars…] {tail}"
