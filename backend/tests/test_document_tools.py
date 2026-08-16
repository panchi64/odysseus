"""The document tools: create/edit stream document.* events, targeted edits match a
unique span, and the provenance gate — a doc the agent created in *this* conversation
edits freely, while editing a foreign/library doc pauses for approval."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from agent import build_chat_orchestrator, stream_agent_run
from core.container import ServiceContainer
from core.db import init_db, make_engine
from core.vault import Vault
from runs import Run, RunRegistry, RunStatus, RunStream
from services.conversations import ConversationStore
from services.documents import DocumentStore
from tools import RunDeps, build_agent_toolsets
from tools.documents import document_state_context, document_toolset

from .test_memory import FakeEmbedder

OWNER = "operator"
CONV = "conv-1"


class _RecordingAdapter:
    """A duck-typed corpus adapter that records index/remove calls (no real corpus)."""

    def index_document(self, owner_id: str, document_id: str, body: str) -> None: ...
    def remove_document(self, owner_id: str, document_id: str) -> None: ...


async def _store() -> DocumentStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    return DocumentStore(engine, vault, _RecordingAdapter())


def _call_then_answer(tool_name: str, args: dict):
    """A model that calls one tool once, then answers with text once the call has settled
    (a return *or* a retry prompt), so a rejected edit doesn't loop forever."""

    def _settled(messages) -> bool:
        return any(
            type(part).__name__ in ("ToolReturnPart", "RetryPromptPart")
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _settled(messages):
            yield "done"
        else:
            yield {0: DeltaToolCall(name=tool_name, json_args=json.dumps(args))}

    return stream_fn


async def _drive(store: DocumentStore, conversation_id: str | None, tool_name: str, args: dict):
    agent = Agent(
        FunctionModel(stream_function=_call_then_answer(tool_name, args)),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets({"document": document_toolset()}),
        output_type=[str, DeferredToolRequests],
    )
    run = Run(id="r1", kind="chat", owner_id=OWNER, stream=RunStream())
    deps = RunDeps(
        run=run,
        owner_id=OWNER,
        conversation_id=conversation_id,
        caps=ServiceContainer.of(store),
    )
    async with agent.iter("go", deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)
        return run, agent_run.result.output


def _types(run: Run) -> list[str]:
    return [e.body.type for e in run.stream.replay()]


# --- create -----------------------------------------------------------------


async def test_create_streams_events_and_records_an_ai_version():
    store = await _store()
    run, out = await _drive(store, CONV, "document_create", {"title": "Report", "content": "# Hi"})

    types = _types(run)
    assert "document.created" in types
    assert "document.delta" in types
    assert "document.committed" in types
    assert not isinstance(out, DeferredToolRequests)  # create never gates

    # One AI-origin version was persisted in this conversation.
    docs = await store.list_by_conversation(OWNER, CONV)
    assert len(docs) == 1
    versions = await store.list_versions(OWNER, docs[0].id)
    assert versions[0].version == 1 and versions[0].origin == "ai"


# --- edit a document born in this conversation (ungated) --------------------


async def test_edit_of_a_session_document_applies_without_approval():
    store = await _store()
    doc = await store.create(OWNER, "Report", "hello world", conversation_id=CONV, origin="ai")

    run, out = await _drive(
        store,
        CONV,
        "document_edit",
        {"document_id": doc.id, "old_text": "world", "new_text": "there"},
    )

    assert not isinstance(out, DeferredToolRequests)  # its own conversation ⇒ no gate
    assert "document.committed" in _types(run)
    assert (await store.get(OWNER, doc.id)).body == "hello there"


# --- edit a foreign / library document (gated) ------------------------------


async def test_edit_of_a_foreign_document_pauses_for_approval():
    store = await _store()
    # A library document (no conversation) — the agent did not create it here.
    doc = await store.create(OWNER, "Library", "hello world")

    run, out = await _drive(
        store,
        CONV,
        "document_edit",
        {"document_id": doc.id, "old_text": "world", "new_text": "there"},
    )

    assert isinstance(out, DeferredToolRequests)
    assert any(c.tool_name == "document_edit" for c in out.approvals)
    assert "tool.completed" not in _types(run)  # deferred before running
    assert "document.committed" not in _types(run)
    assert (await store.get(OWNER, doc.id)).body == "hello world"  # unchanged


# --- targeted edit must identify a unique span ------------------------------


async def test_edit_rejects_a_span_that_is_not_unique():
    store = await _store()
    doc = await store.create(OWNER, "Report", "la la la", conversation_id=CONV, origin="ai")

    run, _out = await _drive(
        store, CONV, "document_edit", {"document_id": doc.id, "old_text": "la", "new_text": "LA"}
    )

    # The ambiguous span was rejected (ModelRetry) — nothing committed, body untouched.
    assert "document.committed" not in _types(run)
    assert (await store.get(OWNER, doc.id)).body == "la la la"


async def test_edit_rejects_a_span_that_is_absent():
    store = await _store()
    doc = await store.create(OWNER, "Report", "hello", conversation_id=CONV, origin="ai")

    run, _out = await _drive(
        store, CONV, "document_edit", {"document_id": doc.id, "old_text": "zzz", "new_text": "!"}
    )
    assert "document.committed" not in _types(run)
    assert (await store.get(OWNER, doc.id)).body == "hello"


# --- suggest: propose without applying (DOC-3) ------------------------------


async def test_suggest_records_pending_changes_without_touching_the_document():
    store = await _store()
    doc = await store.create(
        OWNER, "Report", "alpha\nbeta\ngamma\n", conversation_id=CONV, origin="ai"
    )

    run, out = await _drive(
        store,
        CONV,
        "document_suggest",
        {
            "document_id": doc.id,
            "summary": "two tweaks",
            "changes": [
                {"old_text": "alpha", "new_text": "ALPHA", "explanation": "louder"},
                {"old_text": "gamma", "new_text": "GAMMA"},
            ],
        },
    )

    assert not isinstance(out, DeferredToolRequests)  # its own conversation ⇒ no gate
    types = _types(run)
    # Streamed as produced, but never committed — a version exists only once accepted.
    assert types.count("document.delta") == 3  # two proposals + settling back on truth
    assert "document.committed" not in types

    assert (await store.get(OWNER, doc.id)).body == "alpha\nbeta\ngamma\n"
    assert [v.version for v in await store.list_versions(OWNER, doc.id)] == [1]

    sets = await store.suggestions.list_for_document(OWNER, doc.id)
    assert len(sets) == 1 and sets[0].pending == 2
    assert sets[0].summary == "two tweaks"
    assert sets[0].conversation_id == CONV
    assert sets[0].changes[0].explanation == "louder"


async def test_suggest_streams_a_preview_then_settles_back_on_the_real_body():
    store = await _store()
    doc = await store.create(OWNER, "Report", "one two", conversation_id=CONV, origin="ai")

    run, _out = await _drive(
        store,
        CONV,
        "document_suggest",
        {
            "document_id": doc.id,
            "changes": [
                {"old_text": "one", "new_text": "1"},
                {"old_text": "two", "new_text": "2"},
            ],
        },
    )

    bodies = [e.body.text for e in run.stream.replay() if e.body.type == "document.delta"]
    # The proposal builds up in the View, then the last delta restores what the document
    # actually says — nothing was applied.
    assert bodies == ["1 two", "1 2", "one two"]


async def test_suggest_on_a_foreign_document_pauses_for_approval():
    store = await _store()
    doc = await store.create(OWNER, "Library", "hello world")

    run, out = await _drive(
        store,
        CONV,
        "document_suggest",
        {"document_id": doc.id, "changes": [{"old_text": "world", "new_text": "there"}]},
    )

    assert isinstance(out, DeferredToolRequests)
    assert any(c.tool_name == "document_suggest" for c in out.approvals)
    assert "document.delta" not in _types(run)
    assert await store.suggestions.list_for_document(OWNER, doc.id) == []


async def test_suggest_refuses_the_whole_set_when_one_span_is_ambiguous():
    store = await _store()
    doc = await store.create(OWNER, "Report", "la la la", conversation_id=CONV, origin="ai")

    run, _out = await _drive(
        store,
        CONV,
        "document_suggest",
        {
            "document_id": doc.id,
            "changes": [
                {"old_text": "la la la", "new_text": "LA LA LA"},
                {"old_text": "la", "new_text": "LA"},
            ],
        },
    )

    assert "document.delta" not in _types(run)
    assert await store.suggestions.list_for_document(OWNER, doc.id) == []
    assert (await store.get(OWNER, doc.id)).body == "la la la"


# --- next-turn context injection --------------------------------------------


async def test_operator_edited_document_is_injected_next_turn():
    store = await _store()
    doc = await store.create(OWNER, "Draft", "v1 body", conversation_id=CONV, origin="ai")
    # The operator edits it (a user-origin version) — so it should be fed back to the model.
    await store.edit(OWNER, doc.id, body="operator's text", origin="user")

    text = await document_state_context(ServiceContainer.of(store), OWNER, CONV)
    assert "Draft" in text and "operator's text" in text


async def test_agent_authored_document_is_not_reinjected():
    store = await _store()
    # Latest version is the agent's own work (no operator edit) ⇒ the model already knows it.
    await store.create(OWNER, "Draft", "the agent wrote this", conversation_id=CONV, origin="ai")

    assert await document_state_context(ServiceContainer.of(store), OWNER, CONV) == ""


async def test_document_state_reaches_the_model_as_a_tail_prompt_part():
    # End-to-end through the real orchestrator: the operator's current doc is appended at
    # the *tail* of the current turn's user prompt — NOT the instructions block at the
    # head of the request, where its churn would invalidate the inference engine's cached
    # prompt prefix for the entire history — and the persisted history carries only the
    # typed prompt (re-resolved fresh each turn, exactly one copy in context).
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    vault = Vault(Path(tempfile.mkdtemp()) / "keyfile.json")
    await vault.setup("pw")
    store = DocumentStore(engine, vault, _RecordingAdapter())
    conv = ConversationStore(engine, vault, FakeEmbedder())
    await conv.start()
    cid = await conv.create_conversation(OWNER)

    doc = await store.create(OWNER, "Draft", "v1", conversation_id=cid, origin="ai")
    await store.edit(OWNER, doc.id, body="operator's latest text", origin="user")

    seen: dict[str, object] = {}

    async def capture(messages, info: AgentInfo):
        user = next(p for p in messages[-1].parts if isinstance(p, UserPromptPart))
        seen["content"] = user.content
        seen["instructions"] = messages[-1].instructions
        yield "ok"

    orch = build_chat_orchestrator(
        "hello",
        model=FunctionModel(stream_function=capture),
        capabilities=ServiceContainer.of(store),
        prompt_context_providers=(document_state_context,),
        store=conv,
        conversation_id=cid,
    )
    run = RunRegistry().submit(kind="chat", owner_id=OWNER, orchestrator=orch)
    await run.wait()
    assert run.status is RunStatus.done

    # The model saw the doc at the tail of the user prompt — never in the instructions.
    content = seen["content"]
    assert isinstance(content, list) and content[0] == "hello"
    assert "operator's latest text" in content[-1]
    assert "operator's latest text" not in (seen["instructions"] or "")

    # The persisted history carries only the typed prompt — the context never compounds,
    # and the durable history stays a byte-stable prefix for the next request.
    history = await conv.history(cid)
    user = next(p for p in history[0].parts if isinstance(p, UserPromptPart))
    assert user.content == "hello"
    await conv.stop()


def test_with_tail_context_rewrites_only_the_trailing_request_and_never_mutates():
    # The regenerate path: no fresh prompt, so the doc context rides on the trailing user
    # request — in the model's view only. The originals are shared with the store's
    # in-memory tree, so the helper must rebuild, never mutate.
    from pydantic_ai import ModelRequest, ModelResponse, TextPart

    from agent.engine import _with_tail_context

    history = [
        ModelRequest(parts=[UserPromptPart(content="earlier")]),
        ModelResponse(parts=[TextPart("answer")]),
        ModelRequest(parts=[UserPromptPart(content="redo this")]),
    ]
    out = _with_tail_context(history, ["[doc context]"])

    assert out[-1].parts[0].content == ["redo this", "[doc context]"]
    assert history[-1].parts[0].content == "redo this"  # shared original untouched
    assert out[:-1] == history[:-1]  # everything before the tail is the same objects

    # A history ending in a model response (defensive) passes through unchanged.
    trailing_response = history[:2]
    assert _with_tail_context(trailing_response, ["ctx"]) == trailing_response


async def test_injection_ignores_other_conversations_and_archived_docs():
    store = await _store()
    other = await store.create(OWNER, "Elsewhere", "x", conversation_id="conv-other", origin="user")
    archived = await store.create(OWNER, "Gone", "y", conversation_id=CONV, origin="user")
    await store.archive(OWNER, archived.id)
    assert other  # created in another thread — must not leak into CONV's context

    assert await document_state_context(ServiceContainer.of(store), OWNER, CONV) == ""
