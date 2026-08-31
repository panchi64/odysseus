"""The seam that lets the *agent* open a research thread of its own.

Research used to be a pipeline: a deterministic rounds loop with its own store, its own
REST surface and its own report. It is now a **conversation in research mode** — the same
chat backbone every other thread runs on, differing only in its prompt, its tool catalog
and its round-trip budget. What survives that change is this seam, because the structural
constraint that created it did not move: composing a chat turn happens *above* ``tools/``
in the dependency order, so a tool cannot import it. What a tool can do is resolve a
capability by type out of the run's bag, and this is the type it resolves — declared down
here in ``services/``, implemented at the wiring layer, and registered under this abstract
type so the concrete implementation is never named below its own layer.

The interface stays deliberately narrow: two verbs, start and read. A research thread the
agent opened is an ordinary conversation afterwards — the operator can open it, send into
it, branch it, and rename it like any other, which is most of the point of the change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class ResearchUnavailableError(Exception):
    """A research thread cannot be opened right now, with an operator-legible reason.

    Distinct from a bug: a misconfigured model registry or a suspended web capability are
    states the system can be in, and the tool turns this into a result the model can act
    on — fall back to a plain search, or tell the operator what to switch on — rather than
    a failed turn.
    """


@dataclass(frozen=True)
class ParentThread:
    """The thread asking for the research, as far as starting one needs to know it.

    ``seed_from`` is the one non-obvious member and it is why this is a record rather than
    three arguments: when a **code** thread starts research, the analysis must happen on a
    *copy* of its worktree and never on the operator's own working tree — so the caller,
    which already has the run's resolved workspace in hand, names the directory to copy
    and the implementation does not have to re-derive a workspace it cannot see.
    """

    conversation_id: str | None = None
    #: The project the parent is filed under, inherited so the linked thread lands in the
    #: same scope rather than appearing unfiled next to work it belongs with.
    project_id: str | None = None
    #: A directory whose contents seed the new thread's sandbox, or None to start empty.
    seed_from: Path | None = None


@dataclass(frozen=True)
class StartedResearch:
    """What opening a thread produced. The answer is **not** here: research takes minutes
    and the tool that starts it returns immediately (see :meth:`ResearchThreads.start`)."""

    conversation_id: str
    run_id: str
    question: str


@dataclass(frozen=True)
class ResearchThreadView:
    """A research thread as the agent reads it back.

    ``status`` is the thread's, not a stored entity's: ``running`` while a turn is in
    flight, otherwise how the last one settled. ``answer`` is the thread's most recent
    assistant message — which is a *current best* rather than a final report, and is
    readable while the thread is still working.
    """

    conversation_id: str
    question: str
    status: str
    answer: str | None = None


class ResearchThreads(ABC):
    """Open a research thread, and read one back."""

    @abstractmethod
    async def start(
        self,
        owner_id: str,
        question: str,
        *,
        context: str = "",
        parent: ParentThread | None = None,
    ) -> StartedResearch:
        """Open a research thread for ``question`` and return as soon as its first turn
        is submitted.

        **It does not wait.** The thread runs as its own Run on the same substrate and
        takes minutes; blocking the calling turn on it would burn that turn's whole step
        budget watching a progress bar. The operator sees the new thread in their session
        list and is notified when it settles, exactly as they are for any other thread.

        ``context`` stands in for the questions the operator would otherwise be asked
        before the reading starts — what the calling conversation has already established
        that narrows the question.
        """

    @abstractmethod
    async def read(self, owner_id: str, conversation_id: str) -> ResearchThreadView:
        """The thread's current state, with its latest answer."""
