"""The agent's task list: sealed per-conversation persistence, and an event on every
mutation — including the bulk replace the harness's own stores leave silent.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic_ai_harness.planning import PlanItem, TaskStatus

from core.db import init_db, make_engine
from core.vault import Vault
from models.plan import ConversationPlan
from runs import PlanUpdated, Run, RunStream
from services.plans import ConversationPlans, ConversationPlanStore

OWNER = "operator"


@pytest.fixture
async def plans(tmp_path):
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("correct horse battery staple")
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return ConversationPlans(engine, vault)


def _store(plans: ConversationPlans, run: Run | None = None) -> ConversationPlanStore:
    return ConversationPlanStore(
        plans, owner_id=OWNER, conversation_id="conv-1", run=run
    )


def _items(*contents: str) -> list[PlanItem]:
    return [
        PlanItem(id=f"t{i}", content=c, status=TaskStatus.pending)
        for i, c in enumerate(contents)
    ]


def _bodies(run: Run) -> list:
    return [e.body for e in run.stream.replay()]


async def test_plan_round_trips_across_stores(plans):
    await _store(plans).set_items(_items("read the file", "fix the bug"))

    # A second store object is what a later turn (or a reload) gets — the list has to
    # come back from storage, not from anything held in memory.
    reloaded = await _store(plans).get_items()
    assert [i.content for i in reloaded] == ["read the file", "fix the bug"]


async def test_the_bulk_replace_emits_too(plans):
    run = Run(id="r", kind="chat", owner_id=OWNER, stream=RunStream())
    await _store(plans, run).set_items(_items("one", "two"))

    # `write_plan` is the tool a model reaches for first and is event-silent in the
    # harness's own stores; a panel built on events alone would sit empty through it.
    events = [b for b in _bodies(run) if isinstance(b, PlanUpdated)]
    assert len(events) == 1
    assert [i["content"] for i in events[0].items] == ["one", "two"]


async def test_each_granular_mutation_emits_the_whole_list(plans):
    run = Run(id="r", kind="chat", owner_id=OWNER, stream=RunStream())
    store = _store(plans, run)
    await store.set_items(_items("one", "two"))
    await store.update_item("t0", status=TaskStatus.completed)
    await store.remove_item("t1")

    events = [b for b in _bodies(run) if isinstance(b, PlanUpdated)]
    assert len(events) == 3
    # Full state every time, so applying an event on SSE replay is idempotent.
    assert [i["status"] for i in events[1].items] == ["completed", "pending"]
    assert [i["content"] for i in events[2].items] == ["one"]


async def test_concurrent_updates_do_not_lose_one(plans):
    store = _store(plans)
    await store.set_items(_items("one", "two", "three"))

    # A model can emit several plan calls in one response, which Pydantic AI runs
    # concurrently. Each is a read-modify-write of the whole list, so without
    # serialization the later writer overwrites the earlier one's change.
    await asyncio.gather(
        store.update_item("t0", status=TaskStatus.completed),
        store.update_item("t1", status=TaskStatus.in_progress),
        store.update_item("t2", status=TaskStatus.cancelled),
    )

    final = {i.id: i.status for i in await store.get_items()}
    assert final == {
        "t0": TaskStatus.completed,
        "t1": TaskStatus.in_progress,
        "t2": TaskStatus.cancelled,
    }


async def test_one_shared_category_keeps_conversations_apart(plans):
    """The category object is built **once** for the whole app and shared by every
    conversation, while each conversation owns its own plan. The capability memoises its
    store on first use, so a single shared capability hands thread B thread A's tasks —
    this drives one toolset, as the app does, rather than a fresh one per call."""
    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage

    from core.container import ServiceContainer
    from tools import RunDeps, build_agent_toolsets
    from tools.plan import plan_toolset

    toolset = build_agent_toolsets({"plan": plan_toolset()})[0]

    async def write(conversation_id: str, task: str) -> None:
        run = Run(id=f"r-{conversation_id}", kind="chat", owner_id=OWNER, stream=RunStream())
        caps = ServiceContainer()
        caps.add(plans, as_type=ConversationPlans)
        deps = RunDeps(
            run=run, owner_id=OWNER, caps=caps, conversation_id=conversation_id
        )
        ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
        tools = await toolset.get_tools(ctx)
        await toolset.call_tool(
            "plan_add_task", {"content": task}, ctx, tools["plan_add_task"]
        )

    await write("conv-a", "alpha task")
    await write("conv-b", "beta task")

    a = await ConversationPlanStore(plans, owner_id=OWNER, conversation_id="conv-a").get_items()
    b = await ConversationPlanStore(plans, owner_id=OWNER, conversation_id="conv-b").get_items()
    assert [i.content for i in a] == ["alpha task"]
    assert [i.content for i in b] == ["beta task"]


async def test_a_run_without_a_conversation_keeps_one_plan():
    """A run with no conversation still gets *one* plan for its lifetime — a store rebuilt
    per call would hand every call an empty list and the plan would never accumulate."""
    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage

    from core.container import ServiceContainer
    from tools import RunDeps, build_agent_toolsets
    from tools.plan import plan_toolset

    toolset = build_agent_toolsets({"plan": plan_toolset()})[0]
    run = Run(id="r-solo", kind="chat", owner_id=OWNER, stream=RunStream())
    deps = RunDeps(run=run, owner_id=OWNER, caps=ServiceContainer(), conversation_id=None)
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
    tools = await toolset.get_tools(ctx)

    await toolset.call_tool(
        "plan_add_task", {"content": "only task"}, ctx, tools["plan_add_task"]
    )
    read = await toolset.call_tool("plan_read_plan", {}, ctx, tools["plan_read_plan"])
    assert "only task" in str(read)


async def test_a_duplicate_id_is_refused(plans):
    store = _store(plans)
    await store.set_items(_items("one"))
    # Two items sharing an id would shadow each other and make later updates land on
    # one of them at random — the protocol requires this to raise.
    with pytest.raises(ValueError):
        await store.add_item(PlanItem(id="t0", content="again", status=TaskStatus.pending))


async def test_updating_a_missing_task_reports_rather_than_writing(plans):
    store = _store(plans)
    await store.set_items(_items("one"))
    assert await store.update_item("nope", status=TaskStatus.completed) is None
    assert await store.remove_item("nope") is False
    assert [i.content for i in await store.get_items()] == ["one"]


async def test_the_plan_is_sealed_at_rest(plans, tmp_path):
    from sqlmodel import Session, select

    await _store(plans).set_items(_items("something private"))

    with Session(plans._db) as session:  # noqa: SLF001 - asserting the stored bytes
        row = session.exec(select(ConversationPlan)).one()
    # The plan describes what the operator asked for, so it is content, not policy.
    assert "something private" not in row.items_enc


async def test_a_locked_vault_degrades_to_no_plan(plans):
    plans._vault.lock()  # noqa: SLF001 - simulating the locked state
    store = _store(plans)
    # Planning aids the turn; it is not the turn. A run that cannot read its plan
    # carries on without one rather than failing.
    assert await store.get_items() == []
    await store.set_items(_items("dropped"))
