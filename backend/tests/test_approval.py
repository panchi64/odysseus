"""Approval flow: a sensitive tool parks the run; approve/deny resumes it."""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ToolApproved, ToolDenied
from pydantic_ai.models.test import TestModel

from agent import ParkedTurn, build_chat_orchestrator, build_resume_orchestrator
from core.db import init_db, make_engine
from core.vault import Vault
from runs import RunRegistry, RunStatus
from services.notifications import NotificationService
from tools import Capabilities, RunDeps


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


# --- approval_needed notification wiring --------------------------------------------


async def _notification_service(tmp_path) -> NotificationService:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    service = NotificationService(engine, vault)
    await service.start()
    return service


async def test_park_notifies_approval_needed(tmp_path):
    service = await _notification_service(tmp_path)
    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "delete the thing",
        model=TestModel(custom_output_text="done"),
        categories=_danger_categories(),
        capabilities=Capabilities(notifications=service),
        conversation_id="c1",
    )
    run = reg.submit(
        kind="chat", owner_id="operator", orchestrator=orch, conversation_id="c1"
    )
    await run.wait()

    assert run.status is RunStatus.awaiting_input
    items, unread = await service.list_notifications("operator")
    assert unread == 1
    assert items[0].kind == "approval_needed"
    assert items[0].run_id == run.id
    assert items[0].conversation_id == "c1"
    assert "delete_thing" in items[0].title
    await service.stop()


async def test_grant_short_circuit_resolves_a_dangling_notification(tmp_path):
    # Everything this turn defers is already grant-covered from the start, so the
    # engine never parks — it continues the same turn inline. That branch is a
    # defensive `resolve_for_run` call too: this proves it actually fires by seeding a
    # notification for this exact run id up front and checking it's resolved after.
    from tests._helpers import granting_store

    # Learn the real (namespaced) tool name a park reports, rather than guessing it.
    probe_run = await _park_a_run(RunRegistry())
    tool_name = probe_run.parked_payload.requests.approvals[0].tool_name

    service = await _notification_service(tmp_path)
    grants = await granting_store("operator", "c1", tool_name)
    run_id = "preset-run-1"
    await service.notify("operator", "approval_needed", "stale", run_id=run_id)

    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "delete the thing",
        model=TestModel(custom_output_text="done"),
        categories=_danger_categories(),
        capabilities=Capabilities(grants=grants, notifications=service),
        conversation_id="c1",
    )
    run = reg.submit(
        kind="chat",
        owner_id="operator",
        orchestrator=orch,
        conversation_id="c1",
        run_id=run_id,
    )
    await run.wait()

    assert run.status is RunStatus.done  # grant-covered inline — never parked
    items, _ = await service.list_notifications("operator")
    assert items[0].resolved_at is not None
    await service.stop()
