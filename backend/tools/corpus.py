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

from .deps import RunDeps


def corpus_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def retrieve(ctx: RunContext[RunDeps], query: str, limit: int = 8) -> list[dict]:
        """Retrieve relevant passages from the knowledge corpus (folders, memory, and
        past conversations) by meaning, with a keyword fallback."""
        index = ctx.deps.corpus
        if index is None:
            return [{"error": "The knowledge corpus is unavailable."}]
        hits = await index.retrieve(ctx.deps.owner_id, query, limit=limit)
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
