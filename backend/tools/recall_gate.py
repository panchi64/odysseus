"""The context-control gate shared by every global-recall tool (AE-3.8).

Global, relevance-ranked recall over the operator's corpus — memory, past
conversations, indexed folders/uploads/documents — pulls untrusted knowledge-base
content into the model's context, so it pauses for operator approval: a denial keeps
that content out of context. The gate lives here, not inline per tool, so every recall
surface (``corpus.retrieve``'s global path, ``memory.recall``, ``conversations.search``)
enforces it identically and a future refinement lands in one place.

An explicit-id read — a source the operator already referenced, e.g. a file attached to
the turn, or one conversation read by id after a search — is *not* global recall and
passes through ungated.

The gate raises ``ApprovalRequired``, which only *defers* (rather than erroring) when the
composing agent's ``output_type`` admits ``DeferredToolRequests`` — as the chat engine's
agent does. A recall toolset must only be composed into such an agent.
"""

from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ApprovalRequired

from .deps import RunDeps


def gate_global_recall(ctx: RunContext[RunDeps]) -> None:
    """Pause a global recall for operator approval unless it was already approved.
    ``tool_call_approved`` is set on the re-invocation after an approval, so this raises
    once and then lets the recall run."""
    if not ctx.tool_call_approved:
        raise ApprovalRequired()
