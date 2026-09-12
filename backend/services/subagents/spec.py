"""What a sub-agent *is*, as data.

A sub-agent is not a class and not a run loop. It is a handful of values that decide how
one ordinary turn is composed — which mode it runs in, how far it may reach, what standing
brief it is given, whether it gets a copy of the workspace. Everything else about it is the
engine every other turn uses.

Keeping it data is what makes the roster extensible without new code: a built-in sub-agent
and one a project declares in a file are the same record, built two ways, and the launcher
cannot tell them apart. A sub-agent that needed *behaviour* of its own would be a sign the
engine was missing something, not a reason for a subclass here.

**A spec is a request, never a grant.** Every field below is read as a ceiling the launcher
then lowers against the thread that asked — most importantly ``permission_ceiling``, which
is folded with the parent's own level so a sub-agent can never reach further than the
conversation that launched it. A project file declaring itself all-powerful gets exactly
what the operator already allowed and no more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: How a sub-agent is given files to work on.
#:
#: ``none`` — no workspace of its own; it reads what it is told and reports. The cheapest,
#: and right for anything that only needs the model.
#: ``seed`` — a *copy* of the parent's files, taken once at launch and thrown away after.
#: Right for reading and analysis: nothing it does can reach the operator's own tree, and
#: nothing the parent does afterwards moves underneath it.
#: ``fork`` — its own sandbox session or its own checkout on its own branch, merged back
#: when it finishes, with conflicts reported rather than resolved in its favour.
#: Right, and only right, for a sub-agent that *changes* things.
WorkspacePolicy = Literal["none", "seed", "fork"]


@dataclass(frozen=True)
class SubagentSpec:
    """One sub-agent the model may launch."""

    #: How the model names it in the launch call, and how the operator sees it on a card.
    name: str
    #: One or two lines saying what this sub-agent is *for*, joined with its peers into the
    #: launch tool's own description. This is the only place the model reads the roster —
    #: not a standing instruction at the prompt head, which would repeat itself inside the
    #: cached prefix on every request and say it furthest from where the choice is made.
    description: str
    #: The sub-agent's standing brief, delivered as an instruction rather than as its
    #: opening message: instructions are rebuilt each turn and never read back out of
    #: history, so nothing the sub-agent later reads can rewrite what it was told to do.
    brief: str
    #: The mode it runs in. None inherits the parent's, which is usually right — a
    #: sub-agent of a code thread is working on that code. A spec names one only when it
    #: genuinely belongs elsewhere (research, which needs the open web).
    mode: str | None = None
    #: The furthest this sub-agent may reach, before the parent's own level is folded in.
    #: None takes the mode's default. Never raises what the operator allowed.
    permission_ceiling: str | None = None
    workspace: WorkspacePolicy = "none"
    #: Tools withheld from this sub-agent on top of everything mode, level and the
    #: operator's own switches already withhold. For narrowing a sub-agent to its job —
    #: a reviewer that reads and reports has no business editing.
    withheld: frozenset[str] = field(default_factory=frozenset)
    #: Tools without which this sub-agent is a pretence rather than a degraded version of
    #: itself — a researcher with no web reach answers from memory and reads, to the
    #: operator, exactly as though it had looked. The launcher refuses instead.
    required: frozenset[str] = field(default_factory=frozenset)
    #: Model round-trips it may spend, and how long it may take in total. None leaves both
    #: to the engine's own defaults (the operator's ceiling, the mode's floor).
    request_limit: int | None = None
    wall_clock_timeout_s: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a sub-agent needs a name")
        if not self.brief.strip():
            raise ValueError(f"sub-agent {self.name!r} has no brief")
