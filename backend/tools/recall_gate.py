"""The context-control gate shared by the global-recall tools (AE-3.8).

Global, relevance-ranked recall over indexed folders, uploads and past conversations
pulls content the operator did not write into the model's context, so it pauses for
approval: a denial keeps that content out. The gate lives here, not inline per tool, so
both surfaces (``corpus_retrieve``'s global path and ``conversations_search``) enforce it
identically and a future refinement lands in one place.

``memory_recall`` is deliberately **not** one of them. Long-term memory holds only what
this agent was told to remember on the operator's behalf — their own notes, never a
document someone else wrote — so there is nothing there to keep out, and gating it bought
a park on the one lookup the agent needs most often to answer in the operator's own terms.

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
