"""How much rope the model gets — two knobs, and four names over them.

A permission level is the second axis of a thread. The mode says what kind of work this
is; the level says how far the model may go without stopping to ask. They are orthogonal
on purpose: every mode carries all four levels, and a level means the same thing in each.

**Why two knobs rather than four branches.** The obvious shape is four named levels and a
decision function that switches on the name — which works until a fifth combination is
wanted, at which point every switch has to grow a case and the ones that are missed fail
silently. So a level is stored and shown as a name, and *resolved* to a pair:

- a **ceiling** on :class:`~services.tool_sensitivity.Sensitivity` — how far the model may
  reach without permission at all. ``read`` permits observation only; ``workspace_write``
  also permits changing what this installation owns; the room for a third (a level that
  may touch the host) is the point;
- an **approval policy** — what happens to an act that reaches past that ceiling: withhold
  the tool outright, park for the operator, or send it to review.

The four levels are presets over that pair. A fifth is a row here, and nothing else moves.

The ceiling is a sensitivity class rather than a name of its own because that is what
makes the pair decidable: the classes already say what a tool *does*, so "may this run
without asking?" is a comparison rather than a list of tool names to keep in step.

**What a level cannot do is take a gate away.** Levels widen; they never narrow. A tool
that gates itself — the global-recall pause, a skill edit — is still answered at every
level, because the reason it gates is not the one this axis reasons about (a recall pulls
untrusted content into the model's context; it changes nothing the ceiling describes).
What clears a tool's own gate is the operator: at the prompt, through a standing
conversation grant, or — at the one level whose entire meaning is that they asked for
their answers to be given for them — through the review. That asymmetry is what keeps
adding a level from quietly deleting a protection nobody re-examined.

There is exactly one exemption in the other direction, and it is here rather than at a
call site because both halves of the enforcement need it: the model's own task list is
writable at every level (:data:`PLANNING_TOOLS`), since a read-only turn whose only
possible ending is a written plan cannot be made to ask permission to write one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from prompts.levels import MANUAL_LEVEL, PLAN_LEVEL
from services.tool_sensitivity import (
    EXTERNAL_PREFIX,
    Sensitivity,
    classified,
    sensitivity_of,
    tools_above,
)

#: The stored vocabulary. A plain string on the conversation row, like the mode: a
#: restored backup or a row written by another build must still load.
type PermissionLevel = Literal["plan", "manual", "edit", "auto"]

#: The four, as a set to validate against. Written once here so no caller re-lists them.
PERMISSION_LEVELS: frozenset[str] = frozenset({"plan", "manual", "edit", "auto"})

#: What a mode that names no level of its own starts a thread at, and what a caller with
#: no level to pass gets. ``edit`` is the level a thread is most usefully at: the model
#: works in the workspace and stops at the boundary of it.
DEFAULT_PERMISSION: PermissionLevel = "edit"

#: The level that does the least — where an unreadable stored value lands.
STRICTEST_PERMISSION: PermissionLevel = "plan"


class ApprovalPolicy(StrEnum):
    """What becomes of an act that reaches past the level's ceiling."""

    #: Never offered. The tool is dropped from the catalog before the model sees it, so
    #: there is nothing to ask about — the only form of read-only that survives a model
    #: that decides otherwise (``services/tool_policy.py``).
    WITHHOLD = "withhold"
    #: Park and wait for the operator's decision.
    ASK = "ask"
    #: Judged, then reviewed; parks on doubt.
    REVIEW = "review"


@dataclass(frozen=True)
class PermissionSpec:
    """One named level, as the pair it resolves to."""

    #: The stored value, and the identity — ``PERMISSIONS[spec.level] is spec``.
    level: PermissionLevel
    #: The highest sensitivity class that passes unasked. ``read`` reaches nothing;
    #: ``workspace_write`` also reaches the run's own files, its plan and this
    #: installation's records — state we own, can show the operator, and can undo.
    ceiling: Sensitivity
    #: What happens when a tool reaches further.
    approval_policy: ApprovalPolicy
    #: The prompt fragment this level adds, or "" when it adds nothing — mirroring
    #: ``ModeSpec.instructions``, and for the same reason: a level's prose belongs with the
    #: rest of that level's declaration rather than in a branch at the engine. Two of the
    #: four say nothing (:mod:`prompts.levels` explains which and why), so the registration
    #: is unconditional and most threads pay no tokens for it.
    instructions: str = ""


