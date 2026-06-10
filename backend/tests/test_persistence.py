"""Persistence: the conversation store, write-behind, and chat continuity."""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ToolApproved
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

import agent.engine as engine
from agent import ParkedTurn, build_chat_orchestrator, build_resume_orchestrator
from agent.meta import Verdict
from core.config import Settings
from core.db import init_db, make_engine
from core.vault import Vault
from runs import RunRegistry, RunStatus
from services.conversations import ConversationStore, _project
from tools import RunDeps

from ._helpers import client_app, collect_sse_events


async def _unlocked_vault(tmp_path, name: str = "keyfile.json") -> Vault:
    vault = Vault(tmp_path / name)
    if not vault.is_initialized:
        await vault.setup("pw")
    else:
        await vault.unlock("pw")
    return vault


async def _fresh_store(tmp_path) -> tuple[ConversationStore, object]:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return ConversationStore(engine, await _unlocked_vault(tmp_path)), engine


async def test_store_records_and_rehydrates_from_db(tmp_path):
    store, engine = await _fresh_store(tmp_path)
    await store.start()
    conv = await store.create_conversation("operator", title="t")

    reg = RunRegistry()

    async def run_turn(text: str):
        orch = build_chat_orchestrator(
            text,
            model=TestModel(custom_output_text=f"re:{text}"),
            categories={},  # no tools → 2 messages per turn
            store=store,
            conversation_id=conv,
        )
        run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
        await run.wait()

    await run_turn("hello")
    await run_turn("again")

    # The live working set reflects both turns immediately (no DB read).
    assert len(await store.history(conv)) == 4

    # A cold store rehydrates the same history from the durable record (it must
    # unlock the same keyfile to decrypt).
    await store.stop()
    cold = ConversationStore(engine, await _unlocked_vault(tmp_path))
    await cold.start()
    rehydrated = await cold.history(conv)
    assert [m.kind for m in rehydrated] == ["request", "response", "request", "response"]
    await cold.stop()


async def test_content_is_encrypted_at_rest(tmp_path):
    from sqlmodel import Session, select

    from models.conversation import Message

    store, engine = await _fresh_store(tmp_path)
    await store.start()
    conv = await store.create_conversation("operator")

    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "tell me the SECRET-TOKEN-XYZ",
        model=TestModel(custom_output_text="the answer is SECRET-TOKEN-XYZ"),
        categories={},
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()
    await store.stop()  # flush the write-behind queue

    # Raw rows on disk must not contain the plaintext.
    with Session(engine) as session:
        rows = session.exec(select(Message).where(Message.conversation_id == conv)).all()
    assert rows
    for row in rows:
        assert "SECRET-TOKEN-XYZ" not in row.blob
        assert "SECRET-TOKEN-XYZ" not in row.text


async def test_foreign_keys_are_enforced():
    # The Message → Conversation FK is only real if SQLite's pragma is on; an
    # orphan insert must fail loudly rather than silently land.
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import Session

    from models.conversation import Message

    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    raised = False
    with Session(engine) as session:
        session.add(
            Message(conversation_id="no-such-conv", seq=0, kind="response", text="x", blob="y")
        )
        try:
            session.commit()
        except IntegrityError:
            raised = True
    assert raised


async def test_second_turn_continues_prior_history(tmp_path):
    store, _ = await _fresh_store(tmp_path)
    await store.start()
    conv = await store.create_conversation("operator")

    reg = RunRegistry()
    seen_history_lengths = []

    # A model that records how much history it was given each turn.
    def make_model(reply: str) -> TestModel:
        return TestModel(custom_output_text=reply)

    orch1 = build_chat_orchestrator(
        "first", model=make_model("a"), categories={}, store=store, conversation_id=conv
    )
    run1 = reg.submit(kind="chat", owner_id="operator", orchestrator=orch1)
    await run1.wait()
    seen_history_lengths.append(len(await store.history(conv)))

    orch2 = build_chat_orchestrator(
        "second", model=make_model("b"), categories={}, store=store, conversation_id=conv
    )
    run2 = reg.submit(kind="chat", owner_id="operator", orchestrator=orch2)
    await run2.wait()
    seen_history_lengths.append(len(await store.history(conv)))

    assert seen_history_lengths == [2, 4]  # history grows across turns
    await store.stop()


