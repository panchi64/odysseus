"""When a *turn* folds the thread, how the fold is announced, and what it does to the
turn's persistence boundary.

``summarize.py`` is the fold itself — what gets read, what gets written, and the one path
all three triggers run through. This is the turn's side of it: the projected check that
fires one between turns, the mid-turn recovery that fires one after a provider refused the
request, the ``compaction.started``/``conversation.compacted`` pair each announces itself
with, and — the part only a turn can know — the rebuild of the history the retried request
is sent against, with the ``TurnStart`` boundary moved to match. A fold that happens inside
a turn moves the line between what the thread already had and what this turn is about to
persist; nowhere else has to think about that, which is why it is here and not there.

Nothing here reads settings for itself: the value rides on the ``CompactionContext`` the
turn built once, so every reading of the thread's size in one turn is against one object.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)

from runs import (
    CompactionReason,
    CompactionStarted,
    ConversationCompacted,
    Run,
    TurnOverhead,
)
from services.conversation_view import estimate_tokens

from .compaction_context import CompactionContext
from .history import (
    TurnStart,
    drop_dangling_tool_calls,
    merge_consecutive_requests,
)
from .metrics import turn_metrics
from .summarize import compact_conversation, should_compact

logger = logging.getLogger(__name__)


def incoming_request(
    user_prompt: str | list[Any] | None, extra: list[str]
) -> ModelRequest | None:
    """This turn's own new content as one request, for measuring it — the operator's
    message with its attachment markers, plus any per-turn context that isn't already
    inside it (a regenerate has no fresh prompt, so its context is the only new part).

    ``None`` when the turn adds nothing measurable, which is a plain regenerate with no
    context providers wired. Binary parts ride along untouched; the estimator ignores
    them by design."""
    parts: list[Any] = []
    if user_prompt is not None:
        parts.extend(user_prompt if isinstance(user_prompt, list) else [user_prompt])
    parts.extend(extra)
    return ModelRequest(parts=[UserPromptPart(content=parts)]) if parts else None


async def _fold(
    run: Run, ctx: CompactionContext, *, reason: CompactionReason
) -> list[ModelMessage] | None:
    """Run one compaction and announce it, returning the replay it leaves behind — or
    ``None`` when nothing folded.

    The one path every fold takes, whichever of the two triggers fired, so the pair cannot
    drift on what is emitted or in what order. Nothing here may raise: both callers are on
    the critical path of a turn, and compaction is an efficiency measure rather than a
    guard — when it fails, or frees nothing, the turn carries on and meets the model's real
    ceiling, which is the honest outcome.

    ``compaction.started`` goes out from inside the plan callback rather than before it, so
    it is emitted only once there is genuinely something to fold and can state what. It
    also refreshes the inactivity watchdog on the way past, which matters more than it
    looks: the summarizer is a whole model call with its own timeout, and it emits nothing
    while it runs."""
    try:
        outcome = await compact_conversation(
            ctx.store,
            ctx.conversation_id,
            model=ctx.model,
            reason=reason,
            reasoning_off=ctx.reasoning_off,
            keep_turns=ctx.policy.keep_turns,
            settings=ctx.settings,
            max_input_tokens=ctx.max_input_tokens,
            on_plan=lambda plan: run.emit(
                CompactionStarted(
                    conversation_id=ctx.conversation_id,
                    reason=reason,
                    messages=len(plan.messages),
                    tokens_estimate=estimate_tokens(plan.messages),
                )
            ),
        )
    except Exception:  # noqa: BLE001 — an optimization must never take the turn down with it
        logger.warning("compaction failed for %s", ctx.conversation_id, exc_info=True)
        return None
    if outcome is None:
        return None
    run.emit(
        ConversationCompacted(
            conversation_id=ctx.conversation_id,
            reason=reason,
            message_id=outcome.message_id,
            summary=outcome.summary,
            messages_compacted=outcome.messages_compacted,
            tokens_before=outcome.tokens_before,
            tokens_after=outcome.tokens_after,
            after_message_id=outcome.after_message_id,
        )
    )
    return await ctx.store.model_history(ctx.conversation_id)


async def maybe_compact(
    run: Run,
    ctx: CompactionContext | None,
    history: list[ModelMessage],
    *,
    overhead: TurnOverhead | None,
    incoming_tokens: int,
    context_window: int | None,
) -> tuple[list[ModelMessage], bool]:
    """Fold this conversation's older turns when the turn *about to run* would reach the
    operator's share of the model's context window, returning the history to replay and
    whether anything folded.

    The trigger is projected, not retrospective: ``incoming_tokens`` is this turn's own
    prompt, its attachments and the per-turn context appended to it, all of which are
    resolved before this runs precisely so they can be counted here. A thread at 70% that
    is about to be handed a 15% prompt is a thread that needs folding now, and measuring
    the history alone could not see that.

    Returns ``history`` unchanged whenever compaction is off, unmeasurable (no declared
    window), not yet due, has nothing left to fold, or the summarizer failed."""
    if ctx is None or not ctx.policy.enabled:
        return history, False
    if not should_compact(
        history,
        context_window,
        ctx.policy.threshold,
        overhead=overhead,
        incoming_tokens=incoming_tokens,
        settings=ctx.settings,
    ):
        return history, False
    folded = await _fold(run, ctx, reason="threshold")
    return (history, False) if folded is None else (folded, True)


def _without_empty_tail(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Drop the empty response the streaming path leaves behind when a request fails.

    Pydantic AI appends a placeholder ``ModelResponse`` to the history before it starts
    streaming into it, so a request the provider refuses outright leaves a partless
    response as the tail. It is not a message — nothing was generated — and leaving it
    there would end the rebuilt history on a response, which is not a shape a turn can be
    resumed from."""
    while messages and isinstance(messages[-1], ModelResponse) and not messages[-1].parts:
        messages = messages[:-1]
    return messages


