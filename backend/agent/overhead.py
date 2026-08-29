"""Measuring what a request carries besides the conversation.

The tool definitions and the standing brief are the two parts of a model request that
never survive into the stored message history in a form anything downstream can size, so
this is measured mid-turn and carried on the Run rather than derived later from what was
persisted.

Characters, not tokens: the figures are used as proportions in
``services.context_budget``, and rounding each to tokens before comparing them would
throw away precision for nothing.
"""

from __future__ import annotations

import json
from typing import Any

from runs import TurnOverhead


def measure_overhead(ctx: Any, request: Any) -> TurnOverhead | None:
    """Size the standing brief and the tool schemas for the request that just went out.

    ``ctx`` is Pydantic AI's graph run context and ``request`` the ``ModelRequest`` the
    step streamed. Everything here reaches into library internals that carry no
    compatibility promise — the tool manager's prepared definitions, where the assembled
    instructions land — so **every failure is swallowed**: this exists to annotate a
    gauge, and an upgrade that moves an attribute must degrade the readout to
    "unmeasured", never break the turn that was producing it."""
    try:
        return TurnOverhead(system=_system_chars(ctx, request), tools=_tool_chars(ctx))
    except Exception:
        return None


def _system_chars(ctx: Any, request: Any) -> int:
    """Instructions plus system prompt, as one figure.

    Both are the standing brief as far as the operator is concerned; the distinction
    between them (instructions are re-sent every turn and never retained in history, a
    system prompt is retained) is a durability decision this codebase makes, not something
    to split a readout by.

    Read off the **assembled request**, never by re-running the instruction providers.
    Those providers are functions that inspect live state — the repository, the active
    project — and calling them a second time to measure the length of what they returned
    would be doing real work for a readout, on top of risking a different answer than the
    one that was actually sent."""
    instructions = getattr(request, "instructions", None) or ""
    total = len(instructions)
    # The system prompt is only ever at the head of the history — a later
    # `SystemPromptPart` would be a second brief, which this codebase never sends — and it
    # is not on `request` for any step after the first, so the history is where it is read.
    for message in ctx.state.message_history:
        for part in getattr(message, "parts", ()):
            if type(part).__name__ == "SystemPromptPart":
                content = getattr(part, "content", "")
                total += len(content) if isinstance(content, str) else 0
    return total


def _tool_chars(ctx: Any) -> int:
    """Every tool definition the model was handed, serialized.

    The JSON here is our own rendering, not the exact bytes any one provider puts on the
    wire — each wraps the same name/description/schema differently. It is the right
    *proportion* regardless, which is all this is used as, and the alternative (a
    per-provider serializer kept in step with four SDKs) would be precision the readout
    can't spend.

    Read after the request node has streamed: the tool manager refuses to list its
    definitions until it has been prepared for the step."""
    return sum(
        len(
            json.dumps(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.parameters_json_schema,
                },
                default=str,
            )
        )
        for definition in ctx.deps.tool_manager.tool_defs
    )
