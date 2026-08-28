"""The agent's own entry point into deep research.

Two things here are structural rather than behavioural, and both are the kind that
break silently:

- the launcher is registered under its **abstract** type, because `tools/` sits below
  `research/` and a tool naming the concrete orchestrator would invert the dependency
  order. If that registration regresses, the tool degrades to "unavailable" — which
  looks like a configuration problem, not a wiring bug.
- `start` **returns without awaiting the run**. A research run takes minutes; a tool
  that waited would spend the whole turn on it.
"""

from __future__ import annotations

import asyncio

import pytest

from services.research_launcher import (
    LaunchedResearch,
    ResearchLauncher,
    ResearchSnapshot,
    ResearchUnavailableError,
)
from tests._helpers import client_app
from tools.deps import RunDeps
from tools.research import research_toolset


class _FakeLauncher(ResearchLauncher):
    def __init__(self, *, fail: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail
        self.finished = asyncio.Event()

    async def launch(self, owner_id, question, context=""):
        if self._fail:
            raise ResearchUnavailableError(self._fail)
        self.calls.append((question, context))
        return LaunchedResearch(research_id="r1", run_id="run1", question=question)

    async def snapshot(self, owner_id, research_id):
        if research_id != "r1":
            raise ResearchUnavailableError(f"No research entry {research_id!r}.")
        return ResearchSnapshot(
            research_id="r1",
            question="q",
            status="done",
            report="# Findings",
            sources=7,
            findings=3,
        )


def _ctx(launcher: ResearchLauncher | None):
    from core.container import ServiceContainer

    caps = ServiceContainer()
    if launcher is not None:
        caps.add(launcher, as_type=ResearchLauncher)

    class _Ctx:
        deps = RunDeps(run=None, owner_id="operator", caps=caps)  # type: ignore[arg-type]

    return _Ctx()


async def _call(toolset, name: str, ctx, **kwargs):
    return await toolset.tools[name].function(ctx, **kwargs)


class TestStart:
    async def test_returns_immediately_with_the_ids(self):
        launcher = _FakeLauncher()
        result = await _call(
            research_toolset(), "start", _ctx(launcher), question="Why X?", context="c"
        )
        assert result["started"] is True
        assert result["research_id"] == "r1"
        assert launcher.calls == [("Why X?", "c")]
        # The result must *say* not to wait — otherwise the model polls, which is the
        # same waste one level up.
        assert "not wait" in result["detail"].lower()

    async def test_an_unavailable_capability_degrades_rather_than_raising(self):
        # Offline, or the web tools switched off. The model should be able to fall back
        # to a plain search, so this is a result, not an exception.
        result = await _call(
            research_toolset(),
            "start",
            _ctx(_FakeLauncher(fail="needs web_search")),
            question="q",
        )
        assert result["started"] is False
        assert "web_search" in result["detail"]

    async def test_degrades_when_research_is_not_deployed(self):
        result = await _call(research_toolset(), "start", _ctx(None), question="q")
        assert result["started"] is False


class TestRead:
    async def test_returns_the_report_once_terminal(self):
        result = await _call(
            research_toolset(), "read", _ctx(_FakeLauncher()), research_id="r1"
        )
        assert result["status"] == "done"
        assert result["report"] == "# Findings"
        assert result["sources"] == 7

    async def test_an_unknown_id_asks_the_model_to_retry(self):
        from pydantic_ai import ModelRetry

        with pytest.raises(ModelRetry):
            await _call(
                research_toolset(), "read", _ctx(_FakeLauncher()), research_id="nope"
            )


class TestWiring:
    async def test_the_launcher_resolves_by_its_abstract_type(self):
        async with client_app() as (_client, app):
            # The whole point of the as_type registration: a tool asks for the
            # abstraction, never the orchestrator that implements it.
            assert app.state.capabilities.get_optional(ResearchLauncher) is not None

    async def test_start_is_approval_gated(self):
        async with client_app() as (_client, app):
            tools = app.state.tool_categories["research"].tools
            # Spending real model budget and reaching the open web unattended is exactly
            # what the operator should see before it happens.
            assert tools["start"].takes_ctx is not None
            assert getattr(tools["start"], "requires_approval", False) is True
