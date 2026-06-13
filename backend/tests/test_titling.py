"""Auto-titling: the chassis names a fresh conversation from its first exchange."""

from __future__ import annotations

import pytest
from pydantic_ai import FunctionToolset, ToolApproved
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

import agent.engine as engine
from agent import build_chat_orchestrator, build_resume_orchestrator
from agent.title import _clean, first_user_text, generate_title
from core.config import Settings
from core.db import init_db, make_engine
from core.vault import Vault
from runs import RunRegistry, RunStatus
from services.conversations import ConversationStore
from tools import RunDeps


async def _unlocked_vault(tmp_path) -> Vault:
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    return vault


async def _fresh_store(tmp_path) -> ConversationStore:
    engine_ = make_engine("sqlite:///:memory:")
    init_db(engine_)
    store = ConversationStore(engine_, await _unlocked_vault(tmp_path))
    await store.start()
    return store


def _bodies(run):
    return [e.body for e in run.stream.replay()]


# --- sanitization -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('"Trip Planning to Japan"', "Trip Planning to Japan"),
        ("Title: Debugging a Race Condition", "Debugging a Race Condition"),
        ("Resetting the Vault Password.", "Resetting the Vault Password"),
        ("  Multi\nLine\nReply  ", "Multi"),
        ("`Quoted Backticks`", "Quoted Backticks"),
        ("   ", None),
    ],
)
def test_clean_sanitizes_model_replies(raw, expected):
    assert _clean(raw) == expected


def test_clean_caps_length():
    title = _clean("A " * 100)
    assert title is not None and len(title) <= 60


# --- generation -------------------------------------------------------------


async def test_generate_title_returns_clean_title():
    model = TestModel(custom_output_text='"Configuring the Model Registry"')
    title = await generate_title(model, "how do I set up endpoints?")
    assert title == "Configuring the Model Registry"


