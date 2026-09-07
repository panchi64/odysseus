"""POST /runs/{id}/approve: the end-to-end approval flow over HTTP."""

from __future__ import annotations

import asyncio

from pydantic_ai import FunctionToolset
from pydantic_ai.models.test import TestModel

from services.registry import ModelRegistry
from tools import RunDeps

from ._helpers import (
    client_app,
    collect_sse_events,
    register_stub_provider,
    stub_resolution,
    swap_tool_catalog,
)


def danger_categories():
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True)
    def delete_thing(name: str) -> str:
        return f"deleted {name}"

    return {"danger": toolset}


def egress_categories():
    """A `code` category whose one tool is namespaced `code_request_egress` — the name
    `ONCE_ONLY_TOOLS` pins."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True)
    def request_egress(domain: str) -> str:
        return f"allowed {domain}"

    return {"code": toolset}


def _install_sensitive_tool(monkeypatch):
    """Point the model at a TestModel; pair with ``swap_tool_catalog(app,
    danger_categories())`` after boot so the catalog is exactly the one
    approval-required tool."""

    async def fake_resolve_detailed(self, role, **kwargs):
        # One patch covers the whole run: the turn's own model and the titler that
        # runs (on a toolless agent) after the approved turn completes both resolve
        # through here. A plain text model names the thread without tool calls.
        return await stub_resolution(self, TestModel(custom_output_text="done"))

    register_stub_provider(monkeypatch)
    monkeypatch.setattr(ModelRegistry, "resolve_detailed", fake_resolve_detailed)


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
        swap_tool_catalog(app, danger_categories())
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


async def test_approve_resumes_under_the_operators_bounds(monkeypatch):
    # The continuation is a turn like any other, so it must run under the operator's own
    # bounds rather than the registry defaults — a wall clock that applied to send but not
    # to the resumed half of an approval-gated turn would be a setting that lies.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, danger_categories())
        await client.put(
            "/chat/settings", json={"wall_clock_timeout_s": 900, "inactivity_timeout_s": 45}
        )
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)

        seen: dict[str, object] = {}
        real_resume = app.state.runs.resume

        async def spy(rid, orchestrator, **kwargs):
            seen.update(kwargs)
            return await real_resume(rid, orchestrator, **kwargs)

        monkeypatch.setattr(app.state.runs, "resume", spy)

        call_id = run.parked_payload.requests.approvals[0].tool_call_id
        resp = await client.post(
            f"/runs/{run_id}/approve",
            json={"decisions": [{"tool_call_id": call_id, "approved": True}]},
        )
        assert resp.status_code == 202
        await collect_sse_events(client, run_id)

    assert seen == {"wall_clock_timeout_s": 900, "inactivity_timeout_s": 45}


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
        swap_tool_catalog(app, danger_categories())
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

        # The grant is recorded and visible on the conversation's grants surface. The tool
        # runs no command, so it is the whole-tool scope — an empty prefix.
        granted = await app.state.approval_grants.list("operator", conv_id)
        assert (approval.tool_name, ()) in {(g.tool_name, g.command_prefix) for g in granted}
        listed = (await client.get(f"/conversations/{conv_id}/grants")).json()
        assert any(
            g["tool_name"] == approval.tool_name and g["command_prefix"] == [] for g in listed
        )


def command_categories():
    """A catalog holding one approval-gated tool that *runs a command* — the shape a
    conversation grant is scoped to rather than granted wholesale."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True, name="run_host_command")
    def run_host_command(command: str) -> str:
        return f"ran {command}"

    return {"code": toolset}


async def test_a_conversation_grant_on_a_command_names_the_command(monkeypatch):
    # The scope is derived here, from the parked call, and never sent by the client: what
    # the operator said yes to is the act the agent actually asked for.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, command_categories())
        run_id = (await client.post("/chat", json={"prompt": "run it"})).json()["run_id"]
        run = await _await_parked(app, run_id)
        approval = run.parked_payload.requests.approvals[0]
        assert approval.tool_name == "code_run_host_command"
        command = approval.args_as_dict()["command"]
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

        listed = (await client.get(f"/conversations/{conv_id}/grants")).json()
        assert [(g["tool_name"], g["command_prefix"]) for g in listed] == [
            ("code_run_host_command", command.split())
        ]

        # Revoking is by the same pair, and the scope goes back **exactly as it was
        # listed** — one parameter per word, never a sentence something else has to split.
        # The whole-tool form leaves the narrower grant standing; only the matching scope
        # drops it, which is what makes the listing and the delete one round trip.
        assert (
            await client.delete(f"/conversations/{conv_id}/grants/code_run_host_command")
        ).status_code == 204
        assert len((await client.get(f"/conversations/{conv_id}/grants")).json()) == 1
        assert (
            await client.delete(
                f"/conversations/{conv_id}/grants/code_run_host_command",
                params={"command_prefix": listed[0]["command_prefix"]},
            )
        ).status_code == 204
        assert (await client.get(f"/conversations/{conv_id}/grants")).json() == []


