"""A sub-agent, launched as an ordinary turn.

Delegation used to run a bespoke `Agent(...)` loop of its own, inside the calling tool,
blocking the parent's turn for as long as it took. It is now a conversation composed by
the same `compose_turn` every other turn goes through. What that buys — and therefore what
these hold onto — is that the sub-agent is an *ordinary* run: the same engine, the same
persisted transcript, the same context gauge, the same approval machinery.

The things worth pinning are the ones that would quietly stop being true:

- `launch` **returns before the sub-agent finishes**, which is the whole point of the
  change and the one property the blocking version could not have;
- the sub-agent can never do **more than the thread that launched it**;
- it **cannot launch sub-agents of its own**, so the depth is one by construction rather
  than by a counter somebody has to maintain;
- its thread is **hidden but real** — no one can type into it, and its transcript is a
  conversation the panel can open by id;
- it is **registered durably**, because a link held only in memory leaves the operator
  with unreachable transcripts after a restart;
- isolation only ever **increases**: the launch may ask a sharing sub-agent to step out of
  the way, and may never pull an isolated one into the operator's own files.
"""

from __future__ import annotations

import pytest

from services.subagent_store import SubagentStore
from services.subagents import (
    SubagentLauncher,
    SubagentParent,
    SubagentSpec,
    SubagentUnavailableError,
    builtin_roster,
)
from tests._helpers import client_app, patch_model_resolution

EXPLORER = builtin_roster()["explorer"]
WORKER = builtin_roster()["worker"]


def _launcher(app) -> SubagentLauncher:
    launcher = app.state.capabilities.get_optional(SubagentLauncher)
    assert launcher is not None, "the subagents manifest did not export its implementation"
    return launcher


def _records(app) -> SubagentStore:
    records = getattr(app.state, "subagent_records", None)
    assert isinstance(records, SubagentStore), (
        "the subagents manifest did not export its register"
    )
    return records


async def _settle(app, run_id: str) -> None:
    """Let the submitted run finish — it is a real Run on the real registry."""
    run = app.state.runs.get(run_id)
    assert run is not None
    if run.task is not None:
        await run.task