PERMISSIONS: Mapping[PermissionLevel, PermissionSpec] = {
    # Read-only, and enforced by absence rather than by asking: a Plan turn is offered no
    # mutating tool at all, so it ends the only way it can — in a plan the operator reads
    # and accepts. Asking instead would make the read-only promise depend on the model
    # agreeing to it, which is the one moment it stops holding.
    "plan": PermissionSpec(
        level="plan",
        ceiling=Sensitivity.READ,
        approval_policy=ApprovalPolicy.WITHHOLD,
        instructions=PLAN_LEVEL,
    ),
    # Read-only until told otherwise, one act at a time. The tools stay in the catalog —
    # the model must be able to propose the thing it needs permission for.
    "manual": PermissionSpec(
        level="manual",
        ceiling=Sensitivity.READ,
        approval_policy=ApprovalPolicy.ASK,
        instructions=MANUAL_LEVEL,
    ),
    # The working default: change the workspace freely, stop at its edge. Running a
    # program, reaching a mail or calendar server, driving the operator's own browser
    # session and reading a credential all sit past that edge.
    "edit": PermissionSpec(
        level="edit", ceiling=Sensitivity.WORKSPACE_WRITE, approval_policy=ApprovalPolicy.ASK
    ),
    # The same reach as Edit, with the operator's decision replaced by a review rather
    # than removed: a deterministic judge, then a model reviewer, parking on any doubt
    # and on every way the review can fail (`decide.py`).
    "auto": PermissionSpec(
        level="auto", ceiling=Sensitivity.WORKSPACE_WRITE, approval_policy=ApprovalPolicy.REVIEW
    ),
}


#: How permissive each policy is, once the ceiling has been compared. Withholding the tool
#: is the least a level can do with an act it does not permit; parking asks the operator;
#: reviewing answers for them. Only meaningful *within* one ceiling — a level that reaches
#: further is more permissive whatever it does at the boundary.
_POLICY_PERMISSIVENESS: Mapping[ApprovalPolicy, int] = {
    ApprovalPolicy.WITHHOLD: 0,
    ApprovalPolicy.ASK: 1,
    ApprovalPolicy.REVIEW: 2,
}

#: The levels that can change something without being asked first — derived from the pair
#: rather than named, so a fifth preset is a row in :data:`PERMISSIONS` and nothing else
#: moves. A ``read`` ceiling is the definition of a level that cannot act: it reaches
#: nothing but observation, so raising a thread *to* it would be a no-op with extra steps.
ACTING_PERMISSIONS: frozenset[PermissionLevel] = frozenset(
    level for level, spec in PERMISSIONS.items() if spec.ceiling is not Sensitivity.READ
)


def permission_level(level: str) -> PermissionLevel:
    """A stored permission value, falling back to the strictest level rather than the
    default one.

    The two axes of a thread degrade in the same direction and for the same reason — a
    value that reaches this comes off a database row or a parked run's payload, both of
    which outlive a rename — but the conservative answer differs. An unknown *mode* is
    Normal because Normal reaches the least; an unknown *level* is Plan because Plan does
    the least. A corrupt value leaves the model able to read and to plan, and unable to
    act, which is a failure the operator can see and correct rather than one that quietly
    grants.
    """
    return level if level in PERMISSION_LEVELS else STRICTEST_PERMISSION


def permission_spec(level: str) -> PermissionSpec:
    """The spec for a stored level value. Never raises — see :func:`permission_level`."""
    return PERMISSIONS[permission_level(level)]


def _permissiveness(spec: PermissionSpec) -> tuple[int, int]:
    """How far a level goes, as a comparable pair: how far it reaches unasked, then what it
    does with an act that reaches further. Derived from the two knobs for the same reason
    everything else here is — a fifth preset orders itself instead of being slotted into a
    hand-written list somebody has to remember to edit."""
    return (spec.ceiling.escalation, _POLICY_PERMISSIVENESS[spec.approval_policy])


