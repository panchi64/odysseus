"""Pillar I — the Run: one identified, background-executing unit of work.

Chat turns, agent tasks, and research jobs are all Runs; they differ only in
the orchestrator that drives them. A Run owns its id/owner/status, its event
stream (buffer + broker), and — once running — the asyncio task executing it.
Status follows ``queued → running → {done | blocked | error | cancelled}``,
with a parked ``awaiting_input`` when a sensitive action needs approval (D20).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from .events import Event, now_utc
from .stream import RunStream


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_input = "awaiting_input"
    done = "done"
    blocked = "blocked"
    error = "error"
    cancelled = "cancelled"


TERMINAL_STATUSES = {
    RunStatus.done,
    RunStatus.blocked,
    RunStatus.error,
    RunStatus.cancelled,
}


@dataclass
class Run:
    id: str
    kind: str
    owner_id: str
    stream: RunStream
    status: RunStatus = RunStatus.queued
    detail: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=now_utc)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_activity_mono: float = 0.0
    task: asyncio.Task[None] | None = None
    cancel_requested: bool = False

    def touch(self) -> None:
        """Mark activity now — feeds the inactivity watchdog (XC-PERF-2)."""
        self.last_activity_mono = asyncio.get_running_loop().time()

    def emit(self, body: BaseModel) -> Event:
        self.touch()
        return self.stream.emit(body)

    def block(self, detail: str | None = None) -> None:
        """Orchestrator declares it cannot proceed (AE-1.2 blocked)."""
        self.status = RunStatus.blocked
        self.detail = detail

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    async def wait(self) -> None:
        """Await the executing task (returns when the Run reaches terminal)."""
        if self.task is not None:
            await asyncio.shield(self.task)


# An orchestrator drives one Run: it emits events and may call ``run.block()``
# or raise. Normal return ⇒ done; raise ⇒ error; cancellation ⇒ cancelled.
Orchestrator = Callable[[Run], Awaitable[None]]
