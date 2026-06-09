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

import json
from typing import Any

from pydantic_ai import (
    Agent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from runs import (
    AnswerDelta,
    Run,
    StepCompleted,
    StepStarted,
    ThinkingDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)

from .meta import LoopBreaker


def _jsonable(value: Any) -> Any:
    """Coerce a tool result into something the JSON envelope can carry."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _on_model_event(event: object, run: Run) -> None:
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart) and part.content:
            run.emit(AnswerDelta(text=part.content))
        elif isinstance(part, ThinkingPart) and part.content:
            run.emit(ThinkingDelta(text=part.content))
    elif isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta) and delta.content_delta:
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
                    result=_jsonable(part.content),
                )
            )


async def stream_agent_run(
    agent_run: Any,
    run: Run,
    *,
    announced: set[str] | None = None,
    loop_breaker: LoopBreaker | None = None,
) -> None:
    """Iterate the AgentRun's graph nodes, emitting our events as they happen.

    ``announced`` (a set of tool_call_ids already surfaced as ``tool.started``)
    is threaded across a turn-chain so an approval-deferred call is announced
    once even though its call event re-fires on resume. ``loop_breaker``, if
    given, raises :class:`LoopDetected` to abort a no-progress turn.
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
        elif Agent.is_call_tools_node(node):
            async with node.stream(agent_run.ctx) as stream:
                async for event in stream:
                    _on_tool_event(event, run, announced, loop_breaker)
        # UserPromptNode / End nodes have nothing to stream.
