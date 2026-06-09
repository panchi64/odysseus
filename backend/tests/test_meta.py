"""The meta-loop: the no-progress loop-breaker and the optional verifier."""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

import agent.engine as engine
from agent.meta import LoopBreaker, LoopDetected, Verdict
from core.config import Settings
from runs import RunRegistry, RunStatus


# --- LoopBreaker (unit) ------------------------------------------------------
def test_loop_breaker_trips_on_identical_repeats():
    breaker = LoopBreaker(repeat_threshold=3)
    breaker.check("search", {"q": "x"})
    breaker.check("search", {"q": "x"})
    with pytest.raises(LoopDetected):
        breaker.check("search", {"q": "x"})


def test_loop_breaker_ignores_varied_calls():
    breaker = LoopBreaker(repeat_threshold=2)
    breaker.check("search", {"q": "a"})
    breaker.check("search", {"q": "b"})  # different args → no trip
    breaker.check("other", {"q": "a"})  # different tool → no trip


# --- Loop-breaker wired into a run -------------------------------------------
async def test_run_blocks_when_loop_detected(monkeypatch):
    # threshold=1 trips on the first tool call — exercises the wiring end to end.
    monkeypatch.setattr(engine, "get_settings", lambda: Settings(loop_repeat_threshold=1))
    reg = RunRegistry()
    orch = engine.build_chat_orchestrator("use a tool", model=TestModel(custom_output_text="x"))
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.blocked
    types = [e.body.type for e in run.stream.replay()]
    assert "limit.notice" in types
    loop_notice = next(e.body for e in run.stream.replay() if e.body.type == "limit.notice")
    assert loop_notice.limit == "loop"


# --- Verifier ----------------------------------------------------------------
async def test_verifier_disabled_by_default():
    calls = []

    async def judge(request, answer):
        calls.append((request, answer))
        return Verdict(ok=False, reason="should not run")

    reg = RunRegistry()
    orch = engine.build_chat_orchestrator(
        "hello", model=TestModel(custom_output_text="hi"), judge=judge
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    assert calls == []  # verify_enabled is False by default


async def test_verifier_makes_one_corrective_attempt(monkeypatch):
    monkeypatch.setattr(engine, "get_settings", lambda: Settings(verify_enabled=True))
    verdicts = [Verdict(ok=False, reason="missing the summary")]
    seen = []

    async def judge(request, answer):
        seen.append(answer)
        return verdicts.pop(0) if verdicts else Verdict(ok=True)

    reg = RunRegistry()
    orch = engine.build_chat_orchestrator(
        "summarize it", model=TestModel(custom_output_text="here"), judge=judge
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    assert len(seen) == 1  # judged once; one bounded re-attempt, no re-judge
    types = [e.body.type for e in run.stream.replay()]
    assert "limit.notice" in types
    notice = next(e.body for e in run.stream.replay() if e.body.type == "limit.notice")
    assert notice.limit == "verify"


async def test_verifier_accepts_a_good_answer(monkeypatch):
    monkeypatch.setattr(engine, "get_settings", lambda: Settings(verify_enabled=True))

    async def judge(request, answer):
        return Verdict(ok=True)

    reg = RunRegistry()
    orch = engine.build_chat_orchestrator(
        "hello", model=TestModel(custom_output_text="hi"), judge=judge
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert run.status is RunStatus.done
    types = [e.body.type for e in run.stream.replay()]
    assert "limit.notice" not in types  # no re-attempt
