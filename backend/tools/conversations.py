"""Cross-chat tools — the agent's thin adapter over conversation search.

Two verbs, both thin pass-throughs to
:class:`~services.conversation_search.ConversationSearch` reached via ``RunDeps``:
``search`` finds the operator's *other* conversations by meaning (with keyword
fallback), and ``read`` pulls a found conversation's full transcript. Search
always excludes the current thread — the agent already has that in context.

If the capability isn't wired into the run, the tools say so rather than failing
(graceful degradation), and the model adapts.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, RunContext

from services.conversation_search import ConversationSearch

from .deps import RunDeps
from .recall_gate import gate_global_recall


def conversations_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def search(ctx: RunContext[RunDeps], query: str, limit: int = 5) -> list[dict]:
        """Search the operator's other chat conversations and return the best
        matching ones (title, an excerpt, and a conversation id to read in full).

        Use this to recall what was discussed in a *different* chat. An empty list
        means nothing matched — conclude from that rather than rephrasing endlessly.
        Pass a conversation id from a result to ``conversations_read`` for the full
        thread."""
        # Relevance recall across the operator's other conversations is global
        # knowledge-base recall, so it is approval-gated (AE-3.8) like the corpus read.
        # ``read`` below is an explicit-id read of one already-surfaced thread, so it
        # passes through ungated.
        gate_global_recall(ctx)
        svc = ctx.deps.caps.get_optional(ConversationSearch)
        if svc is None:
            return [{"error": "Conversation search is unavailable."}]
        hits = await svc.search(
            ctx.deps.owner_id,
            query,
            limit=limit,
            exclude_conversation_id=ctx.deps.conversation_id,
        )
        return [
            {
                "conversation_id": h.conversation_id,
                # A conversation may not be auto-titled yet; never hand the model a
                # null title (mirrors `read`'s fallback) so it can still refer to it.
                "title": h.title or "(untitled conversation)",
                "snippet": h.snippet,
                "matched_by": h.matched_by,
            }
            for h in hits
        ]

    @toolset.tool
    async def read(ctx: RunContext[RunDeps], conversation_id: str) -> str:
        """Read the full transcript of one of the operator's conversations by id
        (get the id from a ``conversations_search`` result)."""
        svc = ctx.deps.caps.get_optional(ConversationSearch)
        if svc is None:
            return "Conversation search is unavailable."
        transcript = await svc.read(ctx.deps.owner_id, conversation_id)
        if transcript is None:
            return f"No conversation found for id {conversation_id!r}."
        header = transcript.title or "(untitled conversation)"
        return f"# {header}\n\n{transcript.text}"

    return toolset
