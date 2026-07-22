"""The /research REST surface: the pre-run clarify/plan exchange (intake/refine), the
skip/start-now affordance, submitting a run and persisting its terminal report/stats,
research-linked notifications, "continue in chat" (+ its idempotency), delete guards,
auth, and the camelCase wire shape.

The two pre-run agent calls (`_judge_clarification`/`_produce_plan`) are monkeypatched
directly — deterministic control over the clarify-vs-plan branch without depending on a
`TestModel`'s auto-generated structured output. `run_research` itself is monkeypatched to
a fast fake so `start` is exercised end-to-end (Run submission, terminal persistence,
notifications) without a real search/fetch/model round trip.

Waiting for a started run to reach terminal never polls-with-a-timeout: it directly
awaits the Run's own task (`app.state.runs`) and then every in-flight run-terminal
background task (the finalize task that persists the report/stats/status, and the
notification surface's own notify task — both ride the same shared
`run_terminal_tasks` bucket), so these tests are deterministic regardless of host load.
"""

from __future__ import annotations

import asyncio

from core.config import get_settings
from research import ResearchPlan, ResearchResult, SearchUnavailableError
from routes.deps import OPERATOR_ID
from routes.research import ClarifyVerdict

from ._helpers import client_app, patch_model_resolution


def _install_needs_clarification(monkeypatch, questions: list[str]) -> None:
    async def judge(model, settings, *, question, context):
        return ClarifyVerdict(needs_clarification=True, questions=questions)

    monkeypatch.setattr("routes.research._judge_clarification", judge)


def _install_clear_plan(
    monkeypatch, *, objective: str = "Answer the question", angles=None, notes=None
) -> None:
    async def judge(model, settings, *, question, context):
        return ClarifyVerdict(needs_clarification=False)

    async def plan(model, settings, *, question, context):
        return ResearchPlan(
            objective=objective, angles=angles or ["angle one", "angle two"], notes=notes
        )

    monkeypatch.setattr("routes.research._judge_clarification", judge)
    monkeypatch.setattr("routes.research._produce_plan", plan)


def _fail_if_judge_called(monkeypatch) -> None:
    async def judge(model, settings, *, question, context):
        raise AssertionError("the clarify judge must not be consulted on a forced plan")

    monkeypatch.setattr("routes.research._judge_clarification", judge)


