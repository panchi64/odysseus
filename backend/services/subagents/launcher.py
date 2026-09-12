"""The seam that lets the *agent* launch a sub-agent.

Same structural constraint that created the research seam, and the same answer: composing
a chat turn happens *above* ``tools/`` in the dependency order, so a tool cannot import it.
What a tool can do is resolve a capability by type out of the run's bag, and this is the
type it resolves — declared down here in ``services/``, implemented at the wiring layer
(``harness/manifests/_subagents.py``), and registered under this abstract type so the
concrete implementation is never named below its own layer.

**A sub-agent is an ordinary conversation.** It is composed by the same ``compose_turn``
an operator's own message goes through, runs the same engine, persists the same message
rows, and is measured by the same context gauge. What makes it a sub-agent rather than a
thread is three things: it is hidden from the session list, nobody can type into it, and
when it finishes its report is delivered back to the thread that launched it. None of that
is a second engine, and the moment it starts to become one, something here is wrong.

The interface is three verbs. ``launch`` returns the instant the child's first turn is
submitted — it never waits, because waiting is the whole thing this replaced. ``read`` is
how a parent checks on one it is still expecting. ``live`` is how the cap is counted and
how the panel backfills.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from services.subagents.spec import SubagentSpec


class SubagentUnavailableError(Exception):
    """A sub-agent cannot be launched right now, with an agent-legible reason.

    Distinct from a bug: a misconfigured model registry, a workspace that cannot be forked,
    a cap the operator set — these are states the system can be in, and the launch tool
    turns this into a result the model can act on (do the work itself, wait for a running
    sub-agent, tell the operator what to switch on) rather than a failed turn.
    """


@dataclass(frozen=True)
class SubagentParent:
    """The thread doing the launching, as far as launching needs to know it.

    Everything here exists to *narrow* the child. The project it inherits so the child
    lands in the same scope; the permission it inherits as a ceiling it can never exceed;
    the workspace it names so a fork is cut from the files the parent's own transcript
    describes, rather than from a workspace re-derived down here that might not be the
    same one.
    """

    conversation_id: str | None = None
    #: The project the parent is filed under, inherited so a child works on the same code.
    project_id: str | None = None
    #: The parent's own mode, which a spec naming no mode of its own inherits.
    mode: str | None = None
    #: How much rope the *parent* has. A sub-agent runs at the stricter of this and what
    #: its spec asks for, so one approved launch cannot buy a level the operator never
    #: chose. None means the caller had no level to hand over and the mode's default stands.
    permission: str | None = None
    #: The parent's resolved workspace root — what a ``seed`` copies and a ``fork`` cuts
    #: from. None when the parent has no workspace, which a ``fork`` spec cannot survive.
    workspace_from: Path | None = None
    #: The parent's workspace key, which is what the sandbox manager forks by name.
    workspace_key: str | None = None
    #: The run doing the launching. Only its id is kept, to tie a card back to the turn
    #: that asked for it.
    run_id: str | None = None


@dataclass(frozen=True)
class LaunchedSubagent:
    """What launching produced. The **report is not here**: a sub-agent takes minutes, and
    the launch returns as soon as its first turn is submitted."""

    subagent_id: str
    #: The child's own conversation — where its transcript lives, and what the panel opens.
    conversation_id: str
    run_id: str
    name: str
    task: str


@dataclass(frozen=True)
class SubagentView:
    """A sub-agent as the parent reads it back, and as a card renders it.

    ``status`` is derived from the child's Run and its stored record rather than stored
    twice — "is it still working" is a fact about the run registry, and a second copy of it
    would be the one that goes stale.
    """

    subagent_id: str
    conversation_id: str
    run_id: str
    name: str
    task: str
    #: ``running`` | ``blocked`` | ``done`` | ``failed`` | ``cancelled``.
    status: str
    #: Its report, once it has one; its most recent answer while it is still working.
    summary: str | None = None
    error: str | None = None
    #: How full the child's own context window is — the card's ring. Null while unknown.
    context_used: int | None = None
    context_window: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class SubagentLauncher(ABC):
    """Launch a sub-agent, read one back, and list the ones that exist."""

    @abstractmethod
    async def launch(
        self,
        owner_id: str,
        spec: SubagentSpec,
        task: str,
        *,
        parent: SubagentParent | None = None,
    ) -> LaunchedSubagent:
        """Open a sub-agent on ``task`` and return as soon as its first turn is submitted.

        **It does not wait.** The sub-agent runs as its own Run on the same substrate and
        takes minutes; blocking the launching turn on it would burn that turn's whole step
        budget watching a progress bar, which is exactly what the synchronous delegation
        this replaced did.

        ``task`` has to stand alone. The child never sees the launching conversation — it
        starts from an empty history with its spec's brief and this one message — so a task
        that says "fix the bug we discussed" describes nothing the sub-agent can act on.

        Raises :class:`SubagentUnavailableError` for every state the system can legitimately
        be in that prevents a launch.
        """

    @abstractmethod
    async def read(self, owner_id: str, subagent_id: str) -> SubagentView:
        """One sub-agent's current state, with its report if it has finished."""

    @abstractmethod
    async def live(
        self, owner_id: str, *, conversation_id: str | None = None
    ) -> list[SubagentView]:
        """Every sub-agent still working — all of the owner's, or one parent's.

        Counted against the operator's cap, and what a parent lists when deciding whether
        it is waiting on anything. A sub-agent parked on an approval is *live*: it has not
        reported, and the thing it is waiting for is the operator, not a slot.
        """
