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

from agent.overhead import measure_overhead
from core.citations import Citable
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

from .meta import LoopBreaker


def citations_from_tool_result(content: Any) -> list[CitationAdded]:
    """Sources a completed tool call surfaced, in the order the result gave them.

    A result declares its own sources by implementing :class:`~core.citations.Citable`;
    anything else (a degraded-capability string, a tool with nothing to cite) yields none —
    this is additive, never load-bearing. Asking the result rather than matching on tool
    names keeps this translator out of the business of knowing which features cite things:
    a new tool that returns a citable result is surfaced the day it lands, and Pillar II
    needn't import a feature's service types to recognize it.

    Cross-call dedup and the Sources-row numbering are the consumer's concern (the run's
    citation fold dedups by URL; the row numbers by position), so this neither dedups nor
    assigns an index.
    """
    if not isinstance(content, Citable):
        return []
    return [CitationAdded(url=c.url, title=c.title) for c in content.citations()]


def _on_model_event(event: object, run: Run, mark_first_token: Callable[[], None]) -> None:
    """``mark_first_token`` is called for the first output of **any** kind and only
    counts once (see ``TurnTimer.model_request``).

    Any kind is deliberate, and wider than it first looks. Reasoning counts, because on
    a thinking model the reasoning is what arrives first and timing to the first *answer*
    token would bill the whole thinking pass as latency. **Tool calls count too**, even
    though nothing else in this function acts on them: a response that only calls a tool
    has still finished processing the prompt and started emitting: If it reported no
    first token, its entire duration — prefill included — would land in the "generating"
    side of the throughput calculation that subtracts TTFT from the round-trip, and a
    tool-heavy thread would report a decode rate well under the truth.

    So the mark is driven by the event arriving at all, not by what we do with it."""
    if isinstance(event, PartStartEvent | PartDeltaEvent):
        mark_first_token()
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
    # PartEndEvent / FinalResultEvent carry no domain signal we surface — tool
    # execution is reported from the CallToolsNode.


def _on_tool_event(
    event: object, run: Run, announced: set[str] | None, loop_breaker: LoopBreaker | None
) -> None:
    if isinstance(event, FunctionToolCallEvent):
        part = event.part
        # tool.started is idempotent per run: an approval-deferred call re-fires
        # its call event on the resume turn, so announce each id once.
        if announced is not None and part.tool_call_id in announced:
            return
        if announced is not None:
            announced.add(part.tool_call_id)
        # No-progress guard: trips before we announce a looping call — and *after* the
        # dedupe above, so the re-fired event of a deferred call isn't counted a second
        # time. Counting it twice would halve the effective repeat threshold for every
        # tool an approval grant auto-approves, since those hops share one LoopBreaker.
        if loop_breaker is not None:
            loop_breaker.check(part.tool_name, part.args_as_dict())
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
            for citation in citations_from_tool_result(part.content):
                run.emit(citation)


async def stream_agent_run(
    agent_run: Any,
    run: Run,
    *,
    announced: set[str] | None = None,
    loop_breaker: LoopBreaker | None = None,
    on_step: Callable[[list[ModelMessage]], None] | None = None,
    on_request_node: Callable[[Any], None] | None = None,
) -> None:
    """Iterate the AgentRun's graph nodes, emitting our events as they happen.

    ``announced`` (a set of tool_call_ids already surfaced as ``tool.started``)
    is threaded across a turn-chain so an approval-deferred call is announced
    once even though its call event re-fires on resume. ``loop_breaker``, if
    given, raises :class:`LoopDetected` to abort a no-progress turn. ``on_step``,
    if given, is called with the accumulated history after each model response —
    the engine uses it to emit a live context/usage frame as the turn progresses.
    ``on_request_node``, if given, is called with each yielded ``ModelRequestNode``
    *before* it streams — the request isn't in flight yet and hasn't been appended
    to the history, so the callback may still amend ``node.request.parts`` (the
    engine injects mid-run operator messages here).

    Wall-clock is collected into ``run.timer`` as the nodes are walked: this is the
    only place that sees both node boundaries, so it is where the stopwatch belongs,
    and the run owns it so an approval that splits a turn into several segments still
    accumulates one total.
    """
    step = 0
    timer = run.timer
    async for node in agent_run:
        if Agent.is_model_request_node(node):
            if on_request_node is not None:
                on_request_node(node)
            step += 1
            run.emit(StepStarted(index=step))
            with timer.model_request() as mark_first_token:
                async with node.stream(agent_run.ctx) as stream:
                    async for event in stream:
                        _on_model_event(event, run, mark_first_token)
            run.emit(StepCompleted(index=step))
            # Measured here and nowhere else: the tool manager only lists its definitions
            # once it has been prepared for a step, and neither the schemas nor the
            # instructions ever reach the message history — so this is the one moment the
            # request's non-conversation weight is visible. Re-measured each step because
            # a turn's tool set can change under it (a mode switch, a toolset that
            # prepares differently), and the gauge should describe the request that just
            # went out rather than the first one of the turn.
            run.context_overhead = measure_overhead(agent_run.ctx, node.request)
            if on_step is not None:
                on_step(agent_run.ctx.state.message_history)
        elif Agent.is_call_tools_node(node):
            # Timed as a batch, not per call: the node runs its calls concurrently, so
            # summing them individually would report more tool time than elapsed.
            with timer.tool_calls():
                async with node.stream(agent_run.ctx) as stream:
                    async for event in stream:
                        _on_tool_event(event, run, announced, loop_breaker)
        # UserPromptNode / End nodes have nothing to stream.
