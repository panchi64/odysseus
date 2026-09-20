"""The attribution surface — the wire shape the panel reads, and the retroactive path.

The retroactive path is the one worth a route test of its own. It is what makes the
decision behind this feature affordable: the Sources panel did not have to wait for the
extraction to ship, because a thread finished before the pass existed can be read at any
time from its stored tool results. So these seed a research thread *with no attribution
at all*, ask for one, and check that a reading appears — which only works if the source
inventory really does survive the trip through the database.
"""

from __future__ import annotations

from pydantic_ai import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from services.registry import ModelRegistry

from ._helpers import client_app, collect_sse_events, patch_model_resolution, stub_resolution

ANSWER = "The reactor was cold. The budget doubled in 2024."
PAGE = "https://a.example"


def _reading(claims: list[dict]):
    """Point every background resolution at a reader that answers with ``claims``."""

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if info.output_tools:
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"claims": claims})]
            )
        return ModelResponse(parts=[TextPart("ok")])  # pragma: no cover — titling only

    return FunctionModel(respond)


def _patch_background(monkeypatch, model) -> None:
    async def resolve_detailed(self, role, **kwargs):
        return await stub_resolution(self, model)

    monkeypatch.setattr(ModelRegistry, "resolve_detailed", resolve_detailed)


def _researched_turn() -> list:
    """One assistant turn that fetched a page and wrote an answer off it — the shape a
    real research turn persists as, tool result and all."""
    return [
        ModelRequest(parts=[UserPromptPart("what happened at the reactor?")]),
        ModelResponse(parts=[ToolCallPart("web_fetch", {"url": PAGE}, tool_call_id="c1")]),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="web_fetch",
                    content={
                        "url": PAGE,
                        "title": "A page",
                        "content": "the reactor was cold all winter",
                    },
                    tool_call_id="c1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(ANSWER)]),
    ]


async def _research_thread(client, app) -> str:
    """A research conversation whose latest turn read a page, persisted and settled."""
    resp = await client.post("/chat", json={"prompt": "hello", "mode": "research"})
    body = resp.json()
    await collect_sse_events(client, body["run_id"])
    conversation_id = body["conversation_id"]
    store = app.state.conversations
    store.record(conversation_id, _researched_turn())
    await store._worker.join()
    return conversation_id


async def test_a_thread_with_no_reading_serves_an_empty_list(monkeypatch):
    """Absent, never an error and never a blank panel — the ordinary state of every
    thread that predates the pass and of every non-research thread forever."""
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _research_thread(client, app)
        resp = await client.get(f"/conversations/{conversation_id}/attributions")
        assert resp.status_code == 200
        assert resp.json() == {"conversation_id": conversation_id, "messages": []}


