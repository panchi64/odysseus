"""Measuring what a request carries besides the conversation.

The tool definitions and the standing brief are the two parts of a model request that
never survive into the stored message history in a form anything downstream can size, so
this is measured as the request goes out and carried on the Run rather than derived later
from what was persisted.

Both are measured **itemised** — the brief by contributing block, the schemas by tool
category — because the total is what the operator reads and the itemisation is what they
can act on. A brief that is 5k tells them nothing they can do; a brief that is 5k of
which 4k is the skill catalog tells them where to look.

Characters, not tokens: the figures are used as proportions in
``services.context_budget``, and rounding each to tokens before comparing them would
throw away precision for nothing.

**This reads the assembled request through public API only.** Pydantic AI hands a
``before_model_request`` hook the exact ``ModelRequestParameters`` it is about to send —
the instruction parts with the id each was contributed under, the tool definitions, and
the outgoing message list. Nothing here reaches into a library internal, so an upgrade
that moves one is a type error at the seam rather than a readout that silently degrades.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic_ai import InstructionPart, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition

from runs import BriefBlock, ToolGroupOverhead, TurnOverhead
from tools.deps import RunDeps

#: The block the fixed prompt is filed under — everything in the brief that no named
#: provider claimed: our literal instructions, the system prompt, and the separators the
#: library joined the parts with.
BASE_BLOCK = "base"


@dataclass
class MeasureOverhead(AbstractCapability[RunDeps]):
    """Size the standing brief and the tool schemas for each request as it goes out.

    A capability rather than a step-end measurement because the hook is where the
    assembled request exists as *parts* — once they are on the wire the brief is one
    string with no seam to cut on, which is what the previous shim around every
    instruction provider existed to work around.

    Observes only: the request context is returned exactly as it arrived.
    """

    async def before_model_request(
        self, ctx: RunContext[RunDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        # Defensive on the deps hop alone: an agent built without our deps (a bare test
        # harness) costs the readout, never the turn. Everything below is total.
        run = getattr(ctx.deps, "run", None)
        if run is not None:
            params = request_context.model_request_parameters
            run.context_overhead = measure_overhead(
                params.instruction_parts, request_context.messages, params.function_tools
            )
        return request_context


def measure_overhead(
    instruction_parts: list[InstructionPart] | None,
    messages: list[ModelMessage],
    function_tools: list[ToolDefinition],
) -> TurnOverhead:
    blocks = _brief_blocks(instruction_parts, messages)
    groups = _tool_groups(function_tools)
    return TurnOverhead(
        system=sum(block.chars for block in blocks),
        tools=sum(group.chars for group in groups),
        blocks=blocks,
        groups=groups,
    )


def _brief_blocks(
    instruction_parts: list[InstructionPart] | None, messages: list[ModelMessage]
) -> tuple[BriefBlock, ...]:
    """The standing brief, split by what contributed it.

    Instructions and the system prompt are **one block** (``base``) rather than two. Both
    are the standing brief as far as the operator is concerned; the distinction between
    them (instructions are re-sent every turn and never retained in history, a system
    prompt is retained) is a durability decision this codebase makes, not something to
    split a readout by. What *is* worth splitting by is which feature put text there,
    because that is the thing the operator can switch off.

    Each provider is registered with a ``name`` (``agent/engine.py``), so the library
    stamps its resolved part with ``InstructionId(AgentInstructionSource(), name=…)`` and
    the row is read straight off the part. A part with no name — our own literal
    instructions — falls into ``base``, as do the separators ``join`` puts between parts,
    which is why the total is taken from the joined string rather than from the sum of
    the parts: the blocks then sum to the brief that was actually sent."""
    parts = instruction_parts or []
    total = len(InstructionPart.join(parts) or "")
    # The system prompt is only ever at the head of the history — a later
    # `SystemPromptPart` would be a second brief, which this codebase never sends — and it
    # is not on the request for any step after the first, so the history is where it is read.
    for message in messages:
        for part in getattr(message, "parts", ()):
            if type(part).__name__ == "SystemPromptPart":
                content = getattr(part, "content", "")
                total += len(content) if isinstance(content, str) else 0

    named: dict[str, int] = {}
    for part in parts:
        name = part.id.name if part.id is not None else None
        if name:
            named[name] = named.get(name, 0) + len(part.content)
    base = max(0, total - sum(named.values()))
    blocks = [BriefBlock(id=BASE_BLOCK, chars=base)]
    blocks.extend(BriefBlock(id=name, chars=chars) for name, chars in sorted(named.items()))
    return tuple(block for block in blocks if block.chars > 0)


def _tool_groups(function_tools: list[ToolDefinition]) -> tuple[ToolGroupOverhead, ...]:
    """Every tool definition the model was handed, serialized and grouped by category.

    The JSON here is our own rendering, not the exact bytes any one provider puts on the
    wire — each wraps the same name/description/schema differently. It is the right
    *proportion* regardless, which is all this is used as, and the alternative (a
    per-provider serializer kept in step with four SDKs) would be precision the readout
    can't spend.

    The grouping is by namespace prefix, because ``tools/toolsets.py`` builds every name
    as ``category_tool`` and category names carry no underscore of their own. That makes
    the readout's rows line up exactly with the rows on the operator's tool settings page
    — the point of the split being that "``external`` is 40% of your window" is only
    useful if there is a single switch labelled ``external`` to go and find. A tool
    registered outside the namespacing (none today) lands under its own first word, which
    is wrong-ish but harmless: it is still a row, still counted once, still summing."""
    chars: dict[str, int] = {}
    counts: dict[str, int] = {}
    for definition in function_tools:
        category = definition.name.split("_", 1)[0]
        chars[category] = chars.get(category, 0) + len(
            json.dumps(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.parameters_json_schema,
                },
                default=str,
            )
        )
        counts[category] = counts.get(category, 0) + 1
    return tuple(
        ToolGroupOverhead(category=category, tools=counts[category], chars=size)
        for category, size in sorted(chars.items())
    )
