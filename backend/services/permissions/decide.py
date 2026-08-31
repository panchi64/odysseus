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
a thread the operator set to act in nothing.

**The second half of this module is that review** (:func:`review`), which is what
``REVIEW`` resolves to: the deterministic stage first (``judge.py``), the model second
(``reviewer.py``), and the arithmetic over their answers here — deliberately *here*,
where a reader can see the whole rule at once and where the reviewer cannot read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from services.permissions.capability import Capability
from services.permissions.judge import judge
from services.permissions.levels import ApprovalPolicy, beyond_scope, permission_spec
from services.permissions.reviewer import Reviewer, ReviewRequest, ReviewVerdict


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
    #: Refuse it and tell the model why. Either the level does not permit this act at all
    #: — under Plan the operator's answer is already on the record, in the level they
    #: chose — or the review found it unrecoverable. Two different refusals, two
    #: different messages (:func:`blocked_message`, :func:`review_refusal`).
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
#: Which stage settled a review — the deterministic allowlist, or the model.
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


async def review(
    capability: Capability,
    *,
    reviewer: Reviewer | None,
    transcript: str = "",
) -> ReviewOutcome:
    """Rule on one call at the Auto level: the deterministic stage, then the model.

    The combination, stated once here and written down nowhere the reviewer can read it
    (``reviewer.py``):

    - the deterministic stage's approval **runs**, with no model call at all;
    - ``too_destructive`` **blocks**, whatever the operator is judged to have asked for —
      an unrecoverable act is not something a conversation can authorize into being
      recoverable, and this is the one place authorization does not enter the arithmetic;
    - ``low`` risk **runs** unless the operator said no;
    - ``high`` risk runs **only** on an explicit yes;
    - everything else **parks**, and so does every way this can fail.

    Note what is deliberately absent: ``correctness`` moves nothing. It is an observation
    for the operator to read on the review row, not a fourth term — a reviewer that could
    veto on "this looks like the wrong path" would be second-guessing the model's work
    rather than ruling on its permission, and those are different jobs.
    """
    verdict_of_judge = judge(capability)
    if verdict_of_judge.approved:
        return ReviewOutcome(Decision.ALLOW, "judge", verdict_of_judge.reason)
    if reviewer is None:
        # No utility model bound, or none reachable from here. The conservative branch is
        # the default at exactly this point, because the alternative is an action nobody
        # — no operator, no judge, no reviewer — ever agreed to.
        return ReviewOutcome(
            Decision.ASK, "judge", f"{verdict_of_judge.reason}; no reviewer is available"
        )
    verdict = await reviewer(ReviewRequest(capability=capability, transcript=transcript))
    if verdict is None:
        return ReviewOutcome(
            Decision.ASK, "reviewer", f"{verdict_of_judge.reason}; the review did not complete"
        )
    return ReviewOutcome(_verdict_decision(verdict), "reviewer", _verdict_reason(verdict), verdict)


def _verdict_decision(verdict: ReviewVerdict) -> Decision:
    """The arithmetic, one branch per risk word.

    Written as a match on the *named* values rather than as a chain ending in an else,
    because the else was `high`'s rule wearing "everything else"'s name: a fourth risk
    word — a middle one, added because two levels of severity were not enough — would
    have inherited the one branch that can return ALLOW on nothing more than an
    authorization. Unnamed risk parks, which is what the docstring above always said.
    """
    match verdict.risk:
        case "too_destructive":
            return Decision.BLOCK
        case "low":
            return Decision.ASK if verdict.authorization == "explicitly_no" else Decision.ALLOW
        case "high":
            return Decision.ALLOW if verdict.authorization == "explicitly_yes" else Decision.ASK
        case _:
            return Decision.ASK


def _verdict_reason(verdict: ReviewVerdict) -> str:
    reason = f"{verdict.risk} risk, authorization {verdict.authorization}"
    return f"{reason}; {verdict.correctness}" if verdict.correctness else reason


def review_refusal(tool: str, reason: str) -> str:
    """What the model is told when the review refuses a call outright.

    Distinct from :func:`blocked_message` because the two refusals are different facts and
    a model that confused them would take the wrong next step: a level's refusal says
    *this kind of act is not available in this thread*, and this one says *this particular
    act cannot be undone*. The second leaves a smaller, safer version of the same act open.
    """
    return (
        f"{tool} was not run: the review found it {reason}, and an action that cannot be "
        "undone is never taken without the operator asking for it in so many words. "
        "Propose a reversible version, or say what you need them to confirm."
    )
