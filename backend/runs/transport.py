"""Pillar I/II — SSE transport: turn a Run's event stream into an HTTP response.

The only transport in v1 (SSE for server→client, POST for control). Disconnect
is safe — the generator just unsubscribes; the Run keeps executing and is fully
replayable on reconnect via ``Last-Event-ID``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi.responses import StreamingResponse

from .events import Event
from .run import Run

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering so frames flush live
}

# Emit a comment frame when the run has been quiet this long, so a client can tell
# a legitimately quiet run (a slow tool call) from a dead connection. Comment
# frames carry no ``data:`` line, so the client parser ignores them.
_KEEPALIVE_INTERVAL_S = 15.0

# The relay queue between the pump and the response is bounded so a client that
# stops draining (a backgrounded tab) can't make it buffer the whole run. When it
# fills, the pump blocks on ``put`` and stops draining the subscription, which the
# RunStream then drops the same way it drops any wedged consumer — keeping the
# "never grow unbounded" invariant from ``runs/CLAUDE.md``.
_RELAY_QUEUE_MAX = 256


def parse_last_event_id(header_value: str | None, query_value: int | None) -> int:
    """Resolve the resume point from the SSE header or an explicit query param."""
    if header_value:
        try:
            return max(0, int(header_value))
        except ValueError:
            pass
    if query_value is not None:
        return max(0, query_value)
    return 0


def sse_response(run: Run, after_seq: int = 0) -> StreamingResponse:
    async def frames() -> AsyncIterator[str]:
        # Pump the run's events through a local queue so the keepalive timeout sits
        # on the queue, not on the subscribe generator itself — cancelling the
        # latter mid-await would unsubscribe it. Cancelling the pump task on
        # disconnect closes the subscription cleanly through its own ``finally``.
        queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=_RELAY_QUEUE_MAX)

        async def pump() -> None:
            try:
                async for event in run.stream.subscribe(after_seq):
                    await queue.put(event)
            finally:
                # Best-effort sentinel — never block here. On a full queue the
                # consumer is already gone (disconnect cancels this task), so a
                # blocking put would just deadlock the cancellation.
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(None)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), _KEEPALIVE_INTERVAL_S)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:  # the subscription ended (run terminal / dropped)
                    break
                yield item.sse()
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(frames(), media_type="text/event-stream", headers=_SSE_HEADERS)
