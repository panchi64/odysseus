"""The chat orchestrator on the Run substrate: end-to-end with a TestModel."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

import agent.engine as engine
from agent import build_chat_orchestrator
from core.config import Settings
from runs import RunRegistry, RunStatus


def _bodies(run):
    return [e.body for e in run.stream.replay()]


async def test_chat_runs_to_done_with_metrics():
    reg = RunRegistry()
    orch = build_chat_orchestrator("hello", model=TestModel(custom_output_text="hi there"))
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    types = [b.type for b in _bodies(run)]
    assert types[0] == "run.started"
    assert types[-1] == "run.ended"
    assert "answer.delta" in types

    answer = "".join(b.text for b in _bodies(run) if b.type == "answer.delta")
    assert answer == "hi there"

    metrics = next(b for b in _bodies(run) if b.type == "run.metrics")
    assert metrics.steps >= 1


async def test_metrics_accumulate_across_verifier_correction(monkeypatch):
    # A verifier correction is a second turn; the reported metrics must cover the
    # whole run, not just the corrective turn.
    from agent.meta import Verdict

    monkeypatch.setattr(
        engine, "get_settings", lambda: Settings(verify_enabled=True, verify_heuristic=False)
    )
    verdicts = [Verdict(ok=False, reason="redo")]

    async def judge(request, answer):
        return verdicts.pop(0) if verdicts else Verdict(ok=True)

    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "hello", model=TestModel(custom_output_text="hi"), categories={}, judge=judge
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    metrics = next(b for b in _bodies(run) if b.type == "run.metrics")
    assert metrics.steps >= 2  # original turn + the corrective re-attempt


async def test_usage_limit_blocks_the_turn(monkeypatch):
    # request_limit=0 trips on the first model request → bounded stop.
    monkeypatch.setattr(
        engine, "get_settings", lambda: Settings(agent_request_limit=0, agent_tool_calls_limit=None)
    )
    reg = RunRegistry()
    orch = build_chat_orchestrator("hello", model=TestModel(custom_output_text="never"))
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.blocked
    types = [b.type for b in _bodies(run)]
    assert "limit.notice" in types
    assert _bodies(run)[-1].outcome == "blocked"