async def test_generate_title_merges_reasoning_off_without_error():
    # The reasoning-off settings (from services.reasoning) are merged over the base
    # caps and passed through; a TestModel ignores them but the call still works.
    model = TestModel(custom_output_text="A Title")
    title = await generate_title(
        model,
        "q",
        reasoning_off={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
    )
    assert title == "A Title"


# --- engine wiring ----------------------------------------------------------


async def test_first_turn_emits_and_persists_title(tmp_path):
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator")  # untitled
    reg = RunRegistry()

    orch = build_chat_orchestrator(
        "plan a trip to Japan",
        model=TestModel(custom_output_text="Sure, here is a plan."),
        title_model=TestModel(custom_output_text="Japan Trip Plan"),
        categories={},
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    titled = [b for b in _bodies(run) if b.type == "conversation.titled"]
    assert len(titled) == 1
    assert titled[0].conversation_id == conv
    assert titled[0].title == "Japan Trip Plan"

    # Emitted before the run ends, so a still-open stream carries it.
    types = [b.type for b in _bodies(run)]
    assert types.index("conversation.titled") < types.index("run.ended")

    # And it was persisted, not just announced.
    summary = await store.get_summary(conv, "operator")
    assert summary is not None and summary.title == "Japan Trip Plan"
    await store.stop()


async def test_continued_turn_is_not_retitled(tmp_path):
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator")
    reg = RunRegistry()

    def run_turn(prompt: str):
        orch = build_chat_orchestrator(
            prompt,
            model=TestModel(custom_output_text="ok"),
            title_model=TestModel(custom_output_text="Some Title"),
            categories={},
            store=store,
            conversation_id=conv,
        )
        return reg.submit(kind="chat", owner_id="operator", orchestrator=orch)

    first = run_turn("first message")
    await first.wait()
    second = run_turn("second message")
    await second.wait()

    # Only the opening turn names the thread; the continuation does not re-title.
    assert any(b.type == "conversation.titled" for b in _bodies(first))
    assert not any(b.type == "conversation.titled" for b in _bodies(second))
    await store.stop()


async def test_existing_operator_title_is_never_clobbered(tmp_path):
    # A thread the operator already named must not be auto-renamed even on its
    # first turn — set_title_if_absent is the authoritative guard.
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator", title="My Own Name")
    reg = RunRegistry()

    orch = build_chat_orchestrator(
        "hello",
        model=TestModel(custom_output_text="hi"),
        title_model=TestModel(custom_output_text="Auto Generated"),
        categories={},
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert not any(b.type == "conversation.titled" for b in _bodies(run))
    summary = await store.get_summary(conv, "operator")
    assert summary is not None and summary.title == "My Own Name"
    await store.stop()


async def test_titling_skipped_without_title_model(tmp_path):
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator")
    reg = RunRegistry()

    orch = build_chat_orchestrator(
        "hello",
        model=TestModel(custom_output_text="hi"),
        categories={},
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert not any(b.type == "conversation.titled" for b in _bodies(run))
    summary = await store.get_summary(conv, "operator")
    assert summary is not None and summary.title is None
    await store.stop()


async def test_titling_skipped_when_disabled_in_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "get_settings", lambda: Settings(title_enabled=False))
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator")
    reg = RunRegistry()

    orch = build_chat_orchestrator(
        "hello",
        model=TestModel(custom_output_text="hi"),
        title_model=TestModel(custom_output_text="Should Not Appear"),
        categories={},
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    assert not any(b.type == "conversation.titled" for b in _bodies(run))
    await store.stop()


async def test_parked_first_turn_is_titled_on_resume(tmp_path):
    # A first turn whose opening message triggers an approval-gated tool parks,
    # then resumes to completion — it must still be named (titling lives at the
    # shared finalize point, carried across the park on the parked turn).
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator")

    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True)
    def delete_thing(name: str) -> str:
        return f"deleted {name}"

    def _tool_ran(messages) -> bool:
        return any(
            type(part).__name__ == "ToolReturnPart"
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _tool_ran(messages):
            yield "Done deleting the thing."
        else:
            yield {0: DeltaToolCall(name=info.function_tools[0].name, json_args='{"name": "x"}')}

    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "please delete the thing",
        model=FunctionModel(stream_function=stream_fn),
        categories={"danger": toolset},
        title_model=TestModel(custom_output_text="Deleting The Thing"),
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    # Parked before reaching the finalize point — titling hasn't run yet.
    assert run.status is RunStatus.awaiting_input
    assert not any(b.type == "conversation.titled" for b in _bodies(run))

    parked = run.parked_payload
    call_id = parked.requests.approvals[0].tool_call_id
    await reg.resume(
        run.id, build_resume_orchestrator(parked, {call_id: ToolApproved()}, store=store)
    )
    await run.wait()
    assert run.status is RunStatus.done

    # Resumed to completion → the opening exchange is named on the same stream.
    titled = [b for b in _bodies(run) if b.type == "conversation.titled"]
    assert len(titled) == 1 and titled[0].title == "Deleting The Thing"
    summary = await store.get_summary(conv, "operator")
    assert summary is not None and summary.title == "Deleting The Thing"
    await store.stop()


# --- history extraction -----------------------------------------------------


async def test_title_text_extraction_from_history(tmp_path):
    # The message the namer sees is read back from persisted history, so the
    # extraction helper must pull the first user prompt — the title is named for
    # what the operator asked, not the assistant's reply.
    store = await _fresh_store(tmp_path)
    conv = await store.create_conversation("operator")
    reg = RunRegistry()
    orch = build_chat_orchestrator(
        "what is the capital of France?",
        model=TestModel(custom_output_text="Paris is the capital."),
        categories={},
        store=store,
        conversation_id=conv,
    )
    run = reg.submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()

    history = await store.history(conv)
    assert "capital of France" in first_user_text(history)
    await store.stop()
