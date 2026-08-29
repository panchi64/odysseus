"""What the context window is holding, split three ways.

The provider reports one number and no breakdown, so the split is measured on our side —
the same posture as the wall-clock timings, and for the same reason: it has to mean the
same thing on Anthropic, on an OpenAI-compatible endpoint and on a local server.

The two properties that matter are asserted throughout. The parts always sum to exactly
the total the provider reported, because a breakdown that disagrees with the figure above
it reads as a bug even when the drift is one token. And a split that couldn't be measured
is absent rather than zeroed — a composition claiming no system prompt and no tools would
be a confident lie about the one thing this readout exists to expose.
"""

from __future__ import annotations

import pytest
from pydantic_ai import ModelRequest, ModelResponse
from pydantic_ai.messages import TextPart, UserPromptPart
from pydantic_ai.usage import RequestUsage

from runs import TurnOverhead
from services.context_budget import compose


def _messages(text: str) -> list:
    return [
        ModelRequest(parts=[UserPromptPart(content=text)]),
        ModelResponse(parts=[TextPart(content="ok")], usage=RequestUsage()),
    ]


# ── The sum ──────────────────────────────────────────────────────────────────────


def test_the_parts_add_up_to_the_providers_own_total():
    split = compose(1_000, TurnOverhead(system=400, tools=1_600), _messages("x" * 2_000))
    assert split is not None
    assert split.system + split.tools + split.messages == 1_000


@pytest.mark.parametrize("used", [1, 7, 33, 101, 999, 12_345, 262_144])
def test_they_add_up_at_every_size(used: int):
    """Three independently rounded shares can miss their total by a token or two; the
    largest part absorbs the drift. Sizes chosen to land on awkward remainders."""
    split = compose(used, TurnOverhead(system=333, tools=333), _messages("y" * 999))
    assert split is not None
    assert split.system + split.tools + split.messages == used


def test_proportions_follow_the_inputs():
    # Tools ten times the standing brief ⇒ ten times the share, give or take rounding.
    split = compose(10_000, TurnOverhead(system=100, tools=1_000), _messages(""))
    assert split is not None
    assert split.tools > split.system * 8


def test_a_thread_of_mostly_conversation_reads_that_way():
    """The distinction the readout exists for: a window filled by the conversation wants a
    compaction, one filled by tool schemas wants fewer tools on, and the total alone can't
    tell them apart."""
    split = compose(100_000, TurnOverhead(system=500, tools=500), _messages("z" * 400_000))
    assert split is not None
    assert split.messages > split.system + split.tools


# ── Absent, never zero ───────────────────────────────────────────────────────────


def test_no_overhead_measured_means_no_split():
    # A turn that never reached a model request has no tool definitions to have measured.
    assert compose(5_000, None, _messages("hello")) is None


def test_no_footprint_means_no_split():
    assert compose(None, TurnOverhead(system=10, tools=10), _messages("hello")) is None
    assert compose(0, TurnOverhead(system=10, tools=10), _messages("hello")) is None


def test_nothing_to_measure_means_no_split():
    # Everything empty: dividing by a zero total would raise, and a zeroed split would
    # claim the window holds nothing while `used` says otherwise.
    assert compose(5_000, TurnOverhead(system=0, tools=0), []) is None


# ── Measured off a real request ──────────────────────────────────────────────────


async def test_the_overhead_is_measured_from_the_request_that_went_out():
    """`measure_overhead` reaches into Pydantic AI internals that carry no compatibility
    promise, so this pins the two things it must find: the standing brief and the tool
    schemas the model was actually handed."""
    from pydantic_ai import Agent, FunctionToolset
    from pydantic_ai.models.test import TestModel

    from agent.overhead import measure_overhead

    toolset: FunctionToolset = FunctionToolset()

    @toolset.tool_plain
    def lookup(query: str, limit: int = 5) -> str:
        """Look something up in the corpus."""
        return "x"

    agent = Agent(
        TestModel(custom_output_text="ok", call_tools=[]),
        system_prompt="A" * 300,
        instructions="B" * 200,
        toolsets=[toolset],
    )
    async with agent.iter("hello") as run:
        async for node in run:
            if not Agent.is_model_request_node(node):
                continue
            async with node.stream(run.ctx) as stream:
                async for _ in stream:
                    pass
            overhead = measure_overhead(run.ctx, node.request)
            break

    assert overhead is not None
    # Both halves of the standing brief, counted together: the instructions off the
    # assembled request, the system prompt off the history head.
    assert overhead.system >= 500
    # The schema is serialized, so the tool's name, its docstring and its parameters are
    # all in there — the figure is far larger than the name alone.
    assert overhead.tools > len("lookup")
    assert overhead.tools > 100


def test_a_broken_context_degrades_to_unmeasured_rather_than_raising():
    """Every attribute this reads is a library internal. An upgrade that moves one must
    cost the readout, never the turn that was producing it."""
    from agent.overhead import measure_overhead

    class _Nothing:
        def __getattr__(self, name):
            raise AttributeError(name)

    assert measure_overhead(_Nothing(), _Nothing()) is None


