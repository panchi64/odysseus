"""Conversation-scoped auto-approval grants: the store, the engine's grant-driven
auto-approve, and the corpus search's conditional (global-only) gating."""

from __future__ import annotations

import asyncio
import json

from pydantic_ai import Agent, DeferredToolRequests, FunctionToolset
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlmodel import Session, select

from agent import build_chat_orchestrator, stream_agent_run
from core.container import ServiceContainer
from core.db import init_db, make_engine
from models.approval_grant import ApprovalGrant
from runs import Run, RunRegistry, RunStatus, RunStream
from services.approval_grants import ApprovalGrantStore, covered_by_grant
from tools import RunDeps, build_agent_toolsets
from tools.conversations import conversations_toolset
from tools.corpus import corpus_toolset
from tools.memory import memory_toolset

OWNER = "operator"
CONV = "conv-1"


def _store(ttl_s: float) -> ApprovalGrantStore:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return ApprovalGrantStore(engine, ttl_s)


# --- the grant store --------------------------------------------------------


async def test_grant_then_active_and_list():
    s = _store(3600)
    await s.grant(OWNER, CONV, "corpus_retrieve")
    assert await s.active(OWNER, CONV) == {"corpus_retrieve"}
    listed = await s.list(OWNER, CONV)
    assert [g.tool_name for g in listed] == ["corpus_retrieve"]
    # A grant is scoped to its conversation — another thread is unaffected.
    assert await s.active(OWNER, "other-conv") == set()


async def test_expired_grant_is_not_active():
    s = _store(-1)  # already lapsed the instant it's written
    await s.grant(OWNER, CONV, "corpus_retrieve")
    assert await s.active(OWNER, CONV) == set()
    assert await s.list(OWNER, CONV) == []


async def test_revoke_drops_the_grant():
    s = _store(3600)
    await s.grant(OWNER, CONV, "corpus_retrieve")
    await s.revoke(OWNER, CONV, "corpus_retrieve")
    assert await s.active(OWNER, CONV) == set()


async def test_regrant_refreshes_expiry_without_duplicating():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    short = ApprovalGrantStore(engine, 1)
    long = ApprovalGrantStore(engine, 100_000)
    first = await short.grant(OWNER, CONV, "corpus_retrieve")
    second = await long.grant(OWNER, CONV, "corpus_retrieve")  # same triple
    assert second > first  # expiry extended, not a second row
    assert len(await long.list(OWNER, CONV)) == 1


# --- the engine auto-approves a granted tool --------------------------------


def _danger_categories():
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain(requires_approval=True)
    def delete_thing(name: str) -> str:
        return f"deleted {name}"

    return {"danger": toolset}


DANGER_TOOL = "danger_delete_thing"  # namespaced category_tool name


def _types(run: Run) -> list[str]:
    return [e.body.type for e in run.stream.replay()]


def _danger_orchestrator(store: ApprovalGrantStore):
    return build_chat_orchestrator(
        "delete the thing",
        model=TestModel(custom_output_text="done"),
        categories=_danger_categories(),
        capabilities=ServiceContainer.of(store),
        conversation_id=CONV,
    )


async def test_active_grant_auto_approves_without_prompting():
    reg = RunRegistry()
    store = _store(3600)
    await store.grant(OWNER, CONV, DANGER_TOOL)

    run = reg.submit(
        kind="chat", owner_id=OWNER, orchestrator=_danger_orchestrator(store), conversation_id=CONV
    )
    await run.wait()

    assert run.status is RunStatus.done
    types = _types(run)
    assert "approval.required" not in types  # the grant covered it — no prompt
    assert "tool.completed" in types  # still executed, and visible in the transcript


async def test_without_a_grant_the_run_still_parks():
    reg = RunRegistry()
    store = _store(3600)  # empty — no grant for this conversation

    run = reg.submit(
        kind="chat", owner_id=OWNER, orchestrator=_danger_orchestrator(store), conversation_id=CONV
    )
    await run.wait()

    assert run.status is RunStatus.awaiting_input
    assert "approval.required" in _types(run)


async def test_granted_runaway_tool_still_trips_the_turn_guard():
    """A granted tool the model keeps re-calling auto-approves every hop, but the turn
    is bounded as a whole — the shared usage/no-progress guard stops it (blocked) instead
    of recursing without end (the regression the inline-resume loop guards against)."""
    reg = RunRegistry()
    store = _store(3600)
    await store.grant(OWNER, CONV, DANGER_TOOL)

    async def always_calls(messages, info):
        yield {0: DeltaToolCall(name=DANGER_TOOL, json_args=json.dumps({"name": "x"}))}

    orch = build_chat_orchestrator(
        "go",
        model=FunctionModel(stream_function=always_calls),
        categories=_danger_categories(),
        capabilities=ServiceContainer.of(store),
        conversation_id=CONV,
    )
    run = reg.submit(kind="chat", owner_id=OWNER, orchestrator=orch, conversation_id=CONV)
    await asyncio.wait_for(run.wait(), timeout=10)

    assert run.status is RunStatus.blocked
    assert "limit.notice" in _types(run)


# --- the corpus search gates only global recall -----------------------------