class TestLaunching:
    async def test_returns_before_the_subagent_finishes(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="what I found")

            started = await _launcher(app).launch("operator", EXPLORER, "find the parser")

            # THE assertion. A tool that awaited this would spend its whole turn here,
            # which is exactly what the blocking delegation did.
            assert app.state.runs.get(started.run_id) is not None
            await _settle(app, started.run_id)

    async def test_the_task_is_what_names_the_thread(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            started = await _launcher(app).launch("operator", EXPLORER, "find the parser")
            await _settle(app, started.run_id)

            summary = await app.state.conversations.get_summary(
                started.conversation_id, "operator"
            )
            # Nobody wrote this thread's opening message, so without the task in its name
            # a card reads "Untitled" and the operator cannot tell it from its neighbours.
            assert summary is not None
            assert "find the parser" in (summary.title or "")

    async def test_the_thread_is_hidden_but_readable(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            started = await _launcher(app).launch("operator", EXPLORER, "read the config")
            await _settle(app, started.run_id)

            listed = await app.state.conversations.list_conversations("operator")
            assert started.conversation_id not in {c.id for c in listed}
            # Hidden from the listing, and still a whole conversation — which is what the
            # panel opens when a card is expanded, and what keeps the transcript.
            turns = await app.state.conversations.messages_view(started.conversation_id)
            assert [t.role for t in turns] == ["user", "assistant"]

    async def test_an_empty_task_is_refused(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch)
            with pytest.raises(SubagentUnavailableError):
                await _launcher(app).launch("operator", EXPLORER, "   ")


class TestWhatItMayDo:
    async def test_it_never_reaches_further_than_its_parent(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            # A worker's own ceiling is the mode's default; the parent is down at Manual.
            started = await _launcher(app).launch(
                "operator",
                WORKER,
                "rename the thing",
                parent=SubagentParent(permission="manual"),
            )
            await _settle(app, started.run_id)

            binding = await app.state.conversations.binding(started.conversation_id)
            # Otherwise one approved launch buys a standing level the operator never chose.
            assert binding.permission == "manual"

    async def test_it_cannot_launch_subagents_of_its_own(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            composed = _capture_composition(monkeypatch)

            started = await _launcher(app).launch("operator", EXPLORER, "look around")
            await _settle(app, started.run_id)

            # Depth is one by construction. A tree of agents is unbounded cost and
            # unbounded blast radius, and nothing about the work needs one.
            assert "subagents_launch" in composed["disabled_tools"]

    async def test_it_runs_in_the_lane_for_work_the_agent_opened_for_itself(
        self, monkeypatch
    ):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            composed = _capture_composition(monkeypatch)

            started = await _launcher(app).launch("operator", EXPLORER, "look around")
            await _settle(app, started.run_id)

            # Not the interactive lane: a burst of sub-agents must never hold up the turn
            # the operator is sitting in front of (`runs/lanes.py`).
            assert composed["kind"] == "linked"
            # And a wall clock, because nobody is watching — the inactivity watchdog
            # cannot end a run that keeps streaming tokens.
            assert composed["wall_clock_timeout_s"]

    async def test_a_spec_needing_a_withheld_tool_refuses_rather_than_pretends(
        self, monkeypatch
    ):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch)
            impossible = SubagentSpec(
                name="impossible",
                description="needs something that is not there",
                brief="do the thing",
                required=frozenset({"subagents_launch"}),
            )
            # `subagents_launch` is withheld from every sub-agent, so this can never be
            # satisfied — and a sub-agent that ran anyway would answer from model memory
            # and read, to everything downstream, exactly as though it had done the work.
            with pytest.raises(SubagentUnavailableError, match="subagents_launch"):
                await _launcher(app).launch("operator", impossible, "go")


class TestTheRegister:
    async def test_a_launch_is_recorded_so_the_transcript_stays_reachable(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="what I found")
            started = await _launcher(app).launch(
                "operator",
                EXPLORER,
                "find the parser",
                parent=SubagentParent(conversation_id="parent-1"),
            )
            await _settle(app, started.run_id)

            rows = await _records(app).for_parent("parent-1", "operator")
            assert [row.child_conversation_id for row in rows] == [started.conversation_id]
            # The link is what a restart would otherwise lose, leaving the operator with a
            # transcript nothing can name.
            assert rows[0].spec_name == "explorer"

    async def test_a_stranded_row_is_reconciled_rather_than_left_running(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            started = await _launcher(app).launch(
                "operator",
                EXPLORER,
                "look",
                parent=SubagentParent(conversation_id="parent-1"),
            )
            await _settle(app, started.run_id)
            records = _records(app)
            # However it ended, put it back to how a process that died would leave it.
            await records.set_status(started.subagent_id, "running")

            assert await records.reconcile_stranded() >= 1

            row = await records.get(started.subagent_id, "operator")
            assert row is not None
            # A row still live after a restart describes work that stopped when the
            # process did: left alone it counts against the cap and promises a report
            # that is never coming.
            assert row.status == "cancelled"
            assert row.ended_at is not None


class TestIsolation:
    async def test_sharing_puts_the_subagent_in_the_parents_workspace(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            started = await _launcher(app).launch(
                "operator",
                EXPLORER,
                "read it",
                parent=SubagentParent(conversation_id="parent-1", workspace_key="parent-1"),
            )
            await _settle(app, started.run_id)

            row = await _records(app).get(started.subagent_id, "operator")
            assert row is not None
            # The default: it sees the work in progress, and what it does is simply there.
            assert row.workspace_key == "parent-1"
            assert row.delegation_id is None

    async def test_isolating_gives_it_a_delegated_key_of_its_own(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            started = await _launcher(app).launch(
                "operator",
                WORKER,
                "rewrite it",
                parent=SubagentParent(conversation_id="parent-1", workspace_key="parent-1"),
                isolate=True,
            )
            await _settle(app, started.run_id)

            row = await _records(app).get(started.subagent_id, "operator")
            assert row is not None
            # A delegated key — `<parent>/<delegation>` — which is what routes it to its
            # own copy in both workspace kinds (`services/workspace.py`).
            assert row.workspace_key.startswith("parent-1/")
            assert row.delegation_id is not None

    async def test_isolation_only_ever_increases(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="done")
            apart = SubagentSpec(
                name="apart",
                description="works apart",
                brief="do it elsewhere",
                workspace="isolated",
            )
            started = await _launcher(app).launch(
                "operator",
                apart,
                "go",
                parent=SubagentParent(conversation_id="parent-1", workspace_key="parent-1"),
                isolate=False,
            )
            await _settle(app, started.run_id)

            row = await _records(app).get(started.subagent_id, "operator")
            assert row is not None
            # Omitting `isolate` must not pull a sub-agent written to stay out of the way
            # back into the operator's own files.
            assert row.workspace_policy == "isolated"


def _capture_composition(monkeypatch) -> dict:
    """The arguments the sub-agent's turn was actually composed with.

    Wrapping the real `compose_turn` rather than replacing it: the turn still runs, so
    these stay tests of a sub-agent that works rather than of a call that was made.
    """
    from harness.manifests import _subagents

    seen: dict = {}
    real = _subagents.compose_turn

    def capture(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(_subagents, "compose_turn", capture)
    return seen
