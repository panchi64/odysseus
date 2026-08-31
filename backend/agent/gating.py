"""Ruling on the calls a turn deferred — the engine's half of the decision.

A model turn that wants a sensitive tool ends with the call *unexecuted* and the question
open: does this run, does it get refused, or does it go to the operator? Answering it is
this module's whole job. :func:`settle_deferred` walks the batch and returns the two piles
the turn continues on — the calls settled without a human, and the ones that need one —
so ``engine.py`` is left with control flow rather than policy.

``services/permissions`` owns the rules: what an action reaches, whether a deterministic
allowlist clears it, and what a model's three scores add up to. None of that knows about
runs, streams or capability bags, and it should not. This module is the seam between the
two: it resolves the reviewer from the run's capabilities, hands the rules everything they
need, and announces what happened on the run's own event stream.

**Why the announcement is not optional.** Auto's whole proposition is that the operator's
approvals are given for them. That is only acceptable if it is *visible* — so a reviewed
call emits ``review.started`` before it is ruled on and ``review.completed`` after, and
those land in the work log beside the call they judged. Without them the operator sees a
tool call they never approved and no account of why it ran, which is indistinguishable
from the gate having silently failed open.

**One reviewer per batch, resolved once.** A model turn can defer several calls at once,
and each is judged on its own — the deterministic stage may clear three and send the
fourth to the model — but building a reviewer is a registry resolution and a model
construction, and doing it per call would pay that cost for calls the judge settles for
free.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic_ai import ToolApproved, ToolDenied
from pydantic_ai.messages import ModelMessage, ToolCallPart

from core.config import get_settings
from core.container import ServiceContainer
from runs import Run
from runs.events import ReviewCompleted, ReviewStarted
from services.approval_grants import ApprovalGrantStore, covered_by_grant
from services.permissions import (
    Decision,
    Reviewer,
    ReviewOutcome,
    blocked_message,
    capability_of,
    decide,
    make_utility_reviewer,
    review,
    review_refusal,
    review_transcript,
)
from services.registry import ModelRegistry
from tools.deps import RunDeps

logger = logging.getLogger(__name__)


async def settle_deferred(
    run: Run,
    approvals: Sequence[ToolCallPart],
    *,
    caps: ServiceContainer,
    conversation_id: str | None,
    deps: RunDeps,
    messages: list[ModelMessage],
    permission: str,
) -> tuple[dict[str, ToolApproved | ToolDenied], list[ToolCallPart]]:
    """Rule on every call this hop deferred, returning ``(settled, manual)``.

    ``settled`` is the decisions the turn can carry on with immediately — an allow the
    model never notices, or a denial it is told in place of the tool's result and re-plans
    around. ``manual`` is what is left for the operator, and a non-empty one is what parks
    the turn.

    An explicit standing decision outranks any policy, so a conversation grant is consulted
    first — and its answer is spelled in the same vocabulary the level's is, leaving one
    dispatch below rather than two. Grants are conversation-scoped, so a stateless turn
    always asks.

    Two refusals, not one, because a model that read them as the same fact would take the
    wrong next step: the level does not permit this act at all (the operator already
    answered by choosing the level), or the Auto review found it unrecoverable.
    """
    granted: set[str] = set()
    grants = caps.get_optional(ApprovalGrantStore)
    if grants is not None and conversation_id is not None:
        granted = await grants.active(run.owner_id, conversation_id)
    settled: dict[str, ToolApproved | ToolDenied] = {}
    manual: list[ToolCallPart] = []
    # Resolved lazily and at most once per batch: building a reviewer is a registry
    # resolution and a model construction, and the deterministic stage settles most
    # calls without ever needing one.
    reviewer: Reviewer | None = None
    reviewer_resolved = False
    for call in approvals:
        decision = (
            Decision.ALLOW
            if covered_by_grant(call.tool_name, granted)
            else decide(permission, call.tool_name)
        )
        reviewed: ReviewOutcome | None = None
        if decision is Decision.REVIEW:
            # Auto: the operator asked for their answers to be given for them, so a
            # judge and then a reviewer give one. Both ends land on the stream, so the
            # operator can always read afterwards why something ran without them.
            if not reviewer_resolved:
                reviewer = await resolve_reviewer(caps, run.owner_id)
                reviewer_resolved = True
            reviewed = await review_call(
                run,
                tool_call_id=call.tool_call_id,
                tool=call.tool_name,
                args=call.args_as_dict(),
                deps=deps,
                messages=messages,
                reviewer=reviewer,
            )
            decision = reviewed.decision
        if decision is Decision.ALLOW:
            settled[call.tool_call_id] = ToolApproved()
        elif decision is Decision.BLOCK:
            settled[call.tool_call_id] = ToolDenied(
                message=review_refusal(call.tool_name, reviewed.reason)
                if reviewed is not None
                else blocked_message(permission, call.tool_name)
            )
        else:
            manual.append(call)
    return settled, manual


async def resolve_reviewer(caps: ServiceContainer, owner_id: str) -> Reviewer | None:
    """The Auto reviewer for this run, or None when there is nothing to review with.

    Resolves the **utility** role through the same ``resolve_background`` rule titling,
    verification and delegation use, so the review is cheap by construction rather than by
    a second policy — and so an operator who has bound only ``main`` still gets one.

    None is the degraded answer, and every caller turns it into a park. That is the one
    place in this codebase where the conservative branch has to be the default: a review
    that cannot run is not a review that passes.
    """
    registry = caps.get_optional(ModelRegistry)
    if registry is None:
        return None
    try:
        resolved = await registry.resolve_background(owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001 — an unbound role is a degrade, not an error
        logger.info("auto review unavailable: no utility model (%s)", exc)
        return None
    settings = get_settings()
    return make_utility_reviewer(
        resolved.model,
        # Reasoning off for the same reason the namer and the judge request it: this is
        # background work inside a turn the operator is watching, and the three scored
        # fields are read off the structured output whatever the model thinks first.
        model_settings=resolved.reasoning_off,
        timeout_s=settings.review_timeout_s,
        max_tokens=settings.review_max_tokens,
    )


async def review_call(
    run: Run,
    *,
    tool_call_id: str,
    tool: str,
    args: dict,
    deps: RunDeps,
    messages: Sequence[ModelMessage],
    reviewer: Reviewer | None,
) -> ReviewOutcome:
    """Rule on one deferred call at the Auto level, announcing both ends on the stream.

    The workspace root comes off the run's own memoised binding when a tool has already
    resolved one this turn (``tools/workspace.py``), and is None otherwise — which is not
    a gap but the strictest reading: with nowhere to measure containment against, every
    absolute or upward path in a command reads as leaving the workspace and escalates.
    """
    workspace = deps.workspace
    capability = capability_of(tool, args, root=workspace.root if workspace else None)
    run.emit(ReviewStarted(tool_call_id=tool_call_id, name=tool, summary=capability.summary))
    outcome = await review(
        capability,
        reviewer=reviewer,
        transcript=review_transcript(messages, limit=get_settings().review_transcript_messages),
    )
    verdict = outcome.verdict
    run.emit(
        ReviewCompleted(
            tool_call_id=tool_call_id,
            name=tool,
            # `review` never returns REVIEW — it is what resolves one — so the cast to the
            # wire's three-value vocabulary is total. Spelled as a lookup rather than a
            # str() so a fourth Decision member would fail here rather than on a client.
            decision=_WIRE_DECISION[outcome.decision],
            stage=outcome.stage,
            reason=outcome.reason,
            risk=verdict.risk if verdict else None,
            authorization=verdict.authorization if verdict else None,
            correctness=verdict.correctness if verdict else None,
        )
    )
    return outcome


#: The outcomes a review can produce, on the wire. `REVIEW` is deliberately absent: it is
#: the question, not an answer, and a review that returned it would be a bug rather than
#: a fourth case to render.
_WIRE_DECISION: dict[Decision, str] = {
    Decision.ALLOW: "allow",
    Decision.ASK: "ask",
    Decision.BLOCK: "block",
}
