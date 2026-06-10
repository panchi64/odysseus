"""The reusable write-behind worker: draining, retry/drop, and lock-awareness."""

from __future__ import annotations

import asyncio

from core.worker import WriteBehindWorker


async def test_drains_submitted_items_in_order():
    seen: list[int] = []

    async def handler(x: int) -> None:
        seen.append(x)

    worker = WriteBehindWorker(handler, name="t")
    await worker.start()
    worker.submit(1)
    worker.submit(2)
    await worker.join()
    await worker.stop()

    assert seen == [1, 2]


async def test_retries_then_succeeds():
    calls: list[str] = []

    async def handler(x: str) -> None:
        calls.append(x)
        if len(calls) < 2:
            raise RuntimeError("transient")

    worker = WriteBehindWorker(handler, name="t", max_attempts=4, base_backoff_s=0.0)
    await worker.start()
    worker.submit("x")
    await worker.join()
    await worker.stop()

    assert len(calls) == 2  # failed once, retried, succeeded — not dropped


async def test_drops_and_reports_after_exhausting_retries():
    attempts: list[str] = []
    dropped: list[tuple[str, str]] = []

    async def handler(x: str) -> None:
        attempts.append(x)
        raise ValueError("boom")

    worker = WriteBehindWorker(
        handler,
        name="t",
        max_attempts=3,
        base_backoff_s=0.0,
        on_drop=lambda item, exc: dropped.append((item, str(exc))),
    )
    await worker.start()
    worker.submit("a")
    await worker.join()
    await worker.stop()

    assert len(attempts) == 3  # tried exactly max_attempts times
    assert dropped == [("a", "boom")]  # terminal failure surfaced, not silent


async def test_lock_gated_worker_parks_until_unlocked():
    unlocked = asyncio.Event()  # starts locked
    seen: list[str] = []

    async def handler(x: str) -> None:
        seen.append(x)

    worker = WriteBehindWorker(handler, name="t", unlocked=unlocked)
    await worker.start()
    worker.submit("a")
    await asyncio.sleep(0.02)
    assert seen == []  # parked while the vault is locked

    unlocked.set()
    await worker.join()
    assert seen == ["a"]  # caught up on unlock
    await worker.stop()


async def test_stop_does_not_hang_when_locked():
    unlocked = asyncio.Event()  # never unlocked
    seen: list[str] = []

    async def handler(x: str) -> None:
        seen.append(x)

    worker = WriteBehindWorker(handler, name="t", unlocked=unlocked)
    await worker.start()
    worker.submit("a")
    await asyncio.sleep(0.02)
    # Shutdown while locked must not block on the parked item.
    await asyncio.wait_for(worker.stop(), timeout=1.0)
    assert seen == []
