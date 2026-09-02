"""Ruling on the calls a turn deferred — the engine's half of the decision.

A model turn that wants a sensitive tool ends with the call *unexecuted* and the question
open: does this run, does it get refused, or does it go to the operator? Answering it is
this module's whole job. :func:`settle_deferred` walks the batch and returns the two piles
the turn continues on — the calls settled without a human, and the ones that need one —
so ``turn.py`` is left with control flow rather than policy.

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

**One review pass per batch, and it runs concurrently.** A model turn can defer several
calls at once, and each is judged on its own — the deterministic stage may clear three and
send the fourth to the model — but everything a review needs that is *not* per-call is
built once for the batch: the reviewer (a registry resolution and a model construction)
and the transcript (a walk of the recent history into one string the reviewer reads
verbatim). The model calls that remain are independent of one another and each carries a
timeout measured in seconds, so they are awaited together rather than in a line; a turn
that deferred four calls waits once, not four times.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic_ai import ToolApproved, ToolDenied
from pydantic_ai.messages import ModelMessage, ToolCallPart

from core.concurrency import gather_bounded
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

#: How many reviews of one batch may be in flight at once. Each is a utility-model round
#: trip, so the cap protects the far side (and a local runtime's own queue) rather than
#: this process; a turn rarely defers more than a handful of calls, and the point is that
#: their latencies overlap rather than stack.
_REVIEW_CONCURRENCY = 4


@dataclass(kw_only=True)
class GrantApproved(ToolApproved):
    """An approval a standing conversation grant produced, marked as one.

    The approve route re-validates what a parked turn settled without the operator, because
    a grant can be revoked — or lapse by TTL — while the run waits. Only a *grant's*
    approval has anything to re-validate, though: Auto's review leaves no grant behind, so
    a review-cleared call re-checked against the grants comes back uncovered and is denied
    a call the operator was never offered and never refused.

    The mark rides on the decision rather than beside it because the decision is the only
    part of the settled pile that crosses into the parked payload, and a provenance kept
    anywhere else would have to be carried through by hand at every hop that touches it.
    """


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

    **The level rules first, and a grant may answer it but never overturn it.** A standing
    grant is the operator's "stop asking me about this one", so it settles a call the level
    would have put in front of them. But a level that refuses outright carries their answer
    already, in the level they chose — a grant recorded while a thread could act is not
    consent to act in one they have since set to act in nothing, and Plan's whole contract
    is that nothing changes. The resume path reads it the same way (``routes/runs.py``): a
    denial the level made carries forward verbatim, and no grant undoes it. Grants are
    conversation-scoped, so a stateless turn always asks.

    Two refusals, not one, because a model that read them as the same fact would take the
    wrong next step: the level does not permit this act at all (the operator already
    answered by choosing the level), or the Auto review found it unrecoverable.
    """
    granted: set[str] = set()
    grants = caps.get_optional(ApprovalGrantStore)
    if grants is not None and conversation_id is not None:
        granted = await grants.active(run.owner_id, conversation_id)
    # Ruled on before anything is reviewed, so the batch knows which calls need a model at
    # all before it pays to resolve one.
    ruled = [(call, _by_level(permission, call.tool_name, granted)) for call in approvals]
    reviewed = await review_batch(
        run,
        [call for call, decision in ruled if decision is Decision.REVIEW],
        caps=caps,
        deps=deps,
        messages=messages,
    )
    settled: dict[str, ToolApproved | ToolDenied] = {}
    manual: list[ToolCallPart] = []
    for call, decision in ruled:
        outcome = reviewed.get(call.tool_call_id)
        if outcome is not None:
            decision = outcome.decision
        if decision is Decision.ALLOW:
            # Reviewed, or covered by a grant — and which of the two is recorded, because
            # only the second is still worth re-checking when the operator answers.
            settled[call.tool_call_id] = (
                ToolApproved() if outcome is not None else GrantApproved()
            )
        elif decision is Decision.BLOCK:
            settled[call.tool_call_id] = ToolDenied(
                message=review_refusal(call.tool_name, outcome.reason)
                if outcome is not None
                else blocked_message(permission, call.tool_name)
            )
        else:
            manual.append(call)
    return settled, manual


def _by_level(permission: str, tool: str, granted: set[str]) -> Decision:
    """What the thread's level says about one call, with the operator's standing grants
    allowed to answer — but only where the level was asking a question."""
    decision = decide(permission, tool)
    if decision is not Decision.BLOCK and covered_by_grant(tool, granted):
        return Decision.ALLOW
    return decision


async def review_batch(
    run: Run,
    calls: Sequence[ToolCallPart],
    *,
    caps: ServiceContainer,
    deps: RunDeps,
    messages: list[ModelMessage],
) -> dict[str, ReviewOutcome]:
    """Review every call the level sent to review, by ``tool_call_id``.

    The reviewer and the transcript are built once for the batch and shared: resolving a
    reviewer is a registry lookup and a model construction, and the transcript is the same
    walk over the same recent history for every call in the turn — rebuilt per call it was
    several kilobytes of identical string per deferred tool.
    """
    if not calls:
        return {}
    reviewer = await resolve_reviewer(caps, run.owner_id)
    transcript = review_transcript(messages, limit=get_settings().review_transcript_messages)
    outcomes = await gather_bounded(
        [
            review_call(
                run,
                tool_call_id=call.tool_call_id,
                tool=call.tool_name,
                args=call.args_as_dict(),
                deps=deps,
                transcript=transcript,
                reviewer=reviewer,
            )
            for call in calls
        ],
        _REVIEW_CONCURRENCY,
    )
    return {call.tool_call_id: outcome for call, outcome in zip(calls, outcomes, strict=True)}


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
    transcript: str,
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
    outcome = await review(capability, reviewer=reviewer, transcript=transcript)
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
