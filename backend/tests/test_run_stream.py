"""RunStream: seq stamping, buffer replay, live fan-out, resume, close."""

from __future__ import annotations

import asyncio

from runs import RunStream
from runs.events import AnswerDelta


def _texts(events):
    return [e.body.text for e in events]


async def test_emit_assigns_monotonic_seq():
    stream = RunStream()
    a = stream.emit(AnswerDelta(text="a"))
    b = stream.emit(AnswerDelta(text="b"))
    assert (a.seq, b.seq) == (1, 2)
    assert stream.last_seq == 2


async def test_subscribe_after_close_replays_backlog_then_ends():
    stream = RunStream()
    stream.emit(AnswerDelta(text="a"))
    stream.emit(AnswerDelta(text="b"))
    stream.close()
    got = [e async for e in stream.subscribe()]
    assert _texts(got) == ["a", "b"]


async def test_resume_filters_by_after_seq():
    stream = RunStream()
    for t in ("a", "b", "c"):
        stream.emit(AnswerDelta(text=t))
    stream.close()
    got = [e async for e in stream.subscribe(after_seq=1)]
    assert _texts(got) == ["b", "c"]
    assert [e.seq for e in got] == [2, 3]


async def test_live_subscriber_receives_emitted():
    stream = RunStream()
    received: list = []

    async def consume():
        async for event in stream.subscribe():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let it register
    stream.emit(AnswerDelta(text="a"))
    stream.emit(AnswerDelta(text="b"))
    await asyncio.sleep(0)
    stream.close()
    await task
    assert _texts(received) == ["a", "b"]


async def test_backlog_then_live_no_gap_no_duplicate():
    stream = RunStream()
    stream.emit(AnswerDelta(text="a"))  # buffered before subscribe
    received: list = []

    async def consume():
        async for event in stream.subscribe():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    stream.emit(AnswerDelta(text="b"))  # arrives live
    await asyncio.sleep(0)
    stream.close()
    await task
    assert _texts(received) == ["a", "b"]
    assert [e.seq for e in received] == [1, 2]


async def test_fanout_to_multiple_subscribers():
    stream = RunStream()
    out_a: list = []
    out_b: list = []

    async def consume(sink):
        async for event in stream.subscribe():
            sink.append(event)

    tasks = [asyncio.create_task(consume(out_a)), asyncio.create_task(consume(out_b))]
    await asyncio.sleep(0)
    stream.emit(AnswerDelta(text="x"))
    await asyncio.sleep(0)
    stream.close()
    await asyncio.gather(*tasks)
    assert _texts(out_a) == ["x"]
    assert _texts(out_b) == ["x"]