def stricter_permission(a: str, b: str) -> PermissionLevel:
    """Whichever of ``a`` and ``b`` permits the less.

    For the caller that opens a thread *from inside another one*: the spawned thread must
    never be able to do more than the thread that spawned it, whatever level its mode
    would start a fresh thread at. Taking the stricter of the two is what stops one
    approved spawn from buying a standing level the operator never chose. A tie resolves
    to ``a``, since neither permits more than the other."""
    return min(
        (permission_level(a), permission_level(b)),
        key=lambda level: _permissiveness(PERMISSIONS[level]),
    )


# The Planning toolset — permitted at every level, whatever its ceiling says. A read-only
# turn exists to end in a plan, so a level that made the model ask before recording what it
# had decided would leave it no way to finish; and a level that asks before *acting* has no
# business interrupting the model's own scratchpad. The whole surviving surface is listed
# rather than the writes alone, so the exemption reads as "the task list" and a reader does
# not have to work out which half of it needed naming. The names are literals for the
# reason every other tool-name set in `services/` is (`tools/` sits above it in the
# dependency order), and `tests/test_tool_sensitivity.py` pins them against the live
# catalog.
PLANNING_TOOLS = frozenset(
    {
        "plan_read_plan",
        "plan_update_task_statuses",
        "plan_write_plan",
    }
)


def beyond_scope(level: str, tool: str, *, declared: Sensitivity | None = None) -> bool:
    """Whether ``tool`` reaches past what ``level`` permits unasked.

    ``declared`` is the class the toolset stated about the tool itself
    (:func:`~services.tool_sensitivity.declared_sensitivity`). It wins over both the name
    registry and the fallback below, because it is knowledge where they are inference —
    and it is the only answer available for a toolset this installation composes at run
    time rather than ships in the catalog.

    The one question both halves of the enforcement ask, so they cannot disagree about
    where the line is: the toolset marks every tool past it as needing approval, and the
    decision point that sees the resulting call reads the same answer to know that the
    level — rather than the tool's own marking — is what deferred it.

    **A tool this installation cannot classify is elevated only by a level that permits
    nothing.** The unclassifiable names are the operator's own MCP and connector tools —
    every tool in the catalog proper carries a class, and ``tests/test_tool_sensitivity.py``
    fails in *both* directions if one stops doing so — and those already carry a per-tool
    decision of the operator's: the trust list (``services/external_tools.py``), which
    pauses an untrusted one from inside the call and lets a trusted one through.
    Manufacturing a second gate on top of a guess would replace that explicit answer with
    an inferred one, and would make "trusted" mean nothing at the two levels where the
    operator uses it. Where the level's promise is that the thread changes *nothing*, the
    guess is load-bearing and the promise wins — there is no other way to keep it against
    a tool nothing here can bound.

    **Everything else unclassified fails closed**, and the split between the two is the
    prefix the external surface already carries. Deferring to the trust list is an answer
    only where there *is* one; for any other unknown name — a tool added to the catalog
    without a class, a rename that outran the registry — there is nothing to defer to, and
    treating "we have never heard of this" as "it may act unasked" is the one reading that
    cannot be justified. So it takes :func:`~services.tool_sensitivity.sensitivity_of`'s
    own conservative fallback and reaches
    :func:`~services.permissions.decide.decide` like anything else past the ceiling.

    In a correct build that branch is unreachable — ``tests/test_tool_sensitivity.py``
    fails in both directions if a catalog tool loses its class — which is exactly why it
    is written the safe way: the cost of it never firing is nothing, and the cost of it
    firing open is a tool acting unasked at the two levels that let the model act at all.
    """
    if tool in PLANNING_TOOLS:
        return False
    spec = permission_spec(level)
    if declared is not None:
        return declared.above(spec.ceiling)
    if not classified(tool) and tool.startswith(EXTERNAL_PREFIX):
        return spec.ceiling is Sensitivity.READ
    return sensitivity_of(tool).above(spec.ceiling)


def tools_beyond_scope(level: str) -> frozenset[str]:
    """Every *classified* tool ``level`` does not permit — the set form of
    :func:`beyond_scope`, for the caller that narrows a catalog rather than ruling on one
    call. Unclassified names are absent by construction and do not need to be there: only
    a call can reveal one, and the decision point that sees it resolves it the same way.
    """
    return tools_above(permission_spec(level).ceiling) - PLANNING_TOOLS