async def test_the_retroactive_path_reads_a_turn_that_finished_before_the_pass(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _research_thread(client, app)
        # The turn above was recorded straight into the store, so nothing ever ran the
        # live pass over it — exactly the position every thread in the database was in
        # the day this landed.
        assert (await client.get(f"/conversations/{conversation_id}/attributions")).json()[
            "messages"
        ] == []

        _patch_background(
            monkeypatch,
            _reading(
                [
                    {
                        "claim": "The reactor was cold.",
                        "source_key": PAGE,
                        "passage": "the reactor was cold all winter",
                        "confidence": "high",
                        "offset": 0,
                    },
                    {
                        "claim": "The budget doubled in 2024.",
                        "source_key": PAGE,
                        "passage": "",
                        "confidence": "low",
                    },
                ]
            ),
        )
        resp = await client.post(f"/conversations/{conversation_id}/attributions", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == conversation_id
        [row] = body["messages"]
        assert row["extracted_at"]

        grounded, ungrounded = row["claims"]
        assert grounded == {
            "claim": "The reactor was cold.",
            "grounded": True,
            "source_key": PAGE,
            "source_title": "A page",
            "source_url": PAGE,
            "source_kind": "web",
            "passage": "the reactor was cold all winter",
            "confidence": "high",
            "offset": 0,
        }
        # The row the whole feature exists to produce: the answer named a page and the
        # page does not say this. It keeps its source and it is not hidden.
        assert ungrounded["grounded"] is False
        assert ungrounded["source_key"] == PAGE
        assert ungrounded["passage"] is None

        # And it survives the reload, which is what a panel opening the thread reads.
        again = (await client.get(f"/conversations/{conversation_id}/attributions")).json()
        assert again == body


async def test_the_reading_joins_onto_the_turn_the_detail_route_already_numbers(monkeypatch):
    """``message_id`` is the branch node, so the client needs no second identity."""
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _research_thread(client, app)
        _patch_background(
            monkeypatch,
            _reading([{"claim": "The reactor was cold.", "source_key": PAGE, "passage": "p"}]),
        )
        body = (
            await client.post(f"/conversations/{conversation_id}/attributions", json={})
        ).json()
        detail = (await client.get(f"/conversations/{conversation_id}")).json()
        assistant_ids = [m["id"] for m in detail["messages"] if m["role"] == "assistant"]
        assert body["messages"][0]["message_id"] in assistant_ids


async def test_a_non_research_thread_stores_nothing_when_asked(monkeypatch):
    """The route runs the same trigger the engine runs, so asking for a reading on a
    thread whose mode does not want one is a no-op rather than a way around it."""
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        resp = await client.post("/chat", json={"prompt": "hello"})
        body = resp.json()
        await collect_sse_events(client, body["run_id"])
        conversation_id = body["conversation_id"]
        app.state.conversations.record(conversation_id, _researched_turn())
        await app.state.conversations._worker.join()

        def explode(messages, info: AgentInfo):  # pragma: no cover — must not run
            raise AssertionError("the extraction model was called on a normal thread")

        _patch_background(monkeypatch, FunctionModel(explode))
        out = (
            await client.post(f"/conversations/{conversation_id}/attributions", json={})
        ).json()
        assert out["messages"] == []


async def test_an_unknown_turn_is_a_404(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _research_thread(client, app)
        resp = await client.post(
            f"/conversations/{conversation_id}/attributions", json={"message_id": "nope"}
        )
        assert resp.status_code == 404


async def test_an_unknown_conversation_is_a_404(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, _app):
        assert (await client.get("/conversations/nope/attributions")).status_code == 404
        assert (await client.post("/conversations/nope/attributions", json={})).status_code == 404


async def test_the_live_pass_hangs_in_the_post_answer_window(monkeypatch):
    """The engine reaches the pass with the turn already recorded — which is what makes
    the id it stores under the same branch node the retroactive path will use.

    The pass itself is exercised directly in ``test_attribution.py``; what this pins is
    the one thing only a real run can show: that the engine gets there at all, after
    ``finalize``, with the thread's mode and the app's own store in hand.
    """
    import agent.engine as engine

    seen: list[dict] = []
    real = engine.attribute_answer

    async def recording(run, **kwargs):
        seen.append(kwargs)
        return await real(run, **kwargs)

    monkeypatch.setattr(engine, "attribute_answer", recording)
    patch_model_resolution(monkeypatch, output_text="an answer")
    async with client_app() as (client, app):
        resp = await client.post("/chat", json={"prompt": "hello", "mode": "research"})
        body = resp.json()
        await collect_sse_events(client, body["run_id"])
        conversation_id = body["conversation_id"]

        [call] = seen
        assert call["mode"] == "research"
        assert call["owner_id"] == "operator"
        assert call["attributions"] is app.state.attributions
        detail = (await client.get(f"/conversations/{conversation_id}")).json()
        assert call["message_id"] in [
            m["id"] for m in detail["messages"] if m["role"] == "assistant"
        ]


async def test_deleting_the_thread_takes_the_reading_with_it(monkeypatch):
    patch_model_resolution(monkeypatch, output_text="hi")
    async with client_app() as (client, app):
        conversation_id = await _research_thread(client, app)
        _patch_background(
            monkeypatch,
            _reading([{"claim": "The reactor was cold.", "source_key": PAGE, "passage": "p"}]),
        )
        await client.post(f"/conversations/{conversation_id}/attributions", json={})
        assert (
            await app.state.attributions.for_conversation("operator", conversation_id)
        ) != []
        assert (await client.delete(f"/conversations/{conversation_id}")).status_code == 204
        assert (
            await app.state.attributions.for_conversation("operator", conversation_id)
        ) == []
