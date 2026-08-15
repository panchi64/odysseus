"""Corpus tool — the agent's unified read across every knowledge source.

A single ``retrieve`` verb, a thin pass-through to :class:`~services.corpus.CorpusIndex`
reached via ``RunDeps``. Because the index registers the memory + conversation adapters
alongside the folder source, this one tool is the agent's read across *all* of them
(memory's ``remember``/``recall`` stay as the write/fact surface — this augments, not
replaces, them).

Each hit's text is folder/file content — **external data**, so it is wrapped with
:func:`core.untrusted.wrap_untrusted` before it reaches the model (the corpus is an
untrusted-content ingester, like web). A missing capability degrades to an "unavailable"
message rather than failing.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, RunContext

from core.untrusted import wrap_untrusted
from services.corpus import CorpusIndex

from .deps import RunDeps
from .recall_gate import gate_global_recall


def corpus_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def retrieve(
        ctx: RunContext[RunDeps],
        query: str,
        limit: int = 8,
        source_ids: list[str] | None = None,
    ) -> list[dict]:
        """Retrieve relevant passages from the knowledge corpus (folders, memory, uploaded
        files, and past conversations) by meaning, with a keyword fallback. ``source_ids``
        scopes the search to specific file sources by id — e.g. a file attached to this
        conversation, whose id appears in its attachment marker; an explicit-id read returns
        the file even if it's been excluded from the knowledge base. Leave ``source_ids``
        unset for normal recall across every source."""
        # Global recall (no explicit source) pulls untrusted knowledge-base content into
        # the operator's context, so it is approval-gated (AE-3.8) — the operator can deny
        # a search they know is irrelevant before its hits reach the model. An explicit-id
        # read is content the operator already chose to provide (an attached file), so it
        # passes through. ``not source_ids`` covers both an unset list and an empty one,
        # which line 53 also collapses to a global recall.
        if not source_ids:
            gate_global_recall(ctx)
        index = ctx.deps.caps.get_optional(CorpusIndex)
        if index is None:
            return [{"error": "The knowledge corpus is unavailable."}]
        hits = await index.retrieve(
            ctx.deps.owner_id, query, source_ids=source_ids or None, limit=limit
        )
        return [
            {
                "source": hit.source_id,
                "ref": hit.ref,
                "matched_by": hit.matched_by,
                "text": wrap_untrusted(hit.text, source=hit.ref),
            }
            for hit in hits
        ]

    return toolset
