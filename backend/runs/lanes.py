"""Which queue a run waits in.

One pool of eight slots shared by everything was a bound on the *host*, not a policy
about *whose work matters*: a scheduled task firing at nine and two research threads the
agent opened for itself could hold every slot, and the operator's next message sat at the
gate behind them — queued, silent, and indistinguishable from a slow model.

So the pool is split into lanes, one semaphore each, and a run picks its lane from its
own ``kind``. That is the whole mechanism: no call site threads a new argument, because
every submitter already says what kind of work it is submitting.

**The lanes are about who is waiting, not what the run does.** All three kinds run the
same chat orchestrator over the same tools; they differ in whether somebody is sitting in
front of the answer. ``interactive`` is the operator's own turn and gets the widest lane.
``background`` is unattended work — a scheduled task, whose whole point is that nobody is
watching it. ``linked`` is a thread the agent opened for itself (research started from
another conversation), which is foreground for the model and background for the operator,
and gets its own lane so a burst of them can neither starve the operator nor be starved
by the scheduler.

An unrecognised kind lands in ``background``. That is the conservative direction: a kind
nobody mapped is far more likely to be new autonomous work than a turn the operator is
waiting on, and the one thing this module exists to prevent is unattended work crowding
out attended work.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

type Lane = Literal["interactive", "background", "linked"]

#: Every lane, in the order a readout should list them: most attended first.
LANES: tuple[Lane, ...] = ("interactive", "background", "linked")

#: What an unmapped kind waits in — see the module docstring.
DEFAULT_LANE: Lane = "background"

#: Run kind → lane. The keys are the vocabulary the chat composition path
#: (``routes/chat.py``'s ``compose_turn``) submits under: ``chat`` is the operator's own
#: turn, ``task`` a scheduled task's fire, ``linked`` a thread the agent opened from
#: inside another one. They name the turn's *provenance*, which is exactly what decides
#: the lane — hence one mapping rather than a lane argument at each call site.
LANE_BY_KIND: Mapping[str, Lane] = {
    "chat": "interactive",
    "task": "background",
    "linked": "linked",
}

#: The kinds that are a chat turn — the ones composed by ``compose_turn``, and therefore
#: the ones whose orchestrator drains the queued-message inbox a mid-run send lands in.
#: Kept beside the lane map because both answer the same question about a kind, and two
#: lists of run kinds would drift the first time a fourth one is added.
CHAT_TURN_KINDS: frozenset[str] = frozenset(LANE_BY_KIND)


def lane_for(kind: str) -> Lane:
    """The lane a run of this kind waits in. Never raises — a stored or forwarded kind
    can outlive the code that coined it, and an unknown one has to queue somewhere."""
    return LANE_BY_KIND.get(kind, DEFAULT_LANE)


@dataclass(frozen=True)
class LaneLimits:
    """How many runs each lane admits at once.

    Interactive is the operator's lane and keeps the number the single pool used to
    carry; the autonomous lanes are deliberately narrower than it rather than equal to
    it, because their work has no one waiting on it and their whole failure mode is
    volume. The three are independent, so the host's real ceiling is their sum — which is
    the honest way to state it, since that is what it always was.
    """

    interactive: int = 8
    background: int = 2
    linked: int = 3

    def for_lane(self, lane: Lane) -> int:
        return getattr(self, lane)


class LaneGate:
    """The semaphores themselves, addressed by run kind.

    Holds one semaphore per lane rather than one per kind, so two kinds that share a
    lane share its slots. Constructed outside any event loop (the registry is built at
    app assembly, before the loop is running), which ``asyncio.Semaphore`` has allowed
    since it stopped binding a loop at construction.
    """

    def __init__(self, limits: LaneLimits | None = None) -> None:
        self._limits = limits or LaneLimits()
        self._semaphores: dict[Lane, asyncio.Semaphore] = {
            lane: asyncio.Semaphore(max(1, self._limits.for_lane(lane))) for lane in LANES
        }

    @property
    def limits(self) -> LaneLimits:
        return self._limits

    def slot(self, kind: str) -> asyncio.Semaphore:
        """The semaphore a run of this kind must hold to execute. Used as an
        ``async with``, so a burst waits at its own lane's gate and nowhere else."""
        return self._semaphores[lane_for(kind)]