async def test_verifier_correction_persists_clean_history(tmp_path, monkeypatch):
    # A judge-rejected answer + the synthetic nudge must NOT end up in history —
    # only the original request → corrected answer.
    monkeypatch.setattr(
        engine, "get_settings", lambda: Settings(verify_enabled=True, verify_heuristic=False)
    )
    store, _ = await _fresh_store(tmp_path)
    await store.start()
    conv = await store.create_conversation("operator")

    verdicts = [Verdict(ok=False, reason="add more detail")]

    async def judge(request, answer):
        return verdicts.pop(0) if verdicts else Verdict(ok=True)

    reg = RunRegistry()
    orch = engine.build_chat_orchestrator(
        "summarize it",
        model=TestModel(custom_output_text="the summary"),
        categories={},  # no tools → a clean 2-message turn
        judge=judge,
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()
    assert run.status is RunStatus.done

    history = await store.history(conv)
    assert [m.kind for m in history] == ["request", "response"]  # not the 4-msg transcript
    texts = [_project(m)[1] for m in history]
    assert not any("did not fully satisfy" in t for t in texts)  # nudge didn't leak
    await store.stop()


def _danger_categories():
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True)
    def delete_thing(name: str) -> str:
        return f"deleted {name}"

    return {"danger": toolset}


async def test_verify_park_persists_once_on_resume(tmp_path, monkeypatch):
    # The verifier's corrective re-attempt itself parks for approval. Nothing is
    # persisted while parked; the resume persists exactly once.
    monkeypatch.setattr(
        engine, "get_settings", lambda: Settings(verify_enabled=True, verify_heuristic=False)
    )
    store, _ = await _fresh_store(tmp_path)
    await store.start()
    conv = await store.create_conversation("operator")

    async def judge(request, answer):
        return Verdict(ok=False, reason="redo it")  # always reject → trigger a correction

    def _is_correction(messages) -> bool:
        text = " ".join(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(getattr(part, "content", None), str)
        )
        return "did not fully satisfy" in text

    def _tool_already_ran(messages) -> bool:
        return any(
            type(part).__name__ == "ToolReturnPart"
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        # First attempt: a plain text answer (no tool). The corrective re-attempt
        # calls the sensitive tool, which parks the run for approval. After the
        # approved tool runs, finish with text.
        if _tool_already_ran(messages):
            yield "all done"
        elif _is_correction(messages):
            tool_name = info.function_tools[0].name
            yield {0: DeltaToolCall(name=tool_name, json_args='{"name": "x"}')}
        else:
            yield "first answer"

    reg = RunRegistry()
    orch = engine.build_chat_orchestrator(
        "do the thing",
        model=FunctionModel(stream_function=stream_fn),
        categories=_danger_categories(),
        judge=judge,
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    # Parked by the correction — persistence context wired, nothing written yet.
    assert run.status is RunStatus.awaiting_input
    assert await store.history(conv) == []
    parked: ParkedTurn = run.parked_payload
    assert parked.conversation_id == conv
    assert parked.persist_from == 0

    call_id = parked.requests.approvals[0].tool_call_id
    await reg.resume(
        run.id, build_resume_orchestrator(parked, {call_id: ToolApproved()}, store=store)
    )
    await run.wait()
    assert run.status is RunStatus.done

    # Persisted exactly once on resume — and cleaned: the rejected "first answer"
    # and the synthetic nudge are dropped, the approved final answer is kept.
    history = await store.history(conv)
    texts = [_project(m)[1] for m in history]
    assert any("all done" in t for t in texts)
    assert not any("first answer" in t for t in texts)
    assert not any("did not fully satisfy" in t for t in texts)
    await store.stop()


async def test_chat_route_returns_conversation_and_continues(monkeypatch):
    import services.llm as llm

    def fake_resolve(role="main"):
        return TestModel(custom_output_text="hi")

    monkeypatch.setattr(llm, "resolve_model", fake_resolve)

    async with client_app() as (client, app):
        first = await client.post("/chat", json={"prompt": "hello"})
        assert first.status_code == 202
        conv_id = first.json()["conversation_id"]
        run_id = first.json()["run_id"]
        await collect_sse_events(client, run_id)

        # continue the same conversation
        second = await client.post("/chat", json={"prompt": "again", "conversation_id": conv_id})
        assert second.json()["conversation_id"] == conv_id
        await collect_sse_events(client, second.json()["run_id"])

        history = await app.state.conversations.history(conv_id)

    assert len(history) >= 4  # two turns, both persisted to the same conversation
