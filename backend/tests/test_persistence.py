"""Persistence: the conversation store, write-behind, and chat continuity."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from agent import build_chat_orchestrator
from core.db import init_db, make_engine
from core.vault import Vault
from runs import RunRegistry
from services.conversations import ConversationStore

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
