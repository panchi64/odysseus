"""RunRegistry: lifecycle, terminal mapping, bounds, cancellation, queueing."""

from __future__ import annotations

import asyncio

from runs import RunRegistry, RunStatus
from runs.events import AnswerDelta


def _types(run):
    return [e.body.type for e in run.stream.replay()]


async def test_run_completes_done():
    reg = RunRegistry()

    async def orch(run):
        run.emit(AnswerDelta(text="hi"))

    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    assert _types(run) == ["run.started", "answer.delta", "run.metrics", "run.ended"]
    ended = run.stream.replay()[-1].body
    assert ended.outcome == "done"


async def test_run_error_is_terminal_not_fatal():
    reg = RunRegistry()

    async def orch(run):
        raise ValueError("boom")

    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.error
    assert run.error == "boom"
    err = run.stream.replay()[-1].body
    assert err.type == "run.error"
    assert err.kind == "ValueError"
    assert err.message == "boom"


async def test_run_blocked_outcome():
    reg = RunRegistry()

    async def orch(run):
        run.block("need more info")

    run = reg.submit(kind="agent", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.blocked
    ended = run.stream.replay()[-1].body
    assert ended.type == "run.ended"
    assert ended.outcome == "blocked"
    assert ended.detail == "need more info"


async def test_cancel_running_run():
    reg = RunRegistry()

    async def orch(run):
        run.emit(AnswerDelta(text="working"))
        await asyncio.Event().wait()  # never completes on its own

    run = reg.submit(kind="agent", owner_id="operator", orchestrator=orch)
    await asyncio.sleep(0)  # let it start
    assert await reg.cancel(run.id) is True
    await run.wait()

    assert run.status is RunStatus.cancelled
    assert run.stream.replay()[-1].body.outcome == "cancelled"
    # cancelling an already-terminal run is a no-op
    assert await reg.cancel(run.id) is False


async def test_wall_clock_timeout():
    reg = RunRegistry(wall_clock_timeout_s=0.05, inactivity_timeout_s=None)

    async def orch(run):
        run.emit(AnswerDelta(text="start"))
        await asyncio.sleep(5)

    run = reg.submit(kind="research", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.error
    err = run.stream.replay()[-1].body
    assert err.type == "run.error"
    assert err.kind == "wall_clock_timeout"


async def test_inactivity_timeout():
    reg = RunRegistry(wall_clock_timeout_s=5.0, inactivity_timeout_s=0.05)

    async def orch(run):
        run.emit(AnswerDelta(text="start"))
        await asyncio.sleep(5)  # no further events → inactivity fires

    run = reg.submit(kind="research", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.error
    assert run.stream.replay()[-1].body.kind == "inactivity_timeout"


async def test_concurrency_limit_queues_bursts():
    reg = RunRegistry(max_concurrency=1)
    started1, release1 = asyncio.Event(), asyncio.Event()
    started2, release2 = asyncio.Event(), asyncio.Event()

    async def orch(started, release):
        async def _run(run):
            started.set()
            await release.wait()

        return _run

    run1 = reg.submit(kind="t", owner_id="operator", orchestrator=await orch(started1, release1))
    run2 = reg.submit(kind="t", owner_id="operator", orchestrator=await orch(started2, release2))

    await started1.wait()
    assert run1.status is RunStatus.running
    assert run2.status is RunStatus.queued  # blocked at the concurrency gate

    release1.set()
    await run1.wait()
    await started2.wait()
    assert run2.status is RunStatus.running

    release2.set()
    await run2.wait()
    assert run1.status is RunStatus.done
    assert run2.status is RunStatus.done


async def test_list_filters_by_owner():
    reg = RunRegistry()

    async def orch(run):
        return None

    a = reg.submit(kind="t", owner_id="alice", orchestrator=orch)
    b = reg.submit(kind="t", owner_id="bob", orchestrator=orch)
    await asyncio.gather(a.wait(), b.wait())

    assert {r.id for r in reg.list(owner_id="alice")} == {a.id}
    assert {r.id for r in reg.list()} == {a.id, b.id}
