"""Translate Pydantic AI's native run into our event protocol (Pillar II).

This is the seam where the *engine* becomes the *product stream*. We drive the
run via ``agent.iter()`` so we can observe each graph node, and turn the
library's events into our domain events:

- a ``ModelRequestNode`` is one **step** (step.started/completed around it);
- text parts → ``answer.delta``, thinking parts → ``thinking.delta`` (the
  reasoning/answer split);
- a ``CallToolsNode`` surfaces tool execution → ``tool.started`` /
  ``tool.completed`` / ``tool.failed`` with full args/results inline.

Step boundaries, document lifecycle, citations, and run metrics are *ours* —
the library doesn't know about them; we emit them here and in the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from core.serde import jsonable
from runs import (
    AnswerDelta,
    CitationAdded,
    Run,
    StepCompleted,
    StepStarted,
    ThinkingDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from services.search import SearchResult, SearchResults
from services.webfetch import FetchedPage

from .meta import LoopBreaker


def citations_from_tool_result(name: str, content: Any) -> list[CitationAdded]:
    """Sources a completed ``web_search``/``web_fetch`` call surfaced, in result order.
    Anything else (a degraded-capability string, an unrecognized tool) yields none — this
    is additive, never load-bearing. Cross-call dedup and the Sources-row numbering are the
    consumer's concern (the run's citation fold dedups by URL; the row numbers by position),
    so this neither dedups nor assigns an index — ``web_search`` results are already
    URL-unique from the service, and ``web_fetch`` is a single page."""
    if name == "web_search" and isinstance(content, SearchResults):
        return [
            CitationAdded(url=item.url, title=item.title)
            for item in content.results
            if isinstance(item, SearchResult)
        ]
    if name == "web_fetch" and isinstance(content, FetchedPage):
        return [CitationAdded(url=content.url, title=content.title)]
    return []


def _on_model_event(event: object, run: Run) -> None:
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart) and part.content:
            run.answer_started = True  # pins the endpoint past this point (AE-5.3)
            run.emit(AnswerDelta(text=part.content))
        elif isinstance(part, ThinkingPart) and part.content:
            run.emit(ThinkingDelta(text=part.content))
    elif isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta) and delta.content_delta:
            run.answer_started = True  # pins the endpoint past this point (AE-5.3)
            run.emit(AnswerDelta(text=delta.content_delta))
        elif isinstance(delta, ThinkingPartDelta) and delta.content_delta:
            run.emit(ThinkingDelta(text=delta.content_delta))
    # PartEndEvent / FinalResultEvent / ToolCallPart streaming carry no domain
    # signal we surface — tool execution is reported from the CallToolsNode.


def _on_tool_event(
    event: object, run: Run, announced: set[str] | None, loop_breaker: LoopBreaker | None
) -> None:
    if isinstance(event, FunctionToolCallEvent):
        part = event.part
        # No-progress guard: trips before we announce a looping call.
        if loop_breaker is not None:
            loop_breaker.check(part.tool_name, part.args_as_dict())
        # tool.started is idempotent per run: an approval-deferred call re-fires
        # its call event on the resume turn, so announce each id once.
        if announced is not None and part.tool_call_id in announced:
            return
        if announced is not None:
            announced.add(part.tool_call_id)
        run.emit(
            ToolStarted(
                tool_call_id=part.tool_call_id,
                name=part.tool_name,
                args=part.args_as_dict(),
            )
        )
    elif isinstance(event, FunctionToolResultEvent):
        part = event.part
        if isinstance(part, RetryPromptPart):
            run.emit(
                ToolFailed(
                    tool_call_id=part.tool_call_id,
                    name=part.tool_name or "",
                    error=part.model_response(),
                )
            )
        else:
            run.emit(
                ToolCompleted(
                    tool_call_id=part.tool_call_id,
                    name=part.tool_name,
                    result=jsonable(part.content),
                )
            )
            for citation in citations_from_tool_result(part.tool_name, part.content):
                run.emit(citation)


async def stream_agent_run(
    agent_run: Any,
    run: Run,
    *,
    announced: set[str] | None = None,
    loop_breaker: LoopBreaker | None = None,
    on_step: Callable[[list[ModelMessage]], None] | None = None,
) -> None:
    """Iterate the AgentRun's graph nodes, emitting our events as they happen.

    ``announced`` (a set of tool_call_ids already surfaced as ``tool.started``)
    is threaded across a turn-chain so an approval-deferred call is announced
    once even though its call event re-fires on resume. ``loop_breaker``, if
    given, raises :class:`LoopDetected` to abort a no-progress turn. ``on_step``,
    if given, is called with the accumulated history after each model response —
    the engine uses it to emit a live context/usage frame as the turn progresses.
    """
    step = 0
    async for node in agent_run:
        if Agent.is_model_request_node(node):
            step += 1
            run.emit(StepStarted(index=step))
            async with node.stream(agent_run.ctx) as stream:
                async for event in stream:
                    _on_model_event(event, run)
            run.emit(StepCompleted(index=step))
            if on_step is not None:
                on_step(agent_run.ctx.state.message_history)
        elif Agent.is_call_tools_node(node):
            async with node.stream(agent_run.ctx) as stream:
                async for event in stream:
                    _on_tool_event(event, run, announced, loop_breaker)
        # UserPromptNode / End nodes have nothing to stream.
