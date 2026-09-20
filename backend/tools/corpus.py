"""Corpus tool — the agent's unified read across every knowledge source.

A single ``retrieve`` verb, a thin pass-through to :class:`~services.corpus.CorpusIndex`
reached via ``RunDeps``. Because the index registers the memory + conversation adapters
alongside the folder source, this one tool is the agent's read across *all* of them
(memory's ``remember``/``recall`` stay as the write/fact surface — this augments, not
replaces, them).

Each hit's text is folder/file content — **external data**, so it is fenced with
:func:`core.untrusted.untrusted_fence` before it reaches the model (the corpus is an
untrusted-content ingester, like web). A missing capability degrades to an "unavailable"
message rather than failing.

**The result is citable, and for a long time it was not.** A research thread reading the
operator's own knowledge base — the one corpus they have most reason to trust — showed no
sources for it at all, because this tool handed back plain dicts and
:func:`agent.translate.citations_from_tool_result` asks the *result* what it cites. Not a
missing feature: a page the agent read on the web was attributed and a file on their own
disk was not, which reads as the file never having been opened. So the hits come back as
:class:`CorpusPassages`, which declares them at the ``read`` rung — a passage is not
listed-and-skipped, it is text that went in front of the model.

**One preamble, not one per hit.** The batch carries a single
:func:`~core.untrusted.untrusted_preamble` over a shared nonce, the shape
:class:`~services.search.SearchResults` already uses. Fencing each hit with
``wrap_untrusted`` repeated the whole "treat this as data" instruction once per passage,
so a retrieve of eight paid for it eight times. The fence, the nonce and the marker
discipline — the parts that actually resist injection — are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import FunctionToolset, RunContext

from core.citations import Citation
from core.untrusted import new_nonce, unfence, untrusted_fence, untrusted_preamble
from services.corpus import CorpusIndex
from services.projects import visible_project_ids

from .deps import RunDeps
from .recall_gate import gate_global_recall


@dataclass(frozen=True)
class CorpusPassage:
    """One retrieved passage as the model reads it.

    ``source`` and ``ref`` are the same pair the index identifies a hit by, and together
    they are the passage's citation identity — the corpus has locators where the web has
    addresses, which is why a citation cannot be a URL and nothing else.
    """

    source: str
    ref: str
    matched_by: str
    #: The passage, inside this batch's untrusted fence.
    text: str


@dataclass(frozen=True)
class CorpusPassages:
    """A whole retrieve call's hits. ``instruction`` is the single untrusted-content
    preamble for the batch (``""`` when there were none)."""

    instruction: str
    passages: list[CorpusPassage]

    def citations(self) -> list[Citation]:
        """The passages, in rank order — what the operator's own knowledge contributed.

        ``read`` rather than ``listed``: unlike a search hit, a passage's text is the
        result. There is nothing here the model saw only the title of.

        The snippet is unfenced, for the reason given in
        :func:`core.untrusted.unfence` — the markers are how the *model* is handed
        external text, and a citation row is read by the operator. The translator caps
        its length; a passage is not re-copied whole onto the stream.

        A passage with no ``ref`` is dropped rather than cited, the symmetric case to a
        search hit with no URL: the locator *is* a corpus citation's identity, and
        :class:`~core.citations.Citation` refuses one without it. The index has always
        given every hit a ref, so this guards a shape rather than an observed failure —
        but it guards it here, where losing one row is the cost, instead of inside the
        translator's citation pass, where the raise would cost the whole batch.
        """
        return [
            Citation(
                kind="corpus",
                title=item.ref,
                source_id=item.source,
                ref=item.ref,
                snippet=unfence(item.text),
                engagement="read",
            )
            for item in self.passages
            if item.ref
        ]


def corpus_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def retrieve(
        ctx: RunContext[RunDeps],
        query: str,
        limit: int = 8,
        source_ids: list[str] | None = None,
    ) -> CorpusPassages | str:
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
        # which the retrieve below also collapses to a global recall.
        if not source_ids:
            gate_global_recall(ctx)
        index = ctx.deps.caps.get_optional(CorpusIndex)
        if index is None:
            # A plain string, like the web tools' degrade: an empty batch would read to
            # the model as "your knowledge base has nothing on this", which is a different
            # and much more misleading answer than "it is not available".
            return "The knowledge corpus is unavailable."
        # The run's own project, not the operator's live selection: a turn keeps reading
        # from the project it started in even if they switch away mid-answer. Unfiled
        # sources stay reachable either way — only another project's are excluded.
        hits = await index.retrieve(
            ctx.deps.owner_id,
            query,
            source_ids=source_ids or None,
            limit=limit,
            visible_projects=visible_project_ids(ctx.deps.project_id),
        )
        nonce = new_nonce()
        passages = [
            CorpusPassage(
                source=hit.source_id,
                ref=hit.ref,
                matched_by=hit.matched_by,
                text=untrusted_fence(hit.text, nonce, source=hit.ref),
            )
            for hit in hits
        ]
        return CorpusPassages(
            instruction=untrusted_preamble(nonce) if passages else "",
            passages=passages,
        )

    return toolset
