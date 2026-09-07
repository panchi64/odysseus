"""What to do with a tool call the model wants to make — one function, four answers.

The engine reaches here at the single point where Pydantic AI hands back a *deferred*
call: a call the library declined to execute and returned for someone to rule on. Two
things put a call in that list, and telling them apart is the whole job of this module:

- **the level put it there.** The toolset marks every tool that reaches past the level's
  ceiling as needing approval (``tools/toolsets.py``), so the model's request for one
  comes back undone. This is the level's own question, and the level's approval policy
  answers it: withheld under Plan (so the call is refused outright rather than asked
  about), parked under Manual and Edit, reviewed under Auto.
- **the tool put itself there.** A global recall, a skill edit, an untrusted external
  tool — tools that gate their own calls for reasons this axis knows nothing about. Those
  are the operator's to answer, which is why they come back ``ASK`` even under a level
  whose scope would have permitted them. A level widens a gate; it never narrows one
  (``levels.py``). Auto is not an exception to that: it answers them by review because
  answering on the operator's behalf is the whole of what choosing Auto means.

**Why the vocabulary has four members when the knobs produce three.** ``ALLOW`` is what a
standing conversation grant produces — the operator's explicit "stop asking me about this
one" — and it is also the verdict Auto's review returns for a call it clears. Expressing
both in the same vocabulary is what keeps the engine to one dispatch. Note where the grant
sits in that dispatch (``agent/gating.py``): it answers a question this module *asked*,
and never overturns a refusal. A grant is consent to skip a prompt, not consent to act in
a thread the operator set to act in nothing. **At Auto it does not answer the question at
all** — it is carried into the review as the operator's authorization (:func:`review`),
because at that level the question was never "may this tool run" but "what would this call
do", and a grant on `shell_run_command` is not an answer to that for every command.

**The second half of this module is that review** (:func:`review`), which is what
``REVIEW`` resolves to: the deterministic stage first (``judge.py``), the model second
(``reviewer.py``), and the arithmetic over their answers here — deliberately *here*,
where a reader can see the whole rule at once and where the reviewer cannot read it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from services.permissions.capability import Capability
from services.permissions.judge import Tier, judge
from services.permissions.levels import ApprovalPolicy, beyond_scope, permission_spec
from services.permissions.reviewer import (
    Authorization,
    Reviewer,
    ReviewRequest,
    ReviewVerdict,
    TranscriptEntry,
)


class Decision(StrEnum):
    """What happens to one deferred tool call."""

    #: Run it, with no operator round-trip. Never the answer to a *level's* question —
    #: only to the operator's own standing grant, and to a review that cleared it.
    ALLOW = "allow"
    #: Judge and review it (Auto) — :func:`review` settles it into one of the other
    #: three. Not itself an outcome: a caller that cannot run the review parks.
    REVIEW = "review"
    #: Park the run and put the call in front of the operator.
    ASK = "ask"
    #: Refuse it and tell the model why (:func:`blocked_message`). Only a *level* produces
    #: this: under Plan the operator's answer is already on the record, in the level they
    #: chose. Auto's review never does — an unrecoverable act is the case the operator most
    #: needs to be shown, so it parks instead of being refused on their behalf.
    BLOCK = "block"


#: The three answers a level gives to a call that reached past its ceiling.
_BY_POLICY = {
    ApprovalPolicy.WITHHOLD: Decision.BLOCK,
    ApprovalPolicy.ASK: Decision.ASK,
    ApprovalPolicy.REVIEW: Decision.REVIEW,
}


def decide(level: str, tool: str) -> Decision:
    """Rule on one deferred call to ``tool`` in a thread at ``level``.

    Pure and total: an unknown level resolves to the strictest one and an unclassified
    tool to the class that reaches furthest, so neither a corrupt stored value nor an
    operator's own MCP tool can arrive here and be waved through. Never returns ``ALLOW``
    — a level permits by *not deferring in the first place*, so anything that reaches this
    is something someone still has to answer.
    """
    policy = permission_spec(level).approval_policy
    if not beyond_scope(level, tool):
        # Within the level's scope, so the level is not what deferred it: the tool gated
        # its own call, and no level may wave that through. The operator answers it —
        # unless they have chosen a level that delegates their answer to the review, which
        # is the whole of what Auto is. Delegating the answer is not deleting the gate.
        return Decision.REVIEW if policy is ApprovalPolicy.REVIEW else Decision.ASK
    return _BY_POLICY[policy]


def blocked_message(level: str, tool: str) -> str:
    """What the model is told when a call is refused, in place of the tool's result.

    Names the level and the fact that no prompt is coming, so the model re-plans instead
    of re-calling the tool and waiting: a refusal the model reads as a transient failure
    is a refusal it will spend the rest of the turn retrying.
    """
    return (
        f"This conversation is at the {permission_spec(level).level} permission level, so "
        f"{tool} was not run and the operator was not asked. Nothing here can change "
        "anything until they raise the level; say what you would do instead."
    )


# --- Auto's review ------------------------------------------------------------------
#: Which stage settled a review — the structural judge, or the model.
type ReviewStage = Literal["judge", "reviewer"]


@dataclass(frozen=True)
class ReviewOutcome:
    """What the two stages made of one call, and why.

    ``reason`` is not decoration. Auto's whole proposition is that the operator's answers
    are given for them, and the only thing that makes that acceptable is being able to
    read afterwards *what was decided and on what grounds* — so the reason travels onto
    the work log's review row beside the call it judged.
    """

    decision: Decision
    stage: ReviewStage
    reason: str
    #: The model stage's three axes, when it ran. None when the deterministic stage
    #: settled it, or when the model stage could not be reached at all.
    verdict: ReviewVerdict | None = None
    #: Which deterministic ground cleared it, when one did — None on everything the model
    #: stage settled. It rides onto the review row beside the reason because "cleared, and
    #: it ran fenced to the worktree" and "cleared, because the tool only observes" are
    #: different assurances, and an operator auditing the level has to tell them apart.
    tier: Tier | None = None
    #: Whether the operator's standing grant is what turned this into an ALLOW — the
    #: reviewer found nothing either way and the grant supplied the yes. It travels because
    #: a grant is **revocable** while the run that used it sits parked: the engine marks
    #: such an approval as the grant's (``agent/gating.py``) so the resume path re-checks it
    #: against the grants as they stand then (``routes/runs.py``). An allow the review
    #: reached on its own grounds has nothing to re-check and must not be re-checked.
    by_grant: bool = False


@dataclass
class ReviewBudget:
    """How many model reviews one turn may still spend.

    A turn is not one deferred call: a model that keeps reaching past the level's ceiling
    is reviewed on every hop, and each review is a round trip on the utility model with a
    timeout measured in seconds. Without a ceiling, a turn that loops through sensitive
    calls pays for a review per call — latency the operator watches, on a turn that is
    already going wrong.

    So the cap is per *turn* and shared by every batch in it, and what it counts is model
    calls: a structurally-cleared command spends nothing, however many of them there are.
    Beyond it the calls **park**, which is the same degrade every other failure of the
    review takes — the operator is asked the question the review was answering for them.
    Mutable and passed by reference for the same reason the turn's usage budget is.
    """

    limit: int
    spent: int = 0

    def take(self) -> bool:
        """Claim one model review, or report that this turn has none left."""
        if self.spent >= self.limit:
            return False
        self.spent += 1
        return True


async def review(
    capability: Capability,
    *,
    reviewer: Reviewer | None,
    transcript: Sequence[TranscriptEntry] = (),
    granted: bool = False,
    fenced: bool = False,
    budget: ReviewBudget | None = None,
) -> ReviewOutcome:
    """Rule on one call at the Auto level: the deterministic stage, then the model.

    ``fenced`` is the fact about the *host* the deterministic stage needs and cannot look
    up for itself (``judge.py`` is pure). It defaults to the strict reading — no fence —
    because a caller that could not say is a caller with nothing to hold a command to, and
    the cost of being wrong that way is a model call rather than an act nobody cleared.

    ``granted`` says the operator has a standing conversation grant on this tool
    (``services/approval_grants.py``). At every other level that grant *is* the answer and
    settles the call; here it is an **input to the review** instead. A grant is the
    operator saying yes to a tool, and at Auto the question is what one particular call to
    it would do — so the grant supplies the authorization and the rest of the review still
    runs, which is what keeps one "allow for this conversation" on a shell tool from
    switching the review off for every command in the thread. It supplies that
    authorization only where the reviewer had **nothing** to say: a reviewer that read the
    operator as having refused this act in this very turn is reading their most recent
    word, and a grant left earlier in the thread does not get to outrank it. And it is an
    input to a review that *ran*: where there is no reviewer to run at all there is nothing
    for it to authorize, so the call parks like every other unreviewable one. A grant that
    settled the call outright in that case would switch the level off on any installation
    with no utility model bound — one "allow for this conversation" on ``shell_run_command``
    and no command in the thread is ever looked at again.

    The combination, stated once here and written down nowhere the reviewer can read it
    (``reviewer.py``):

    - the deterministic stage's approval **runs**, with no model call at all;
    - ``too_destructive`` **parks**, whatever the operator is judged to have asked for —
      an unrecoverable act is not something a conversation can authorize into being
      recoverable, and it is the one act they most need to be shown rather than told
      about afterwards;
    - ``low`` risk **runs** unless the operator said no;
    - ``high`` risk runs **only** on an explicit yes;
    - everything else **parks**, and so does every way this can fail.

    Note what is deliberately absent: ``correctness`` moves nothing. It is an observation
    for the operator to read on the review row, not a fourth term — a reviewer that could
    veto on "this looks like the wrong path" would be second-guessing the model's work
    rather than ruling on its permission, and those are different jobs.
    """
    verdict_of_judge = judge(capability, fenced=fenced)
    if verdict_of_judge.approved:
        return ReviewOutcome(
            Decision.ALLOW, "judge", verdict_of_judge.reason, tier=verdict_of_judge.tier
        )
    if reviewer is None:
        # No utility model bound, or none reachable from here. The conservative branch is
        # the default at exactly this point, because the alternative is an action nobody
        # — no operator, no judge, no reviewer — ever agreed to. A standing grant does not
        # rescue it: the grant is an input to a review, and the review this call needed is
        # the one that could not run. The operator is asked instead, which is the same
        # degrade a timeout and an unparseable answer take.
        return ReviewOutcome(
            Decision.ASK, "judge", f"{verdict_of_judge.reason}; no reviewer is available"
        )
    if budget is not None and not budget.take():
        # Claimed before the call rather than counted after it, so a turn cannot exceed the
        # cap by having several reviews in flight at once (``agent/gating.py`` runs a
        # batch's reviews together).
        return ReviewOutcome(
            Decision.ASK,
            "judge",
            f"{verdict_of_judge.reason}; this turn has already spent its {budget.limit} "
            "reviews",
        )
    verdict = await reviewer(ReviewRequest(capability=capability, transcript=transcript))
    if verdict is None:
        return ReviewOutcome(
            Decision.ASK, "reviewer", f"{verdict_of_judge.reason}; the review did not complete"
        )
    # Derived once and handed to both halves: the arithmetic and the row's account of it
    # have to be reading the same authorization, and re-deriving it in each was two places
    # for the grant's rule to be stated in.
    authorization = _authorization(verdict, granted=granted)
    decision = _verdict_decision(verdict, authorization=authorization)
    return ReviewOutcome(
        decision,
        "reviewer",
        _verdict_reason(verdict, filled_by_grant=authorization != verdict.authorization),
        verdict,
        # Marked as the grant's only where the grant is what *changed* the answer — the
        # same verdict read without it parks. A low-risk act the review would have cleared
        # anyway does not become revocable for having a grant sitting beside it, and
        # marking it so would have the resume path deny a call the review approved.
        by_grant=decision is Decision.ALLOW
        and _verdict_decision(verdict, authorization=verdict.authorization) is not Decision.ALLOW,
    )


def _verdict_decision(verdict: ReviewVerdict, *, authorization: Authorization) -> Decision:
    """The arithmetic, one branch per risk word.

    Written as a match on the *named* values rather than as a chain ending in an else,
    because the else was `high`'s rule wearing "everything else"'s name: a fourth risk
    word — a middle one, added because two levels of severity were not enough — would
    have inherited the one branch that can return ALLOW on nothing more than an
    authorization. Unnamed risk parks, which is what the docstring above always said.

    A standing grant enters through :func:`_authorization` and nowhere else: the verdict
    object itself is left exactly as the model returned it, because it travels onto the
    review row and onto the run's own event, and what the model concluded from the thread
    is a different fact from what the operator said when they left the grant.
    """
    match verdict.risk:
        case "too_destructive":
            return Decision.ASK
        case "low":
            return Decision.ASK if authorization == "explicitly_no" else Decision.ALLOW
        case "high":
            return Decision.ALLOW if authorization == "explicitly_yes" else Decision.ASK
        case _:
            return Decision.ASK


def _authorization(verdict: ReviewVerdict, *, granted: bool) -> Authorization:
    """The authorization the arithmetic runs on: the reviewer's, with a standing grant
    filling in for it where the reviewer found nothing either way.

    **A grant fills a gap; it does not overrule a refusal.** ``explicitly_no`` is the
    reviewer's reading of what the operator said in *this* turn, and a grant recorded
    earlier in the thread is older than that by construction — treating it as the answer
    produced a row that reported the operator had said no and allowed the call in the same
    sentence. ``neutral`` is the case the grant was recorded for: the thread contains no
    word about this act, and the operator has already said yes to the tool.
    """
    if granted and verdict.authorization == "neutral":
        return "explicitly_yes"
    return verdict.authorization


def _verdict_reason(verdict: ReviewVerdict, *, filled_by_grant: bool) -> str:
    """The row's account of the ruling — the reviewer's two axes as it read them, and the
    grant named separately where one supplied the authorization. Stated apart rather than
    folded together because "the model found you had asked for this" and "you had already
    said yes to this tool" are different grounds, and only one of them is revocable. Named
    only where it actually did the work, so a row can never both report a refusal and
    credit a grant for overriding it (:func:`_authorization`)."""
    reason = f"{verdict.risk} risk, authorization {verdict.authorization}"
    if filled_by_grant:
        reason += "; your standing grant for this tool is the authorization"
    return f"{reason}; {verdict.correctness}" if verdict.correctness else reason
