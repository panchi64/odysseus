"""Pillar I — the per-run event stream: in-memory buffer + broker.

One :class:`RunStream` per Run owns the sequence-numbered event buffer and the
set of live subscribers. It does two jobs at once:

- **buffer** — every event is appended in ``seq`` order and kept for the run's
  lifetime, so a client that disconnects and reconnects can replay what it
  missed on reconnect.
- **broker** — each emit fans out to every live subscriber's queue.

The buffer is in-memory and dies with the process, which is exactly what
``AE-7`` licenses ("continuity need not survive a server restart").

Correctness note: ``emit`` is synchronous and ``subscribe`` does its
register-then-snapshot with no ``await`` in between. Under single-threaded
asyncio that window is atomic, so every event lands in exactly one of {backlog,
live queue} — no gap, no duplicate, for any subscriber at any time.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pydantic import BaseModel

from .events import Event, now_utc


class RunStream:
    def __init__(self) -> None:
        self._buffer: list[Event] = []
        self._seq = 0
        self._subscribers: set[asyncio.Queue[Event | None]] = set()
        self._closed = False

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def closed(self) -> bool:
        return self._closed

    def emit(self, body: BaseModel) -> Event:
        """Stamp, buffer, and fan out an event. Synchronous and atomic."""
        if self._closed:
            raise RuntimeError("emit on a closed RunStream")
        self._seq += 1
        event = Event(seq=self._seq, ts=now_utc(), body=body)
        self._buffer.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)
        return event

    def replay(self, after_seq: int = 0) -> list[Event]:
        """Buffered events with ``seq > after_seq`` (all of them if 0)."""
        if after_seq <= 0:
            return list(self._buffer)
        return [e for e in self._buffer if e.seq > after_seq]

    async def subscribe(self, after_seq: int = 0) -> AsyncIterator[Event]:
        """Replay missed events (``seq > after_seq``) then stream live ones.

        Ends when the stream is closed (the run reached a terminal state).
        Subscribing to an already-closed stream replays the backlog and stops —
        so a client reconnecting after the run ended still gets the full record.
        """
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        # --- atomic: register before snapshot, no await between ---
        self._subscribers.add(queue)
        backlog = self.replay(after_seq)
        already_closed = self._closed
        # ----------------------------------------------------------
        try:
            for event in backlog:
                yield event
            if already_closed:
                return
            while True:
                event = await queue.get()
                if event is None:  # close sentinel
                    return
                yield event
        finally:
            self._subscribers.discard(queue)

    def close(self) -> None:
        """Mark terminal and signal every live subscriber to finish."""
        if self._closed:
            return
        self._closed = True
        for queue in self._subscribers:
            queue.put_nowait(None)