async def _drain_terminal_tasks(app) -> None:
    """Await every in-flight run-terminal background task — both the notification
    surface's own notify task and research's finalize task ride the same shared
    `run_terminal_tasks` bucket (`routes/deps.py`'s `run_terminal_tasks`)."""
    pending = list(app.state.run_terminal_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _await_status(client, app, research_id: str, status: str) -> dict:
    """Wait for a started research run to settle, deterministically: await the Run's
    own task, then drain every in-flight terminal background task (research's finalize
    task included), then read back the now-settled state. No polling, no timeout guess."""
    body = (await client.get(f"/research/{research_id}")).json()
    run_id = body["runId"]
    if run_id is not None:
        run = app.state.runs.get(run_id)
        if run is not None:
            await run.wait()
    await _drain_terminal_tasks(app)
    body = (await client.get(f"/research/{research_id}")).json()
    assert body["status"] == status, f"expected status {status!r}, got {body['status']!r}"
    return body


async def _intake(client, question: str = "what should I research?") -> dict:
    resp = await client.post("/research/intake", json={"question": question})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _intake_with_plan(client, monkeypatch) -> dict:
    """A draft research entry that already has a plan (clarify skipped)."""
    _install_clear_plan(monkeypatch)
    return await _intake(client)


# --- intake --------------------------------------------------------------------------


async def test_intake_underspecified_returns_clarifying_questions(monkeypatch):
    patch_model_resolution(monkeypatch)
    _install_needs_clarification(monkeypatch, ["Which region?", "What time frame?"])
    async with client_app() as (client, _app):
        created = await _intake(client, question="what car should I buy")
        assert created["status"] == "draft"
        assert created["clarifyingQuestions"] == ["Which region?", "What time frame?"]
        assert created["plan"] is None
        assert created["report"] is None
        assert created["runId"] is None


async def test_intake_clear_question_returns_plan_directly(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)
        assert created["status"] == "draft"
        assert created["clarifyingQuestions"] is None
        assert created["plan"] == {
            "objective": "Answer the question",
            "angles": ["angle one", "angle two"],
            "notes": None,
        }


async def test_intake_rejects_empty_question(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        resp = await client.post("/research/intake", json={"question": "   "})
        assert resp.status_code == 422


def _break_background_resolution(monkeypatch, exc: Exception) -> None:
    """Make the background (utility→main) resolution the intake path hits first fail
    with ``exc`` — a stand-in for a misconfigured registry (no model bound, or a
    stale/deleted endpoint id)."""
    from services.registry import ModelRegistry

    async def resolve_background(self, **kwargs):
        raise exc

    monkeypatch.setattr(ModelRegistry, "resolve_background", resolve_background)


async def test_intake_maps_degraded_registry_to_503(monkeypatch):
    from core.exceptions import DegradedCapabilityError

    patch_model_resolution(monkeypatch)
    _break_background_resolution(
        monkeypatch,
        DegradedCapabilityError("endpoint 'LM Studio' has no model configured"),
    )
    async with client_app() as (client, _app):
        resp = await client.post("/research/intake", json={"question": "what to research"})
        assert resp.status_code == 503, resp.text
        assert "LM Studio" in resp.json()["detail"]


async def test_intake_maps_stale_endpoint_id_to_404(monkeypatch):
    from core.exceptions import NotFoundError

    patch_model_resolution(monkeypatch)
    _break_background_resolution(monkeypatch, NotFoundError("endpoint 'abc' not found"))
    async with client_app() as (client, _app):
        resp = await client.post("/research/intake", json={"question": "what to research"})
        assert resp.status_code == 404, resp.text


# --- refine ----------------------------------------------------------------------------


async def test_refine_with_answers_produces_a_plan(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        _install_needs_clarification(monkeypatch, ["Which region?"])
        created = await _intake(client)

        _install_clear_plan(monkeypatch, objective="Refined objective")
        refined = await client.post(
            f"/research/{created['id']}/refine", json={"answers": ["Europe"]}
        )
        assert refined.status_code == 200
        body = refined.json()
        assert body["clarifyingQuestions"] is None
        assert body["plan"]["objective"] == "Refined objective"


async def test_refine_with_feedback_revises_an_existing_plan(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        _install_clear_plan(monkeypatch, objective="Revised objective", angles=["new angle"])
        refined = await client.post(
            f"/research/{created['id']}/refine", json={"feedback": "focus more on X"}
        )
        assert refined.status_code == 200
        assert refined.json()["plan"]["objective"] == "Revised objective"
        assert refined.json()["plan"]["angles"] == ["new angle"]


async def test_refine_with_empty_body_skips_the_judge_and_forces_a_plan(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        _install_needs_clarification(monkeypatch, ["Which region?"])
        created = await _intake(client)

        _fail_if_judge_called(monkeypatch)

        async def plan(model, settings, *, question, context):
            return ResearchPlan(objective="forced plan", angles=["a"])

        monkeypatch.setattr("routes.research._produce_plan", plan)

        refined = await client.post(f"/research/{created['id']}/refine", json={})
        assert refined.status_code == 200
        assert refined.json()["plan"]["objective"] == "forced plan"
        assert refined.json()["clarifyingQuestions"] is None


async def test_refine_unknown_id_404s(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        resp = await client.post("/research/does-not-exist/refine", json={"feedback": "x"})
        assert resp.status_code == 404


async def test_refine_rejects_once_no_longer_a_draft(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def fast_run_research(plan, question, deps, emit):
            return ResearchResult(
                report="the report", rounds=1, sources=1, queries=1, duration_s=0.01, model="m"
            )

        monkeypatch.setattr("routes.research.run_research", fast_run_research)
        started = await client.post(f"/research/{created['id']}/start")
        assert started.status_code == 200
        await _await_status(client, app, created["id"], "done")

        refined = await client.post(f"/research/{created['id']}/refine", json={"feedback": "x"})
        assert refined.status_code == 409


# --- start: requires a plan, submits a run, persists terminal outcome ------------------


async def test_start_requires_a_plan(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        _install_needs_clarification(monkeypatch, ["Which region?"])
        created = await _intake(client)
        resp = await client.post(f"/research/{created['id']}/start")
        assert resp.status_code == 422


async def test_start_unknown_id_404s(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        assert (await client.post("/research/does-not-exist/start")).status_code == 404


async def test_start_submits_a_run_and_persists_done_report_and_stats(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def fast_run_research(plan, question, deps, emit):
            assert plan.objective == "Answer the question"
            return ResearchResult(
                report="# The report\n\nAn answer.",
                rounds=2,
                sources=3,
                queries=4,
                duration_s=1.23,
                model="test-model",
            )

        monkeypatch.setattr("routes.research.run_research", fast_run_research)
        started = await client.post(f"/research/{created['id']}/start")
        assert started.status_code == 200
        assert started.json()["status"] == "running"
        assert started.json()["runId"] is not None

        done = await _await_status(client, app, created["id"], "done")
        assert done["report"] == "# The report\n\nAn answer."
        assert done["stats"] == {
            "durationS": 1.23,
            "rounds": 2,
            "sources": 3,
            "queries": 4,
            "model": "test-model",
        }
        assert done["finishedAt"] is not None

        # The lite library listing omits the report body.
        listed = (await client.get("/research")).json()["items"]
        assert listed[0]["id"] == created["id"]
        assert listed[0]["report"] is None
        assert listed[0]["status"] == "done"


async def test_start_persists_error_report_on_search_unavailable(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def failing_run_research(plan, question, deps, emit):
            raise SearchUnavailableError("search appears to be unavailable")

        monkeypatch.setattr("routes.research.run_research", failing_run_research)
        started = await client.post(f"/research/{created['id']}/start")
        assert started.status_code == 200

        errored = await _await_status(client, app, created["id"], "error")
        assert errored["report"] == "search appears to be unavailable"


async def test_concurrent_starts_submit_exactly_one_run(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)
        release_event = asyncio.Event()

        async def slow_run_research(plan, question, deps, emit):
            await release_event.wait()
            return ResearchResult(
                report="ok", rounds=1, sources=0, queries=0, duration_s=0.1, model="m"
            )

        monkeypatch.setattr("routes.research.run_research", slow_run_research)
        first, second = await asyncio.gather(
            client.post(f"/research/{created['id']}/start"),
            client.post(f"/research/{created['id']}/start"),
        )
        # Exactly one start wins; the loser is refused before it can resolve models
        # or submit a duplicate Run — and exactly one Run exists in the registry.
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        research_runs = [r for r in app.state.runs.list(OPERATOR_ID) if r.kind == "research"]
        assert len(research_runs) == 1

        release_event.set()
        done = await _await_status(client, app, created["id"], "done")
        assert done["runId"] == research_runs[0].id


async def test_wall_clock_blocked_run_persists_the_timeout_detail(monkeypatch):
    """A run stopped by the substrate's wall-clock bound is `blocked` via
    `run.block(detail)` — the reason lands on `run.detail`, not `run.error` — and the
    persisted report must carry that real, operator-legible sentence, not the
    unknown-reason fallback."""
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        # Shrink the Run's wall-clock backstop to ~50ms so the registry blocks the
        # run without waiting out the real operator-configured limit.
        base = get_settings().model_copy(update={"research_time_limit_s": 0.05})
        monkeypatch.setattr("routes.research.get_settings", lambda: base)
        monkeypatch.setattr("routes.research._WALL_CLOCK_BUFFER_S", 0.0)

        async def never_finishes(plan, question, deps, emit):
            await asyncio.Event().wait()

        monkeypatch.setattr("routes.research.run_research", never_finishes)
        started = await client.post(f"/research/{created['id']}/start")
        assert started.status_code == 200

        errored = await _await_status(client, app, created["id"], "error")
        run = app.state.runs.get(errored["runId"])
        assert run.detail is not None and "overall limit" in run.detail
        assert errored["report"] == run.detail


# --- notifications: researchId on both done and error ---------------------------------


async def test_done_and_error_runs_both_notify_with_research_id(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        done_entry = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def ok(plan, question, deps, emit):
            return ResearchResult(
                report="ok", rounds=1, sources=0, queries=0, duration_s=0.1, model="m"
            )

        monkeypatch.setattr("routes.research.run_research", ok)
        await client.post(f"/research/{done_entry['id']}/start")
        await _await_status(client, app, done_entry["id"], "done")

        error_entry = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def fail(plan, question, deps, emit):
            raise RuntimeError("kaboom")

        monkeypatch.setattr("routes.research.run_research", fail)
        await client.post(f"/research/{error_entry['id']}/start")
        await _await_status(client, app, error_entry["id"], "error")

        items, _ = await app.state.notifications.list_notifications(OPERATOR_ID, limit=100)
        completed = next(
            n for n in items if n.kind == "run_completed" and n.research_id == done_entry["id"]
        )
        assert completed.research_id == done_entry["id"]
        failed = next(
            n for n in items if n.kind == "run_failed" and n.research_id == error_entry["id"]
        )
        assert failed.body == "kaboom"


# --- continue in chat: seeds + idempotent ----------------------------------------------


async def test_continue_requires_a_done_report(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)
        resp = await client.post(f"/research/{created['id']}/continue")
        assert resp.status_code == 409


async def test_continue_seeds_a_conversation_with_the_report_and_is_idempotent(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def ok(plan, question, deps, emit):
            return ResearchResult(
                report="the finished report", rounds=1, sources=1, queries=1,
                duration_s=0.1, model="m",
            )

        monkeypatch.setattr("routes.research.run_research", ok)
        await client.post(f"/research/{created['id']}/start")
        await _await_status(client, app, created["id"], "done")

        first = await client.post(f"/research/{created['id']}/continue")
        assert first.status_code == 200
        conversation_id = first.json()["conversationId"]

        history = await app.state.conversations.history(conversation_id)
        rendered = " ".join(
            part.content
            for message in history
            for part in message.parts
            if hasattr(part, "content") and isinstance(part.content, str)
        )
        assert "the finished report" in rendered

        second = await client.post(f"/research/{created['id']}/continue")
        assert second.status_code == 200
        assert second.json()["conversationId"] == conversation_id


async def test_continue_seeds_the_report_wrapped_as_untrusted_history(monkeypatch):
    # The seeded report becomes the assistant's own prior turn — retained, poisonable
    # context for every future turn — but it was built from web content, so it must
    # carry the same untrusted marking every other web-sourced text carries through
    # history (security-01), not read back as fully-trusted analyst output.
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)

        async def ok(plan, question, deps, emit):
            return ResearchResult(
                report="the finished report", rounds=1, sources=1, queries=1,
                duration_s=0.1, model="m",
            )

        monkeypatch.setattr("routes.research.run_research", ok)
        await client.post(f"/research/{created['id']}/start")
        await _await_status(client, app, created["id"], "done")

        resp = await client.post(f"/research/{created['id']}/continue")
        conversation_id = resp.json()["conversationId"]

        history = await app.state.conversations.history(conversation_id)
        assistant_text = next(
            part.content
            for message in history
            for part in message.parts
            if hasattr(part, "content")
            and isinstance(part.content, str)
            and "the finished report" in part.content
        )
        assert "BEGIN UNTRUSTED CONTENT" in assistant_text
        assert "END UNTRUSTED CONTENT" in assistant_text
        assert "the finished report" in assistant_text


# --- delete: guarded while running, 404 unknown -----------------------------------------


async def test_delete_unknown_id_404s(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, _app):
        assert (await client.delete("/research/does-not-exist")).status_code == 404


async def test_delete_draft_succeeds_and_delete_while_running_is_refused(monkeypatch):
    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        _install_needs_clarification(monkeypatch, ["Which region?"])
        draft = await _intake(client)
        assert (await client.delete(f"/research/{draft['id']}")).status_code == 204
        assert (await client.get(f"/research/{draft['id']}")).status_code == 404

        created = await _intake_with_plan(monkeypatch=monkeypatch, client=client)
        started_event = asyncio.Event()
        release_event = asyncio.Event()

        async def slow_run_research(plan, question, deps, emit):
            started_event.set()
            await release_event.wait()
            return ResearchResult(
                report="ok", rounds=1, sources=0, queries=0, duration_s=0.1, model="m"
            )

        monkeypatch.setattr("routes.research.run_research", slow_run_research)
        await client.post(f"/research/{created['id']}/start")
        await started_event.wait()

        assert (await client.delete(f"/research/{created['id']}")).status_code == 409

        release_event.set()
        await _await_status(client, app, created["id"], "done")
        assert (await client.delete(f"/research/{created['id']}")).status_code == 204


# --- auth: exactly the same posture as every other feature surface --------------------


async def test_research_routes_require_auth():
    async with client_app(auth_enabled=True, passphrase=None) as (client, _app):
        setup = await client.post("/setup", json={"password": "correct horse battery staple"})
        assert setup.status_code == 200

        client.cookies.clear()
        assert (await client.get("/research")).status_code == 401
        assert (await client.post("/research/intake", json={"question": "x"})).status_code == 401
        assert (await client.post("/research/abc/refine", json={})).status_code == 401
        assert (await client.post("/research/abc/start")).status_code == 401
        assert (await client.post("/research/abc/continue")).status_code == 401
        assert (await client.delete("/research/abc")).status_code == 401
