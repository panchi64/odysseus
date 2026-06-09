"""Pillar I/II — SSE transport: turn a Run's event stream into an HTTP response.

The only transport in v1 (SSE for server→client, POST for control). Disconnect
is safe — the generator just unsubscribes; the Run keeps executing and is fully
replayable on reconnect via ``Last-Event-ID``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from .run import Run

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering so frames flush live
}


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
        async for event in run.stream.subscribe(after_seq):
            yield event.sse()

    return StreamingResponse(frames(), media_type="text/event-stream", headers=_SSE_HEADERS)
