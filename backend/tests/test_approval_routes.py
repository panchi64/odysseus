"""POST /runs/{id}/approve: the end-to-end approval flow over HTTP."""

from __future__ import annotations

import asyncio

from pydantic_ai import FunctionToolset
from pydantic_ai.models.test import TestModel

import tools.toolsets as toolsets
from services.registry import ModelRegistry, ResolvedModel
from tools import RunDeps

from ._helpers import client_app, collect_sse_events


def _install_sensitive_tool(monkeypatch):
    """Point the model at a TestModel and give it one approval-required tool."""

    async def fake_resolve(self, role, *, owner_id, override_endpoint_id=None, override_model=None):
        return TestModel(custom_output_text="done")

    async def fake_resolve_detailed(self, role, **kwargs):
        # The titler runs on this (toolless) agent after the approved turn
        # completes; a plain text model names the thread without tool calls.
        return ResolvedModel(model=TestModel(custom_output_text="done"), reasoning_off={})

    def danger_categories():
        toolset: FunctionToolset[RunDeps] = FunctionToolset()

        @toolset.tool_plain(requires_approval=True)
        def delete_thing(name: str) -> str:
            return f"deleted {name}"

        return {"danger": toolset}

    monkeypatch.setattr(ModelRegistry, "resolve", fake_resolve)
    monkeypatch.setattr(ModelRegistry, "resolve_detailed", fake_resolve_detailed)
    monkeypatch.setattr(toolsets, "default_categories", danger_categories)


async def _await_parked(app, run_id):
    # Poll with a real (small) sleep, not a bare yield: under full-suite load the
    # background run needs wall-clock to reach awaiting_input, and 100 sleep(0)
    # yields can starve before it does (a flaky "never parked").
    for _ in range(200):
        run = app.state.runs.get(run_id)
        if run is not None and run.status == "awaiting_input":
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("run never parked")


async def test_approve_flow_resumes_and_completes(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)

        status = (await client.get(f"/runs/{run_id}")).json()
        assert status["status"] == "awaiting_input"

        call_id = run.parked_payload.requests.approvals[0].tool_call_id
        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={"decisions": [{"tool_call_id": call_id, "approved": True}]},
        )
        assert resp.status_code == 202

        events = await collect_sse_events(client, run_id)

    types = [e["type"] for e in events]
    assert "approval.required" in types
    assert "tool.completed" in types
    assert types[-1] == "run.ended"


async def test_approve_rejects_unknown_and_unparked(monkeypatch):
    async with client_app() as (client, app):
        # unknown run
        resp = await client.post("/runs/nope/approve", json={"decisions": []})
        assert resp.status_code == 404

        # a finished (not parked) run → 409
        async def orch(run):
            return None

        run = app.state.runs.submit(kind="chat", owner_id="operator", orchestrator=orch)
        await run.wait()
        resp = await client.post(f"/runs/{run.id}/approve", json={"decisions": []})
        assert resp.status_code == 409


async def test_approve_with_conversation_scope_records_grant(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)
        approval = run.parked_payload.requests.approvals[0]
        conv_id = run.conversation_id

        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={
                "decisions": [
                    {
                        "tool_call_id": approval.tool_call_id,
                        "approved": True,
                        "scope": "conversation",
                    }
                ]
            },
        )
        assert resp.status_code == 202

        # The grant is recorded and visible on the conversation's grants surface.
        granted = await app.state.approval_grants.active("operator", conv_id)
        assert approval.tool_name in granted
        listed = (await client.get(f"/conversations/{conv_id}/grants")).json()
        assert any(g["tool_name"] == approval.tool_name for g in listed)


async def test_failed_resume_rolls_back_the_recorded_grant(monkeypatch):
    # The grant is written *before* resume (so the resumed turn's inline check sees it),
    # but a resume that can't be accepted must leave no standing auto-approval behind.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)
        approval = run.parked_payload.requests.approvals[0]
        conv_id = run.conversation_id

        async def fail_resume(run_id, orchestrator):
            return None

        monkeypatch.setattr(app.state.runs, "resume", fail_resume)
        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={
                "decisions": [
                    {
                        "tool_call_id": approval.tool_call_id,
                        "approved": True,
                        "scope": "conversation",
                    }
                ]
            },
        )
        assert resp.status_code == 409
        granted = await app.state.approval_grants.active("operator", conv_id)
        assert approval.tool_name not in granted


async def test_approve_rejects_decision_mismatch(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        await _await_parked(app, run_id)
        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={"decisions": [{"tool_call_id": "wrong-id", "approved": True}]},
        )
        assert resp.status_code == 400


# --- approval_needed notification: park creates it, every decision resolves it -----


async def _run_notifications(app, run_id):
    items, _ = await app.state.notifications.list_notifications("operator", limit=100)
    return [n for n in items if n.run_id == run_id]


async def _drain_terminal_notify_tasks(app):
    """Await every in-flight run-terminal notify task. `_on_run_terminal` (app.py)
    adds its task to `run_terminal_tasks` synchronously before the registry's own
    cancel/`run.wait()` call can return, so it's already registered by the time a
    caller reaches here — one `gather` is enough to settle it."""
    pending = list(app.state.run_terminal_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_park_creates_approval_needed_and_approve_resolves_it(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)

        notifs = await _run_notifications(app, run_id)
        assert len(notifs) == 1
        assert notifs[0].kind == "approval_needed"
        assert notifs[0].resolved_at is None

        call_id = run.parked_payload.requests.approvals[0].tool_call_id
        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={"decisions": [{"tool_call_id": call_id, "approved": True}]},
        )
        assert resp.status_code == 202

        notifs = await _run_notifications(app, run_id)
        assert notifs[0].resolved_at is not None


async def test_deny_resolves_the_approval_needed_notification(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)
        call_id = run.parked_payload.requests.approvals[0].tool_call_id

        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={"decisions": [{"tool_call_id": call_id, "approved": False}]},
        )
        assert resp.status_code == 202

        notifs = await _run_notifications(app, run_id)
        assert notifs[0].resolved_at is not None


async def test_cancel_while_parked_resolves_the_approval_needed_notification(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        await _await_parked(app, run_id)

        assert await app.state.runs.cancel(run_id) is True
        await _drain_terminal_notify_tasks(app)

        notifs = await _run_notifications(app, run_id)
        assert len(notifs) == 1
        assert notifs[0].resolved_at is not None
        # Cancelling never itself creates a run_completed/run_failed notification.
        assert all(n.kind == "approval_needed" for n in notifs)