def _call_once(tool_name: str, args: dict):
    """A model that calls one tool once, then answers with text once it has run."""

    def _tool_ran(messages) -> bool:
        return any(
            type(part).__name__ == "ToolReturnPart"
            for message in messages
            for part in message.parts
        )

    async def stream_fn(messages, info):
        if _tool_ran(messages):
            yield "done"
        else:
            yield {0: DeltaToolCall(name=tool_name, json_args=json.dumps(args))}

    return stream_fn


def _recall_agent(categories: dict, tool_name: str, args: dict):
    """An agent that calls one recall tool once. The backing capability is left unset on
    the deps, so a gated tool defers *before* touching it and an ungated one degrades to
    an "unavailable" string — either way the gate behaviour is what's under test."""
    agent = Agent(
        FunctionModel(stream_function=_call_once(tool_name, args)),
        deps_type=RunDeps,
        toolsets=build_agent_toolsets(categories),
        output_type=[str, DeferredToolRequests],
    )
    run = Run(id="r1", kind="chat", owner_id=OWNER, stream=RunStream())
    deps = RunDeps(run=run, owner_id=OWNER, conversation_id=CONV)
    return agent, run, deps


def _corpus_agent(args: dict):
    return _recall_agent({"corpus": corpus_toolset()}, "corpus_retrieve", args)


async def _drive(agent, run, deps, prompt: str):
    async with agent.iter(prompt, deps=deps) as agent_run:
        await stream_agent_run(agent_run, run)
        return agent_run.result.output


async def test_global_corpus_search_defers_for_approval():
    agent, run, deps = _corpus_agent({"query": "cats"})  # no source_ids ⇒ global recall
    out = await _drive(agent, run, deps, "recall")
    assert isinstance(out, DeferredToolRequests)
    assert any(c.tool_name == "corpus_retrieve" for c in out.approvals)
    assert "tool.completed" not in _types(run)


async def test_empty_source_list_is_gated_like_global_recall():
    # An empty list is still a global recall (line 53 collapses it to None), so it must
    # gate — `is None` alone would let `source_ids=[]` slip an ungated full-corpus read in.
    agent, run, deps = _corpus_agent({"query": "cats", "source_ids": []})
    out = await _drive(agent, run, deps, "recall")
    assert isinstance(out, DeferredToolRequests)
    assert any(c.tool_name == "corpus_retrieve" for c in out.approvals)
    assert "tool.completed" not in _types(run)


async def test_explicit_source_read_is_not_gated():
    agent, run, deps = _corpus_agent({"query": "cats", "source_ids": ["s1"]})
    out = await _drive(agent, run, deps, "read the attached file")
    assert not isinstance(out, DeferredToolRequests)  # ran straight through, no approval
    assert "tool.completed" in _types(run)


async def test_memory_recall_defers_for_approval():
    # memory.recall reaches the same long-term-memory content the corpus gate protects, so
    # it must be gated too — otherwise it's an ungated path around AE-3.8.
    agent, run, deps = _recall_agent({"memory": memory_toolset()}, "memory_recall", {"query": "x"})
    out = await _drive(agent, run, deps, "recall")
    assert isinstance(out, DeferredToolRequests)
    assert any(c.tool_name == "memory_recall" for c in out.approvals)


async def test_conversations_search_defers_but_read_does_not():
    cats = {"conversations": conversations_toolset()}
    # search is global relevance recall across other threads ⇒ gated.
    agent, run, deps = _recall_agent(cats, "conversations_search", {"query": "x"})
    out = await _drive(agent, run, deps, "search")
    assert isinstance(out, DeferredToolRequests)
    assert any(c.tool_name == "conversations_search" for c in out.approvals)
    # read is an explicit-id read of one already-surfaced thread ⇒ ungated.
    agent, run, deps = _recall_agent(cats, "conversations_read", {"conversation_id": "c9"})
    out = await _drive(agent, run, deps, "read it")
    assert not isinstance(out, DeferredToolRequests)
    assert "tool.completed" in _types(run)


# --- the shared grant-coverage predicate + lazy prune -----------------------


def test_covered_by_grant_is_the_single_rule():
    assert covered_by_grant("corpus_retrieve", {"corpus_retrieve"}) is True
    assert covered_by_grant("memory_recall", {"corpus_retrieve"}) is False
    assert covered_by_grant(None, {"corpus_retrieve"}) is False


async def test_expired_grants_are_pruned_on_read():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    store = ApprovalGrantStore(engine, -1)  # lapsed the instant it's written
    await store.grant(OWNER, CONV, "corpus_retrieve")
    assert await store.list(OWNER, CONV) == []  # filtered out of the view
    # …and physically gone, not just hidden — the table can't grow without bound.
    with Session(engine) as session:
        assert session.exec(select(ApprovalGrant)).all() == []


async def test_concurrent_grants_do_not_duplicate_or_error():
    # Two approvals of the same tool racing into grant() must converge on one row via the
    # DB upsert, not raise a duplicate-insert IntegrityError.
    s = _store(3600)
    await asyncio.gather(*(s.grant(OWNER, CONV, "corpus_retrieve") for _ in range(5)))
    assert len(await s.list(OWNER, CONV)) == 1
