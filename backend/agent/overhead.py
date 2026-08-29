"""Measuring what a request carries besides the conversation.

The tool definitions and the standing brief are the two parts of a model request that
never survive into the stored message history in a form anything downstream can size, so
this is measured mid-turn and carried on the Run rather than derived later from what was
persisted.

Both are measured **itemised** — the brief by contributing block, the schemas by tool
category — because the total is what the operator reads and the itemisation is what they
can act on. A brief that is 5k tells them nothing they can do; a brief that is 5k of
which 4k is the skill catalog tells them where to look. The totals are still carried
alongside, so a client that only draws the three-part bar needs nothing from the detail.

Characters, not tokens: the figures are used as proportions in
``services.context_budget``, and rounding each to tokens before comparing them would
throw away precision for nothing.
"""

from __future__ import annotations

import json
from typing import Any

from runs import BriefBlock, ToolGroupOverhead, TurnOverhead


def measure_overhead(ctx: Any, request: Any) -> TurnOverhead | None:
    """Size the standing brief and the tool schemas for the request that just went out.

    ``ctx`` is Pydantic AI's graph run context and ``request`` the ``ModelRequest`` the
    step streamed. Everything here reaches into library internals that carry no
    compatibility promise — the tool manager's prepared definitions, where the assembled
    instructions land — so **every failure is swallowed**: this exists to annotate a
    gauge, and an upgrade that moves an attribute must degrade the readout to
    "unmeasured", never break the turn that was producing it."""
    try:
        blocks = _brief_blocks(ctx, request)
        groups = _tool_groups(ctx)
        return TurnOverhead(
            system=sum(block.chars for block in blocks),
            tools=sum(group.chars for group in groups),
            blocks=blocks,
            groups=groups,
        )
    except Exception:
        return None


def _brief_blocks(ctx: Any, request: Any) -> tuple[BriefBlock, ...]:
    """The standing brief, split by what contributed it.

    Instructions and the system prompt are **one block** (``base``) rather than two. Both
    are the standing brief as far as the operator is concerned; the distinction between
    them (instructions are re-sent every turn and never retained in history, a system
    prompt is retained) is a durability decision this codebase makes, not something to
    split a readout by. What *is* worth splitting by is which feature put text there,
    because that is the thing the operator can switch off.

    Read off the **assembled request**, never by re-running the instruction providers.
    Those providers are functions that inspect live state — the repository, the active
    project — and calling them a second time to measure the length of what they returned
    would be doing real work for a readout, on top of risking a different answer than the
    one that was actually sent. That is also why the per-provider figures are collected
    at the moment each provider runs (the shim in ``agent/engine.py`` writes them onto
    the Run) rather than recovered here: by the time the request exists, the providers'
    contributions have been concatenated into one string with no seam to cut on.

    ``base`` is therefore the *remainder* — the fixed prompt, the date line, whatever the
    library joined them with — which keeps the blocks summing to the brief that was
    actually sent even when a provider went unmeasured."""
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

    # `ctx.deps` here is the library's own graph deps, which carries ours as `user_deps`
    # (the same object the tool manager hangs off). Both spellings are tried so this keeps
    # working if that indirection ever collapses.
    deps = getattr(ctx, "deps", None)
    run = getattr(getattr(deps, "user_deps", None), "run", None) or getattr(deps, "run", None)
    measured = dict(getattr(run, "instruction_blocks", None) or {})
    # A provider block can only be trusted up to the brief we actually saw: clamping the
    # remainder at zero keeps the blocks from summing past the total if a provider's text
    # was transformed on its way into the request.
    base = max(0, total - sum(measured.values()))
    blocks = [BriefBlock(id="base", chars=base)]
    blocks.extend(
        BriefBlock(id=name, chars=chars)
        for name, chars in sorted(measured.items())
        if chars > 0
    )
    return tuple(block for block in blocks if block.chars > 0)


def _tool_groups(ctx: Any) -> tuple[ToolGroupOverhead, ...]:
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
    is wrong-ish but harmless: it is still a row, still counted once, still summing.

    Read after the request node has streamed: the tool manager refuses to list its
    definitions until it has been prepared for the step."""
    chars: dict[str, int] = {}
    counts: dict[str, int] = {}
    for definition in ctx.deps.tool_manager.tool_defs:
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
