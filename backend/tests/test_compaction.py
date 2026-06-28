"""Tool-result compaction — the model sees a digested view, the operator sees all.

The mechanism is fixed by two facts (Phase 0, `test_process_history_output_becomes_all_messages`
+ `test_current_turn_returns_stay_full`):

- A history processor installed as a ``ProcessHistory`` capability is NOT persistence-
  transparent — its output *becomes* ``result.all_messages()`` (what the engine persists).
- The engine only persists ``messages[start:]`` — the current turn. So compaction is operator-
  lossless iff it only ever touches *prior* turns (before the last ``UserPromptPart``) and
  leaves the current turn whole.

The rest exercises the real ``agent.compaction`` processor: the rolling K-window, the size
floor, disabled passthrough, the digest pointer, and end-to-end rehydration via the namespaced
``builtin_expand_tool_result`` tool.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import Agent, FunctionToolset
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent.compaction import EXPAND_TOOL, build_compaction_context, compact_tool_returns
from core.config import get_settings
from runs import Run, RunStream
from tools import CompactionContext, RunDeps, build_agent_toolsets, builtin_toolset

_HUGE = "X" * 5000
_HUGE_CURRENT = "Y" * 5000


# --- helpers ----------------------------------------------------------------


def _deps(cc: CompactionContext) -> RunDeps:
    run = Run(id="t", kind="chat", owner_id="op", stream=RunStream())
    return RunDeps(run=run, owner_id="op", compaction=cc)


def _returns_by_tool(messages: list[ModelMessage]) -> dict[str, str]:
    return {
        p.tool_name: p.content
        for m in messages
        for p in m.parts
        if isinstance(p, ToolReturnPart) and isinstance(p.content, str)
    }


def _prior_returns(*tool_ids: str, content: Any = _HUGE) -> list[ModelMessage]:
    """A prior-turn chain: one user question, then a call/return pair per id."""
    out: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="q0")])]
    for tid in tool_ids:
        out.append(ModelResponse(parts=[ToolCallPart(tool_name=tid, args={}, tool_call_id=tid)]))
        out.append(
            ModelRequest(parts=[ToolReturnPart(tool_name=tid, content=content, tool_call_id=tid)])
        )
    return out


async def _run(
    cc: CompactionContext,
    history: list[ModelMessage],
    *,
    toolsets=None,
    driver=None,
    prompt: str | None = "follow up",
    protect_from: int | None = None,
):
    """Run the real processor over ``history`` with a FunctionModel; return (model_saw, result).

    ``protect_from`` is the persistence boundary the engine would set; it defaults to the whole
    ``history`` (so the appended ``prompt`` is the only "current" turn), and is given explicitly
    by the boundary tests that fold the current turn into ``history``."""
    seen: list[list[ModelMessage]] = []
    cc.protect_from = len(history) if protect_from is None else protect_from

    def capture(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        return ModelResponse(parts=[TextPart("ok")])

    agent = Agent(
        FunctionModel(driver or capture),
        deps_type=RunDeps,
        capabilities=[ProcessHistory(compact_tool_returns)],
        toolsets=toolsets or [],
    )
    result = await agent.run(prompt, message_history=history, deps=_deps(cc))
    return seen, result


# --- Phase 0: the load-bearing library facts --------------------------------


async def test_process_history_output_becomes_all_messages():
    """The constraint we design around: ProcessHistory is NOT persistence-transparent."""
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    seen, result = await _run(cc, _prior_returns("old"))

    model_saw = _returns_by_tool(seen[0])["old"]
    assert "compacted" in model_saw  # model saw the notice, not the output...
    assert "XXXXX" not in model_saw  # ...and no excerpt of the original survives
    # ...and all_messages carries that same digest — not the original.
    assert "compacted" in _returns_by_tool(result.all_messages())["old"]


async def test_current_turn_returns_stay_full_while_prior_compacts():
    """A current-turn tool return survives full in all_messages() (what the engine persists),
    while a prior-turn return is compacted for the model."""

    def driver(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        has_current = any(
            isinstance(p, ToolReturnPart) and p.tool_name == "web_fetch"
            for m in messages
            for p in m.parts
        )
        if has_current:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name="web_fetch", args={}, tool_call_id="cur")]
        )

    web = FunctionToolset()

    @web.tool_plain
    def fetch() -> str:  # namespaced to `web_fetch`; the current turn's big tool output
        return _HUGE_CURRENT

    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(
        cc, _prior_returns("old"), toolsets=build_agent_toolsets({"web": web}), driver=driver
    )

    returns = _returns_by_tool(result.all_messages())
    assert "compacted" in returns["old"]  # prior turn → digested (ephemeral, not re-persisted)
    assert returns["web_fetch"] == _HUGE_CURRENT  # current turn → FULL (what the engine persists)


# --- the rolling window + size floor ---------------------------------------


async def test_keep_recent_window_keeps_the_last_k_full():
    cc = CompactionContext(enabled=True, keep_recent=1, min_tokens=0)
    _seen, result = await _run(cc, _prior_returns("t1", "t2", "t3"))

    returns = _returns_by_tool(result.all_messages())
    assert "compacted" in returns["t1"] and "compacted" in returns["t2"]  # older → digested
    assert returns["t3"] == _HUGE  # the most recent stays full
    assert set(cc.full_by_id) == {"t1", "t2"}  # only the digested ones are recoverable


async def test_size_floor_leaves_small_results_untouched():
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(cc, _prior_returns("small", content="tiny output"))

    assert _returns_by_tool(result.all_messages())["small"] == "tiny output"
    assert cc.full_by_id == {}  # nothing compacted → nothing to recover


async def test_disabled_passes_history_through_untouched():
    cc = CompactionContext(enabled=False, keep_recent=0, min_tokens=0)
    _seen, result = await _run(cc, _prior_returns("old"))

    assert _returns_by_tool(result.all_messages())["old"] == _HUGE
    assert cc.full_by_id == {}


async def test_digest_points_at_the_namespaced_expand_tool():
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    seen, _result = await _run(cc, _prior_returns("old"))

    digest = _returns_by_tool(seen[0])["old"]
    assert EXPAND_TOOL == "builtin_expand_tool_result"
    assert f'{EXPAND_TOOL}("old")' in digest  # the model can call the name verbatim


# --- the boundary is the persistence index, not the last user prompt --------


async def test_pre_nudge_current_turn_return_stays_full():
    """The boundary is ``protect_from`` (the persistence index), NOT the last ``UserPromptPart``.
    A verifier correction injects a *second* user prompt (the nudge) inside the current,
    to-be-persisted turn; a tool return that precedes it must still count as current and stay
    full — otherwise ``_finalize`` persists it as an unrecoverable digest (the data-loss bug)."""
    prior = _prior_returns("prior")  # a genuinely-prior turn (3 messages)
    current = [
        ModelRequest(parts=[UserPromptPart(content="real ask")]),
        ModelResponse(parts=[ToolCallPart(tool_name="cur", args={}, tool_call_id="cur")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="cur", content=_HUGE, tool_call_id="cur")]),
        ModelResponse(parts=[TextPart("rejected answer")]),
        ModelRequest(parts=[UserPromptPart(content="nudge: try again")]),  # 2nd user prompt
    ]
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(
        cc, prior + current, prompt=None, protect_from=len(prior)
    )

    returns = _returns_by_tool(result.all_messages())
    assert returns["cur"] == _HUGE  # before the nudge but within the persisted turn → FULL
    assert "compacted" in returns["prior"]  # the actually-prior return → digested
    assert "cur" not in cc.full_by_id  # never stashed, because never compacted


# --- structured (non-string) tool content ----------------------------------


async def test_structured_tool_content_is_compacted_and_recoverable():
    """A large structured (dict/list) tool result is compacted just like a string — it's the
    same context bloat. The notice replaces it for the model; the original object is stashed
    verbatim for rehydration."""
    big = {"rows": [{"i": i, "text": "x" * 50} for i in range(200)]}
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(cc, _prior_returns("struct", content=big))

    assert "compacted" in _returns_by_tool(result.all_messages())["struct"]  # digested for model
    assert cc.full_by_id["struct"] == big  # the structured original recovered verbatim


async def test_binary_tool_content_is_left_verbatim():
    """Content the JSON envelope can't carry (binary/multimodal) is never replaced by a text
    notice — the model must keep seeing it. ``_content_size`` returns None ⇒ skip."""
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    blob = b"\x89PNG" + b"\x00" * 5000  # not JSON-serializable
    _seen, result = await _run(cc, _prior_returns("img", content=blob))

    binary = [
        p.content
        for m in result.all_messages()
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.tool_name == "img"
    ]
    assert binary == [blob]  # handed back untouched
    assert cc.full_by_id == {}


# --- the rolling window counts prior-turn returns only ----------------------


async def test_keep_recent_counts_prior_returns_only():
    """The K window applies to *prior-turn* results; current-turn returns are protected wholesale
    and must not consume the budget — so a tool-heavy current turn can't evict prior results."""
    prior = _prior_returns("p1", "p2")  # two prior returns (5 messages)
    current: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="now")])]
    for tid in ("c1", "c2", "c3"):  # three current tool calls — more than keep_recent
        current.append(
            ModelResponse(parts=[ToolCallPart(tool_name=tid, args={}, tool_call_id=tid)])
        )
        current.append(
            ModelRequest(parts=[ToolReturnPart(tool_name=tid, content=_HUGE, tool_call_id=tid)])
        )
    cc = CompactionContext(enabled=True, keep_recent=1, min_tokens=0)
    _seen, result = await _run(cc, prior + current, prompt=None, protect_from=len(prior))

    returns = _returns_by_tool(result.all_messages())
    assert returns["p2"] == _HUGE  # most-recent prior stays full despite 3 current returns
    assert "compacted" in returns["p1"]  # the older prior is digested
    assert all(returns[c] == _HUGE for c in ("c1", "c2", "c3"))  # current turn untouched
    assert set(cc.full_by_id) == {"p1"}


