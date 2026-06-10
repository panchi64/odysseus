"""A reusable write-behind worker — the background-drainer substrate.

A single asyncio task drains a queue off the hot path. Failed items retry with
bounded exponential backoff; an item that exhausts its retries is handed to an
``on_drop`` callback so a terminal failure is **surfaced, not silently lost**.

Optionally **lock-aware**: a worker whose handler touches the encryption key
takes the vault's ``unlocked`` event and parks while the vault is locked,
resuming when it unlocks — rather than erroring on a missing key. While stopping,
a lock-parked worker stops waiting so shutdown never hangs.

This is the one place the "we own the queues" substrate lives. The conversation
persistence drainer is the first instance; the scheduler and notification
dispatch are meant to reuse it rather than re-implement queue + lifecycle +
retry + lock-awareness each time.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

logger = logging.getLogger(__name__)


class WriteBehindWorker[T]:
    """Drains submitted items to ``handler`` on a background task.

    ``unlocked`` (the vault's event) gates processing on the vault being open —
    pass it only for handlers that touch the encryption key. ``on_drop`` is
    called with ``(item, exc)`` when an item exhausts ``max_attempts``.
    """

    def __init__(
        self,
        handler: Callable[[T], Awaitable[None]],
        *,
        name: str,
        unlocked: asyncio.Event | None = None,
        max_attempts: int = 4,
        base_backoff_s: float = 0.2,
        on_drop: Callable[[T, Exception], None] | None = None,
    ) -> None:
        self._handler = handler
        self._name = name
        self._unlocked = unlocked
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s
        self._on_drop = on_drop
        self._queue: asyncio.Queue[T] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def submit(self, item: T) -> None:
        """Hot path: enqueue an item for background processing (never blocks)."""
        self._queue.put_nowait(item)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name=self._name)

    async def join(self) -> None:
        """Block until every queued item has been processed (or dropped)."""
        await self._queue.join()

    async def stop(self) -> None:
        """Flush what can be flushed, then cancel the drainer.

        When lock-gated and currently locked, processing is parked, so we don't
        block shutdown on ``join()`` — pending items stay unflushed.
        """
        self._stopping.set()
        if self._unlocked is None or self._unlocked.is_set():
            await self._queue.join()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if await self._ready():
                    await self._process(item)
            finally:
                self._queue.task_done()

    async def _ready(self) -> bool:
        """Wait until the vault is unlocked. False if stopping while still locked."""
        if self._unlocked is None or self._unlocked.is_set():
            return True
        stop_wait = asyncio.ensure_future(self._stopping.wait())
        unlock_wait = asyncio.ensure_future(self._unlocked.wait())
        try:
            await asyncio.wait({stop_wait, unlock_wait}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop_wait.cancel()
            unlock_wait.cancel()
        return self._unlocked.is_set()

    async def _process(self, item: T) -> None:
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._handler(item)
                return
            except Exception as exc:  # noqa: BLE001 — a bad item must not kill the worker
                if attempt >= self._max_attempts:
                    logger.exception("%s: dropping item after %d attempts", self._name, attempt)
                    if self._on_drop is not None:
                        self._on_drop(item, exc)
                    return
                await asyncio.sleep(self._base_backoff_s * 2 ** (attempt - 1))
