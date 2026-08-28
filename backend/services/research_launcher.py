"""The seam that lets the *agent* start a deep-research run.

Deep research is an orchestrator (`research/`), which sits **above** `tools/` in the
dependency order — so a tool cannot import it. What a tool can do is resolve a
capability by type out of the run's bag, and this is the type it resolves: an abstract
launcher declared down here in `services/`, implemented up in `research/launcher.py`,
and registered with ``as_type=ResearchLauncher`` so the concrete orchestrator never has
to be named below its own layer.

The interface is deliberately narrow. Everything the REST surface offers — the
clarify exchange, plan refinement, the library — stays the operator's; an agent starting
research on the operator's behalf gets exactly two verbs, start and read.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ResearchUnavailableError(Exception):
    """Research cannot start right now, with an operator-legible reason.

    Distinct from a bug: a missing web capability or a misconfigured model registry are
    states the system can be in, and the tool turns this into a result the model can act
    on rather than a failed turn.
    """


@dataclass(frozen=True)
class LaunchedResearch:
    """What starting produced. The report is *not* here: a run takes minutes, and the
    tool that starts it returns immediately (see `ResearchLauncher.launch`)."""

    research_id: str
    run_id: str
    question: str


@dataclass(frozen=True)
class ResearchSnapshot:
    """A research entry as the agent reads it back."""

    research_id: str
    question: str
    status: str
    report: str | None = None
    sources: int = 0
    findings: int = 0


class ResearchLauncher(ABC):
    """Start a research run, and read one back."""

    @abstractmethod
    async def launch(self, owner_id: str, question: str, context: str = "") -> LaunchedResearch:
        """Plan and start a run for ``question``, returning as soon as it is submitted.

        **It does not wait.** A research run is its own Run on the same substrate and
        takes minutes; blocking a chat turn on it would burn the turn's step budget
        watching a progress bar. The operator sees it on the Research surface and gets a
        notification when it settles.

        ``context`` stands in for the interactive clarify exchange — what the operator
        already said in this conversation that narrows the question.
        """

    @abstractmethod
    async def snapshot(self, owner_id: str, research_id: str) -> ResearchSnapshot:
        """The entry's current state, with the report once it is terminal."""
