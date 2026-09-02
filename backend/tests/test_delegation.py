"""Delegation: one coarse tool, bound per conversation.

The assertion that matters is about **rooting, not isolation**. `SubAgentToolset`
defines no `for_run`, so the library hands every run the same instance — and that
instance is where the sub-agent's workspace root and the event handler live. A test
that only checked "two runs don't share mutable state" would pass with both threads
rooted at the same directory, which is precisely the bug.
"""

from __future__ import annotations

from pydantic_ai import RunContext, RunUsage
from pydantic_ai.models.test import TestModel

from core.container import ServiceContainer
from runs import Run, RunStream
from tests._helpers import client_app
from tools.agents import (
    AGENT_NAME_ARG,
    AGENT_NAME_DESCRIPTION,
    DELEGATE_TOOL,
    EXPLORER,
    agents_toolset,
)
from tools.deps import RunDeps


class _FakeSession:
    def __init__(self, path):
        self._path = path

    def ensure_workspace(self):
        return self._path


class _FakeSessions:
    """Stands in for SandboxSessionManager: one workspace per conversation key."""

    def __init__(self, tmp_path):
        self._root = tmp_path

    async def acquire(self, key: str, *, holder: object = None):
        path = self._root / key
        path.mkdir(parents=True, exist_ok=True)
        return _FakeSession(path)


class _FakeResolved:
    def __init__(self, model: str) -> None:
        self.model = model
        self.reasoning_off = None


class _FakeRegistry:
    async def resolve_background(self, *, owner_id: str):
        return _FakeResolved("test")


def _ctx(caps: ServiceContainer, conversation_id: str, run_id: str = "run-1"):
    """A stand-in RunContext. The `Run` is real because the binding is keyed on its id —
    a fake without one would let the run-scoping regression back in unnoticed."""

    class _Ctx:
        deps = RunDeps(
            run=Run(id=run_id, kind="chat", owner_id="operator", stream=RunStream()),
            owner_id="operator",
            caps=caps,
            conversation_id=conversation_id,
        )
        tool_call_id = "call-1"

    return _Ctx()


class TestBinding:
    async def test_two_conversations_get_different_workspace_roots(self, tmp_path):
        from services.registry import ModelRegistry
        from services.sandbox import SandboxSessionManager

        caps = ServiceContainer()
        caps.add(_FakeRegistry(), as_type=ModelRegistry)
        caps.add(_FakeSessions(tmp_path), as_type=SandboxSessionManager)

        toolset = agents_toolset()
        a = _bind_for(toolset, caps, tmp_path, "conv-a")
        b = _bind_for(toolset, caps, tmp_path, "conv-b")

        # Not merely "different objects" — different *roots*. Sharing one would let a
        # sub-agent read another conversation's workspace.
        assert a is not b

    async def test_the_same_conversation_reuses_its_binding(self, tmp_path):
        from services.registry import ModelRegistry
        from services.sandbox import SandboxSessionManager

        caps = ServiceContainer()
        caps.add(_FakeRegistry(), as_type=ModelRegistry)
        caps.add(_FakeSessions(tmp_path), as_type=SandboxSessionManager)

        toolset = agents_toolset()
        first = _bind_for(toolset, caps, tmp_path, "conv-a")
        second = _bind_for(toolset, caps, tmp_path, "conv-a")
        # Building one registers the sub-agents and generates their schemas; doing that
        # per call would be a real cost on a hot path.
        assert first is second

    async def test_a_second_run_gets_a_fresh_binding(self, tmp_path):
        from services.registry import ModelRegistry
        from services.sandbox import SandboxSessionManager

        caps = ServiceContainer()
        caps.add(_FakeRegistry(), as_type=ModelRegistry)
        caps.add(_FakeSessions(tmp_path), as_type=SandboxSessionManager)

        toolset = agents_toolset()
        first = _bind_for(toolset, caps, tmp_path, "conv-a", run_id="run-1")
        second = _bind_for(toolset, caps, tmp_path, "conv-a", run_id="run-2")
        # The binding captures the run's event-stream handler, so reusing it across runs
        # would emit turn 2's sub-agent progress onto turn 1's finished Run — the
        # delegation would look silent from the second turn onward. Same workspace, same
        # model, different run ⇒ different binding.
        assert first is not second


def _bind_for(toolset, caps, tmp_path, conversation_id: str, run_id: str = "run-1"):
    """The binding is what's under test, so it is reached directly rather than through
    a full delegate call (which would run a real sub-agent)."""
    return toolset._bind(  # noqa: SLF001
        str(tmp_path / conversation_id),
        _FakeResolved("test"),
        _ctx(caps, conversation_id, run_id),
    )


class TestDegrades:
    async def test_no_workspace_degrades_rather_than_failing_the_turn(self):
        caps = ServiceContainer()
        result = await agents_toolset().call_tool(
            "delegate_task",
            {"agent_name": EXPLORER, "task": "look"},
            _ctx(caps, "conv-a"),  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
        assert "unavailable" in str(result).lower()


class TestCatalogAndPrompt:
    async def test_the_delegate_tool_is_operator_toggleable(self):
        async with client_app() as (_client, app):
            # The whole reason it is a toolset rather than a capability: it has to be in
            # the catalog the operator can switch off.
            assert "agents" in app.state.tool_categories
            names = set(app.state.tool_categories["agents"].tools)
            assert "delegate_task" in names

    def test_the_delegate_listing_rides_on_the_tools_own_description(self):
        """It used to be a second standing instruction at the prompt head saying what the
        description already implies. One home, read where the model is deciding."""
        text = agents_toolset().tools[DELEGATE_TOOL].description or ""
        assert EXPLORER in text
        # It must also say when *not* to delegate, or the model reaches for it on
        # one-tool-call questions and pays a round trip for nothing.
        assert "not delegate" in text.lower()

    async def test_the_operator_is_shown_what_the_model_is_told(self):
        """The description is read from two places — `get_tools` for the model, `.tools`
        for the catalog — and an override applied to one of them is a settings screen
        describing a tool that no longer works that way."""
        toolset = agents_toolset()
        deps = RunDeps(
            run=Run(id="run-1", kind="chat", owner_id="operator", stream=RunStream()),
            owner_id="operator",
            caps=ServiceContainer(),
            conversation_id="conv-a",
        )
        ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
        offered = await toolset.get_tools(ctx)
        assert offered[DELEGATE_TOOL].tool_def.description == (
            toolset.tools[DELEGATE_TOOL].description
        )

    async def test_the_agent_name_parameter_points_at_the_roster_that_exists(self):
        """The harness writes `agent_name` against the standing listing its capability
        form registers. We register the toolset and put the roster in the description, so
        the library's text sends the model looking for a listing nothing writes — it then
        guesses a name and spends a retry on `Unknown sub-agent`."""
        toolset = agents_toolset()
        deps = RunDeps(
            run=Run(id="run-1", kind="chat", owner_id="operator", stream=RunStream()),
            owner_id="operator",
            caps=ServiceContainer(),
            conversation_id="conv-a",
        )
        ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
        offered = await toolset.get_tools(ctx)
        schema = offered[DELEGATE_TOOL].tool_def.parameters_json_schema
        assert "instructions" not in schema["properties"][AGENT_NAME_ARG]["description"]
        assert schema["properties"][AGENT_NAME_ARG]["description"] == AGENT_NAME_DESCRIPTION
