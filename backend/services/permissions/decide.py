"""What to do with a tool call the model wants to make — one function, four answers.

The engine reaches here at the single point where Pydantic AI hands back a *deferred*
call: a call the library declined to execute and returned for someone to rule on. Two
things put a call in that list, and telling them apart is the whole job of this module:

- **the level put it there.** The toolset marks every tool that reaches past the level's
  write scope as needing approval (``tools/toolsets.py``), so the model's request for one
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
one", which the engine resolves *before* consulting the level, because a decision the
operator already made outranks a policy. Expressing it in the same vocabulary is what
keeps the engine to one dispatch, and it is the verdict Auto's review stage returns for a
call it clears once that stage lands.
"""

from __future__ import annotations

from enum import StrEnum

from services.permissions.levels import ApprovalPolicy, beyond_scope, permission_spec


class Decision(StrEnum):
    """What happens to one deferred tool call."""

    #: Run it, with no operator round-trip. Never the answer to a *level's* question —
    #: only to the operator's own standing grant, and to a review that cleared it.
    ALLOW = "allow"
    #: Judge and review it (Auto). Parks while there is no review stage to run it
    #: through — a missing judge degrades towards asking, never towards allowing.
    REVIEW = "review"
    #: Park the run and put the call in front of the operator.
    ASK = "ask"
    #: Refuse it and tell the model why. The level does not permit this act at all, so
    #: there is nothing for the operator to decide — under Plan the operator's answer is
    #: already on the record, in the level they chose.
    BLOCK = "block"


#: The three answers a level gives to a call that reached past its write scope.
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
