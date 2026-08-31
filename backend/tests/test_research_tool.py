"""The agent's own entry point into research.

Four things here are structural rather than behavioural, and all four break silently:

- the implementation is registered under its **abstract** type, because `tools/` sits
  below the layer that composes a chat turn and a tool naming the concrete class would
  invert the dependency order. If that registration regresses, the tool degrades to
  "unavailable" — which looks like a configuration problem, not a wiring bug.
- `start` **returns without awaiting the run**. Research takes minutes; a tool that
  waited would spend the whole turn on it.
- `start` announces the thread it opened on the parent's own stream, so a conversation
  that appears in the operator's session list has an account of where it came from.
- a **code** thread hands over its worktree to be copied, never worked in. Losing that
  would put a second agent in the operator's own checkout with nothing to say so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.research_threads import (
    ParentThread,
    ResearchThreads,
    ResearchThreadView,
    ResearchUnavailableError,
    StartedResearch,
)
from services.workspace import RunWorkspace
from tests._helpers import client_app
from tools.deps import RunDeps
from tools.research import research_toolset


class _FakeThreads(ResearchThreads):
    def __init__(self, *, fail: str | None = None) -> None:
        self.calls: list[tuple[str, str, ParentThread]] = []
        self._fail = fail

    async def start(self, owner_id, question, *, context="", parent=None):
        if self._fail:
            raise ResearchUnavailableError(self._fail)
        self.calls.append((question, context, parent or ParentThread()))
        return StartedResearch(conversation_id="c-res", run_id="run1", question=question)

    async def read(self, owner_id, conversation_id):
        if conversation_id != "c-res":
            raise ResearchUnavailableError(f"No conversation {conversation_id!r}.")
        return ResearchThreadView(
            conversation_id="c-res",
            question="q",
            status="done",
            answer="# Findings",
        )


class _FakeRun:
    """Just enough Run to receive the `conversation.linked` notice."""

    def __init__(self) -> None:
        self.emitted: list[object] = []

    def emit(self, body) -> None:
        self.emitted.append(body)


def _ctx(
    threads: ResearchThreads | None,
    *,
    workspace: RunWorkspace | None = None,
    permission: str = "edit",
):
    from core.container import ServiceContainer

    caps = ServiceContainer()
    if threads is not None:
        caps.add(threads, as_type=ResearchThreads)

    class _Ctx:
        deps = RunDeps(
            run=_FakeRun(),  # type: ignore[arg-type]
            owner_id="operator",
            caps=caps,
            conversation_id="c-parent",
            project_id="proj-1",
            workspace=workspace,
            permission=permission,  # type: ignore[arg-type]
        )

    return _Ctx()


async def _call(toolset, name: str, ctx, **kwargs):
    return await toolset.tools[name].function(ctx, **kwargs)


class TestStart:
    async def test_returns_immediately_with_the_ids(self):
        threads = _FakeThreads()
        result = await _call(
            research_toolset(), "start", _ctx(threads), question="Why X?", context="c"
        )
        assert result["started"] is True
        assert result["conversation_id"] == "c-res"
        assert [(q, c) for q, c, _ in threads.calls] == [("Why X?", "c")]
        # The result must *say* not to wait — otherwise the model polls, which is the
        # same waste one level up.
        assert "not wait" in result["detail"].lower()

    async def test_the_new_thread_is_announced_on_the_parent_stream(self):
        ctx = _ctx(_FakeThreads())
        await _call(research_toolset(), "start", ctx, question="Why X?")
        (event,) = ctx.deps.run.emitted  # type: ignore[attr-defined]
        assert event.type == "conversation.linked"
        assert (event.conversation_id, event.relation) == ("c-res", "research")

    async def test_a_code_thread_hands_over_its_worktree_to_be_copied(self, tmp_path):
        threads = _FakeThreads()
        worktree = RunWorkspace(root=tmp_path, kind="worktree", files=None)  # type: ignore[arg-type]
        await _call(
            research_toolset(),
            "start",
            _ctx(threads, workspace=worktree),
            question="q",
        )
        _, _, parent = threads.calls[0]
        # The whole point: analysis happens on a copy, never in the operator's checkout.
        assert parent.seed_from == Path(tmp_path)
        assert parent.conversation_id == "c-parent"
        assert parent.project_id == "proj-1"

    async def test_the_parents_own_level_is_handed_over(self):
        """The level the operator approved *this* thread at. Without it the new thread
        would come up at whatever research mode starts a fresh one at, turning one
        approved `research_start` into rope the operator never handed out."""
        threads = _FakeThreads()
        await _call(
            research_toolset(), "start", _ctx(threads, permission="manual"), question="q"
        )
        assert threads.calls[0][2].permission == "manual"

    async def test_a_sandbox_thread_seeds_nothing(self):
        threads = _FakeThreads()
        sandbox = RunWorkspace(root=Path("/work"), kind="sandbox", files=None)  # type: ignore[arg-type]
        await _call(
            research_toolset(), "start", _ctx(threads, workspace=sandbox), question="q"
        )
        assert threads.calls[0][2].seed_from is None

    async def test_an_unavailable_capability_degrades_rather_than_raising(self):
        # Offline, or no usable model. The model should be able to fall back to a plain
        # search, so this is a result, not an exception.
        result = await _call(
            research_toolset(),
            "start",
            _ctx(_FakeThreads(fail="No usable model is configured")),
            question="q",
        )
        assert result["started"] is False
        assert "model" in result["detail"]

    async def test_degrades_when_research_is_not_deployed(self):
        result = await _call(research_toolset(), "start", _ctx(None), question="q")
        assert result["started"] is False


class TestRead:
    async def test_returns_the_answer(self):
        result = await _call(
            research_toolset(), "read", _ctx(_FakeThreads()), conversation_id="c-res"
        )
        assert result["status"] == "done"
        assert result["answer"] == "# Findings"

    async def test_an_unknown_id_asks_the_model_to_retry(self):
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            await _call(
                research_toolset(), "read", _ctx(_FakeThreads()), conversation_id="nope"
            )


class TestWiring:
    async def test_the_implementation_resolves_by_its_abstract_type(self):
        async with client_app() as (_client, app):
            # The whole point of the as_type registration: a tool asks for the
            # abstraction, never the wiring that implements it.
            assert app.state.capabilities.get_optional(ResearchThreads) is not None

    async def test_start_is_approval_gated(self):
        async with client_app() as (_client, app):
            tools = app.state.tool_categories["research"].tools
            # Spending real model budget and reaching the open web unattended is exactly
            # what the operator should see before it happens.
            assert tools["start"].takes_ctx is not None
            assert getattr(tools["start"], "requires_approval", False) is True
