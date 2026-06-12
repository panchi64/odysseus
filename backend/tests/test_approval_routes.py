"""POST /runs/{id}/approve: the end-to-end approval flow over HTTP."""

from __future__ import annotations

import asyncio

from pydantic_ai import FunctionToolset
from pydantic_ai.models.test import TestModel

import tools.toolsets as toolsets
from services.registry import ModelRegistry
from tools import RunDeps

from ._helpers import client_app, collect_sse_events


def _install_sensitive_tool(monkeypatch):
    """Point the model at a TestModel and give it one approval-required tool."""

    async def fake_resolve(self, role, *, owner_id, override_endpoint_id=None, override_model=None):
        return TestModel(custom_output_text="done")

    def danger_categories():
        toolset: FunctionToolset[RunDeps] = FunctionToolset()

        @toolset.tool_plain(requires_approval=True)
        def delete_thing(name: str) -> str:
            return f"deleted {name}"

        return {"danger": toolset}

    monkeypatch.setattr(ModelRegistry, "resolve", fake_resolve)
    monkeypatch.setattr(toolsets, "default_categories", danger_categories)


async def _await_parked(app, run_id):
    for _ in range(100):
        run = app.state.runs.get(run_id)
        if run is not None and run.status == "awaiting_input":
            return run
        await asyncio.sleep(0)
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