# --- rehydration: the model recovers a compacted result ---------------------


async def test_expand_tool_returns_the_full_original():
    def driver(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        recovered = any(
            isinstance(p, ToolReturnPart) and p.tool_name == EXPAND_TOOL
            for m in messages
            for p in m.parts
        )
        if recovered:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=EXPAND_TOOL, args={"tool_call_id": "old"}, tool_call_id="x1"
                )
            ]
        )

    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(
        cc,
        _prior_returns("old"),
        toolsets=build_agent_toolsets({"builtin": builtin_toolset()}),
        driver=driver,
    )

    # The expand tool's return (current turn) carries the full original verbatim.
    assert _returns_by_tool(result.all_messages())[EXPAND_TOOL] == _HUGE


async def test_expanded_output_is_not_permanently_exempt():
    """A prior-turn ``expand_tool_result`` output is itself eligible for compaction — there is no
    permanent exemption by tool name, so repeatedly expanding digests can't grow the history
    without bound; an aged-out expanded result just condenses again."""
    history: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="q")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=EXPAND_TOOL, args={"tool_call_id": "orig"}, tool_call_id="x1"
                )
            ]
        ),
        ModelRequest(
            parts=[ToolReturnPart(tool_name=EXPAND_TOOL, content=_HUGE, tool_call_id="x1")]
        ),
    ]
    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(cc, history)

    assert "compacted" in _returns_by_tool(result.all_messages())[EXPAND_TOOL]
    assert cc.full_by_id["x1"] == _HUGE