async def test_a_grant_names_the_command_the_operator_edited_it_to(monkeypatch):
    # An override *replaces* the call's arguments, so the act being approved is the edited
    # one. Deriving the standing yes from the arguments the model wrote would record a
    # grant for a command nobody is going to run — and, worse, for the one the operator
    # rejected by editing it away.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, command_categories())
        run_id = (await client.post("/chat", json={"prompt": "run it"})).json()["run_id"]
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
                        "override_args": {"command": "echo skipped"},
                    }
                ]
            },
        )
        assert resp.status_code == 202
        assert resp.json()["granted"] == [["echo", "skipped"]]

        listed = (await client.get(f"/conversations/{conv_id}/grants")).json()
        assert [g["command_prefix"] for g in listed] == [["echo", "skipped"]]


async def test_a_command_no_scope_could_stand_for_records_nothing_and_says_so(monkeypatch):
    # `grant_scopes` refuses a command the grammar cannot read, which is the right call —
    # but the operator ticked a box that promised a standing yes, so the refusal is
    # reported rather than left to be noticed as a missing chip.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, command_categories())
        run_id = (await client.post("/chat", json={"prompt": "run it"})).json()["run_id"]
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
                        "override_args": {"command": "cat $TARGET"},
                    }
                ]
            },
        )
        assert resp.status_code == 202
        assert resp.json() == {
            "status": "resuming",
            "granted": [],
            "unscoped": [approval.tool_call_id],
        }
        assert (await client.get(f"/conversations/{conv_id}/grants")).json() == []


async def test_egress_request_never_records_a_conversation_grant(monkeypatch):
    # A conversation grant auto-approves a tool *name*, so one on the egress request would
    # not mean "this domain again" — it would mean every domain the agent goes on to name.
    # The call is approved; the scope is dropped.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, egress_categories())
        run_id = (await client.post("/chat", json={"prompt": "reach pypi"})).json()["run_id"]
        run = await _await_parked(app, run_id)
        approval = run.parked_payload.requests.approvals[0]
        conv_id = run.conversation_id
        assert approval.tool_name == "code_request_egress"

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

        # The call itself went through — dropping the scope must not read as a denial.
        events = await collect_sse_events(client, run_id)
        assert "tool.completed" in [e["type"] for e in events]

        # Nothing standing, on either surface the operator or the engine reads.
        assert await app.state.approval_grants.list("operator", conv_id) == []
        assert (await client.get(f"/conversations/{conv_id}/grants")).json() == []


async def test_failed_resume_rolls_back_the_recorded_grant(monkeypatch):
    # The grant is written *before* resume (so the resumed turn's inline check sees it),
    # but a resume that can't be accepted must leave no standing auto-approval behind.
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, danger_categories())
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        run = await _await_parked(app, run_id)
        approval = run.parked_payload.requests.approvals[0]
        conv_id = run.conversation_id

        async def fail_resume(run_id, orchestrator, **kwargs):
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
        granted = await app.state.approval_grants.list("operator", conv_id)
        assert approval.tool_name not in {g.tool_name for g in granted}


async def test_approve_rejects_decision_mismatch(monkeypatch):
    _install_sensitive_tool(monkeypatch)
    async with client_app() as (client, app):
        swap_tool_catalog(app, danger_categories())
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
        swap_tool_catalog(app, danger_categories())
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
        swap_tool_catalog(app, danger_categories())
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
        swap_tool_catalog(app, danger_categories())
        run_id = (await client.post("/chat", json={"prompt": "delete it"})).json()["run_id"]
        await _await_parked(app, run_id)

        assert await app.state.runs.cancel(run_id) is True
        await _drain_terminal_notify_tasks(app)

        notifs = await _run_notifications(app, run_id)
        assert len(notifs) == 1
        assert notifs[0].resolved_at is not None
        # Cancelling never itself creates a run_completed/run_failed notification.
        assert all(n.kind == "approval_needed" for n in notifs)