async def test_a_live_turn_reports_a_split_that_sums_to_its_footprint():
    """The whole chain: measured at the request node, carried on the Run, scaled in
    `compose`, and emitted on the metrics frame the gauge reads."""
    from pydantic_ai import FunctionToolset
    from pydantic_ai.models.test import TestModel

    from agent import build_chat_orchestrator
    from runs import RunRegistry, RunStatus

    toolset: FunctionToolset = FunctionToolset()

    @toolset.tool_plain
    def ping() -> str:
        """Answer with pong."""
        return "pong"

    orch = build_chat_orchestrator(
        "hi",
        model=TestModel(custom_output_text="ok", call_tools=[]),
        categories={"util": toolset},
        context_window=100_000,
    )
    run = RunRegistry().submit(kind="chat", owner_id="operator", orchestrator=orch)
    await run.wait()
    assert run.status is RunStatus.done

    frame = [e.body for e in run.stream.replay() if e.body.type == "run.metrics"][-1]
    assert frame.context is not None
    parts = frame.context.parts
    assert parts is not None, "a turn that made a real request must report a split"
    assert parts.system + parts.tools + parts.messages == frame.context.used
    # The tool the turn was given is in there; a zero would mean the schemas went
    # unmeasured while still being sent.
    assert parts.tools > 0
    assert parts.system > 0


# ── The reload ───────────────────────────────────────────────────────────────────


def test_the_cache_keeps_the_last_good_measurement():
    """A failed measurement is ignored rather than stored as absence: the previous figure
    still describes the configuration better than nothing does."""
    from runs import TurnOverhead as Overhead
    from services.context_budget import OverheadCache

    cache = OverheadCache()
    assert cache.get("chat") is None
    cache.remember("chat", Overhead(system=100, tools=200))
    cache.remember("chat", None)
    assert cache.get("chat") == Overhead(system=100, tools=200)


def test_the_cache_is_keyed_by_mode():
    # A coding thread and a chat thread are handed different tools, so one's measurement
    # would misreport the other's weight.
    from runs import TurnOverhead as Overhead
    from services.context_budget import OverheadCache

    cache = OverheadCache()
    cache.remember("chat", Overhead(system=100, tools=200))
    assert cache.get("coding") is None


async def test_a_turn_leaves_its_measurement_for_the_next_cold_load(monkeypatch):
    """What makes a reload able to break the window down at all. The route reads this cache
    keyed by the thread's mode; if a turn doesn't fill it, a reloaded thread shows a total
    with no split and the operator has to send a message to learn why their window is
    full — which is the decision they opened the breakdown to make."""
    from ._helpers import client_app, collect_sse_events, patch_model_resolution

    patch_model_resolution(monkeypatch)
    async with client_app() as (client, app):
        assert app.state.context_overhead.get("chat") is None
        created = (await client.post("/chat", json={"prompt": "hello"})).json()
        await collect_sse_events(client, created["run_id"])

        overhead = app.state.context_overhead.get("chat")
        assert overhead is not None, "a completed turn must leave its overhead behind"
        # Both halves are real: the app assembles a full tool catalog and a standing brief,
        # so a zero in either would mean the measurement found nothing while the request
        # plainly carried something.
        assert overhead.system > 0
        assert overhead.tools > 0
        # And it is keyed by the thread's mode, not shared across them.
        assert app.state.context_overhead.get("coding") is None


# ── What counts as message weight ────────────────────────────────────────────────


def test_a_structured_tool_result_counts_as_the_json_it_becomes():
    """The bug this readout surfaced. A tool result is usually a dict, and it reaches the
    model as serialized JSON — but the estimator read only `str` content, scoring every
    one of them zero. On a tool-heavy thread that is most of the window: the split
    credited the whole weight to the tool *schemas* rather than the results they
    returned, and auto-compaction (which shares the estimate) held off on exactly the
    threads filling up fastest."""
    from pydantic_ai.messages import ToolReturnPart

    from services.conversation_view import estimate_tokens

    payload = {"results": [{"title": "t" * 200, "snippet": "s" * 2_000} for _ in range(5)]}
    messages = [
        ModelRequest(parts=[ToolReturnPart(tool_name="search", content=payload, tool_call_id="1")])
    ]
    assert estimate_tokens(messages) > 2_000


def test_binary_content_still_counts_as_nothing():
    """The rule the fix above had to leave intact. A retained screenshot is base64 in the
    blob; measuring it by character length would read one image as hundreds of thousands
    of phantom tokens and compact a thread nowhere near full."""
    from pydantic_ai import BinaryContent
    from pydantic_ai.messages import ToolReturnPart

    from services.conversation_view import estimate_tokens

    image = BinaryContent(data=b"x" * 100_000, media_type="image/png")
    messages = [
        ModelRequest(parts=[ToolReturnPart(tool_name="shot", content=image, tool_call_id="1")])
    ]
    assert estimate_tokens(messages) == 0


def test_dict_keys_count_too():
    """Keys are serialized alongside the data and are a real share of a wide row's
    tokens — a result of many short values under long field names is mostly field
    names."""
    from pydantic_ai.messages import ToolReturnPart

    from services.conversation_view import estimate_tokens

    wide = {"a_long_field_name_here" * 4: "v", "another_long_field_name" * 4: "v"}
    messages = [
        ModelRequest(parts=[ToolReturnPart(tool_name="t", content=wide, tool_call_id="1")])
    ]
    assert estimate_tokens(messages) > 40