async def compact_and_retry(
    run: Run,
    ctx: CompactionContext,
    *,
    partial_history: list[ModelMessage],
    turn_start: TurnStart,
) -> list[ModelMessage] | None:
    """Fold the thread mid-turn and rebuild the history the failed request will be re-sent
    against, or ``None`` when nothing folded.

    The turn's own messages are not recorded yet, so the tree's leaf is still the previous
    tip and the checkpoint lands exactly where the prelude's fold would have put it. What
    the model replays afterwards is the folded history *plus this turn so far* — the
    operator's prompt, the tool calls it has already made and their results, none of which
    is in the tree yet and all of which the retried request depends on.

    The order below is load-bearing:

    - the dangling-call strip runs on the folded history alone, because a *retained* turn
      that once stopped at a bound can end on an unanswered tool call, and this turn's own
      trailing call is answered by the very request being retried;
    - the merge runs over the **concatenation**, because the library merges consecutive
      requests when it cleans a history it is resuming, and a checkpoint hoisted in front
      of a turn that opens on a user prompt is exactly that shape. Pre-merging is what
      keeps ``all_messages()`` the length we measured our index against;
    - the boundary is then read off the two sides' *shapes*, because that merge can leave
      the turn beginning inside a message the folded history also owns. Half a message is
      still a boundary: without recording how much of it is the turn's own, the persist
      re-records the checkpoint summary — and whatever else the replay put in front of the
      prompt, the reinjected brief included — as new operator messages.

    An operator who switched compaction off for this thread is not overruled by an
    overflow: they get the stop, and the **Compact and retry** it offers, which is the
    same fold under their own hand.
    """
    if not ctx.policy.enabled:
        return None
    folded = await _fold(run, ctx, reason="overflow")
    if folded is None:
        return None
    # Merged per side first, so the only merge the concatenation can still perform is the
    # one at the boundary — which is the one the index has to know about. Reading it off
    # the two shapes is exact; reading it off the lengths would mistake a merge *inside*
    # either side for a collapsed boundary.
    head = merge_consecutive_requests(drop_dangling_tool_calls(folded))
    turn_slice = merge_consecutive_requests(
        _without_empty_tail(partial_history[turn_start.index :])
    )
    collapsed = (
        bool(head)
        and bool(turn_slice)
        and isinstance(head[-1], ModelRequest)
        and isinstance(turn_slice[0], ModelRequest)
    )
    rebuilt = merge_consecutive_requests([*head, *turn_slice])
    turn_start.index = len(head) - 1 if collapsed else len(head)
    turn_start.parts = len(turn_slice[0].parts) if collapsed else 0
    # Nothing in the rebuilt replay was measured against the thread as it now stands — this
    # turn's own responses included, since they reported their prompt size before the fold.
    # So the boundary is the whole replay: the frame below reads the estimate, and the first
    # believable reported figure is the one the retry itself comes back with.
    run.fold_boundary = len(rebuilt)
    # And it goes out *now*, not when the retry answers. A fold that frees half the thread
    # and then overruns again would otherwise leave the gauge pinned at its pre-fold figure
    # for good — the operator watching a compaction that visibly changed nothing.
    run.emit(turn_metrics(run, rebuilt, settings=ctx.settings))
    return rebuilt