async def test_expand_tool_returns_structured_original_as_json():
    """A compacted *structured* result is rehydrated as JSON (not a Python ``repr``), so the
    model reads it faithfully."""
    big = {"a": [1, 2, 3], "b": "y" * 5000}

    def driver(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        recovered = any(
            isinstance(p, ToolReturnPart) and p.tool_name == EXPAND_TOOL
            for m in messages
            for p in m.parts
        )
        if recovered:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=EXPAND_TOOL, args={"tool_call_id": "struct"}, tool_call_id="x1"
                )
            ]
        )

    cc = CompactionContext(enabled=True, keep_recent=0, min_tokens=0)
    _seen, result = await _run(
        cc,
        _prior_returns("struct", content=big),
        toolsets=build_agent_toolsets({"builtin": builtin_toolset()}),
        driver=driver,
    )

    recovered = _returns_by_tool(result.all_messages())[EXPAND_TOOL]
    assert json.loads(recovered) == big


# --- config resolution ------------------------------------------------------


def test_build_compaction_context_resolves_defaults_and_overrides():
    settings = get_settings()
    default = build_compaction_context(settings)
    assert default.enabled == settings.compaction_enabled
    assert default.keep_recent == settings.compaction_keep_recent

    overridden = build_compaction_context(settings, enabled=False, keep_recent=99)
    assert overridden.enabled is False and overridden.keep_recent == 99
