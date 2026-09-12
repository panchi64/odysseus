"""What the panel reads: a thread's sub-agents, live and finished.

One endpoint, and what these hold is mostly about what it deliberately *isn't*. There is no
sub-agent transcript route, no sub-agent cancel route and no sub-agent approval route,
because a sub-agent is a conversation and a run and those routes already exist — so the
properties worth pinning are the ones that make the card's other links work: every card
carries the ids that reach them, and the list is what survives a restart.
"""

from __future__ import annotations

import asyncio

from services.subagents import SubagentLauncher, builtin_roster
from tests._helpers import client_app, patch_model_resolution

EXPLORER = builtin_roster()["explorer"]


async def _settle(app, run_id: str) -> None:
    run = app.state.runs.get(run_id)
    assert run is not None
    if run.task is not None:
        await run.task
    for _ in range(5):
        pending = list(app.state.run_terminal_tasks)
        if not pending:
            await asyncio.sleep(0)
            if not app.state.run_terminal_tasks:
                return
            continue
        await asyncio.gather(*pending, return_exceptions=True)


async def _launch(app, conversation_id: str, task: str):
    launcher = app.state.capabilities.get_optional(SubagentLauncher)
    assert launcher is not None
    from services.subagents import SubagentParent

    started = await launcher.launch(
        "operator", EXPLORER, task, parent=SubagentParent(conversation_id=conversation_id)
    )
    await _settle(app, started.run_id)
    return started


async def test_a_thread_with_no_subagents_answers_with_an_empty_list(monkeypatch):
    async with client_app() as (client, _app):
        patch_model_resolution(monkeypatch)
        got = await client.get("/conversations/never-delegated/subagents")

        # Not a 404. The panel asks this for every thread the operator opens, and an
        # error for the ordinary case is an error the client has to learn to ignore.
        assert got.status_code == 200
        assert got.json() == {"subagents": []}


async def test_each_card_carries_the_ids_its_other_links_need(monkeypatch):
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch, output_text="found it in parser.py")
        started = await _launch(app, "parent-1", "find the parser")

        card = (await client.get("/conversations/parent-1/subagents")).json()["subagents"][0]

        # These three are the whole integration: the transcript is that conversation's
        # messages, and the live tail, the approval and the cancel are all that run's
        # routes. A card missing them would need surfaces of its own for each.
        assert card["id"] == started.subagent_id
        assert card["conversation_id"] == started.conversation_id
        assert card["run_id"] == started.run_id
        assert card["name"] == "explorer"
        assert card["task"] == "find the parser"


async def test_a_finished_subagent_stays_on_the_list_with_what_it_reported(monkeypatch):
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch, output_text="found it in parser.py")
        await _launch(app, "parent-1", "find the parser")

        card = (await client.get("/conversations/parent-1/subagents")).json()["subagents"][0]

        # Kept for the life of the thread. The operator's reason for looking is usually
        # that something went wrong, which is exactly when the card is no longer live.
        assert card["status"] == "done"
        assert card["summary"] == "found it in parser.py"
        assert card["ended_at"] is not None


async def test_the_list_is_newest_first(monkeypatch):
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch, output_text="done")
        await _launch(app, "parent-1", "the first one")
        await _launch(app, "parent-1", "the second one")

        listed = (await client.get("/conversations/parent-1/subagents")).json()
        tasks = [s["task"] for s in listed["subagents"]]
        # The card the operator wants is almost always the most recent, and a list that
        # grew downwards would put it off the bottom of a long session.
        assert tasks == ["the second one", "the first one"]


async def test_a_cards_transcript_opens_through_the_ordinary_conversation_route(
    monkeypatch,
):
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch, output_text="found it in parser.py")
        started = await _launch(app, "parent-1", "find the parser")

        got = await client.get(f"/conversations/{started.conversation_id}")

        # The claim the panel is built on, and the one that would break silently: a
        # sub-agent's thread is hidden from the session list but is otherwise an ordinary
        # conversation, so the transcript needs no route and no renderer of its own.
        assert got.status_code == 200
        assert [m["role"] for m in got.json()["messages"]] == ["user", "assistant"]


async def test_one_threads_subagents_are_not_anothers(monkeypatch):
    async with client_app() as (client, app):
        patch_model_resolution(monkeypatch, output_text="done")
        await _launch(app, "parent-1", "mine")
        await _launch(app, "parent-2", "theirs")

        listed = (await client.get("/conversations/parent-1/subagents")).json()["subagents"]
        assert [s["task"] for s in listed] == ["mine"]
