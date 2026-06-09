"""Approval flow: a sensitive tool parks the run; approve/deny resumes it."""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ToolApproved, ToolDenied
from pydantic_ai.models.test import TestModel

from agent import ParkedTurn, build_chat_orchestrator, build_resume_orchestrator
from runs import RunRegistry, RunStatus
from tools import RunDeps


def _danger_categories():
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True)
    def delete_thing(name: str) -> str:
        return f"deleted {name}"

    return {"danger": toolset}


def _types(run):
    return [e.body.type for e in run.stream.replay()]


async def _park_a_run(reg: RunRegistry):
    orch = build_chat_orchestrator(
        "delete the thing",
        model=TestModel(custom_output_text="done"),
        categories=_danger_categories(),
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()
    return run


async def test_sensitive_tool_parks_for_approval():
    reg = RunRegistry()
    run = await _park_a_run(reg)

    assert run.status is RunStatus.awaiting_input
    assert not run.stream.closed  # stream stays open for the resume
    types = _types(run)
    assert "approval.required" in types
    assert "tool.completed" not in types  # not executed — only requested
    assert "run.ended" not in types  # not terminal

    approval = next(e.body for e in run.stream.replay() if e.body.type == "approval.required")
    assert "delete_thing" in approval.name
    assert "name" in approval.args
    assert approval.summary.startswith(approval.name)
    assert isinstance(run.parked_payload, ParkedTurn)


async def test_approved_resume_executes_and_completes():
    reg = RunRegistry()
    run = await _park_a_run(reg)
    parked: ParkedTurn = run.parked_payload
    call_id = parked.requests.approvals[0].tool_call_id

    resumed = await reg.resume(run.id, build_resume_orchestrator(parked, {call_id: ToolApproved()}))
    assert resumed is run
    await run.wait()

    assert run.status is RunStatus.done
    types = _types(run)
    assert "tool.completed" in types  # executed after approval
    assert types[-1] == "run.ended"
    assert run.stream.closed
    # tool.started was announced once (defer turn), not duplicated on resume
    assert _types(run).count("tool.started") == 1


async def test_denied_resume_completes_without_executing():
    reg = RunRegistry()
    run = await _park_a_run(reg)
    parked: ParkedTurn = run.parked_payload
    call_id = parked.requests.approvals[0].tool_call_id

    await reg.resume(run.id, build_resume_orchestrator(parked, {call_id: ToolDenied(message="no")}))
    await run.wait()

    assert run.status is RunStatus.done
    # The denial is surfaced to the model as the call's result, but the tool
    # body never ran — no real side effect.
    completed = [e.body for e in run.stream.replay() if e.body.type == "tool.completed"]
    assert all("deleted" not in str(b.result) for b in completed)


async def test_cancel_parked_run():
    reg = RunRegistry()
    run = await _park_a_run(reg)

    assert await reg.cancel(run.id) is True
    assert run.status is RunStatus.cancelled
    assert run.stream.closed
    assert _types(run)[-1] == "run.ended"
