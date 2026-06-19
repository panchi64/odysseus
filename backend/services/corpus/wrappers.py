"""Adapter wrappers — plug the existing rich stores into the corpus seam.

The whole point of ADAPTER-UNIFIED: ``MemoryStore`` and ``ConversationSearch`` already
do hybrid recall over their own encrypted tables, so they enroll into the corpus
**untouched, zero migration** — a thin wrapper translates their hit shape to
:class:`CorpusHit` and their counts to :class:`SourceStatus`. They embed on their own
write path, so ``reindex`` delegates to their existing re-embed (memory) or is a no-op
(the conversation index re-embeds via its own coordinator).

The stub *surface* adapters (uploads, gallery, research) exist so the ``/rag`` source
list shows every planned surface from day one, but they hold no content yet (extraction
pipelines are deferred): ``retrieve`` returns nothing and ``status`` reports a stale,
empty source. Each fills in as its surface is built — documents already has, with its
real adapter in ``corpus/documents.py``, so it is no longer stubbed here.
"""

from __future__ import annotations

import numpy as np

from services.conversation_search import ConversationSearch
from services.corpus.adapter import CorpusHit, SourceAdapter, SourceStatus
from services.memory import MemoryStore


class MemoryAdapter(SourceAdapter):
    """Long-term memory as a corpus source — wraps :class:`MemoryStore`."""

    source_kind = "memory"
    SOURCE_ID = "surf-memory"

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def retrieve(
        self,
        owner_id: str,
        query: str,
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        *,
        limit: int,
    ) -> list[CorpusHit]:
        # MemoryStore.recall embeds + hybrid-fuses internally, so it takes the raw query
        # string (not the index's pre-computed vector). Its hits come back ranked; the
        # index fuses this list with the others by rank.
        hits = await self._store.recall(owner_id, query, limit=limit)
        return [
            CorpusHit(
                gid=f"{self.SOURCE_ID}:{hit.memory.id}",
                source_id=self.SOURCE_ID,
                ref=hit.memory.id,
                text=hit.memory.content,
                score=hit.score,
                matched_by=hit.matched_by,
            )
            for hit in hits
        ]

    async def status(self, owner_id: str) -> SourceStatus:
        count = await self._store.count(owner_id)
        return SourceStatus(
            source_id=self.SOURCE_ID,
            kind="surface",
            label="Memory",
            doc_count=count,
            status="indexed",
            last_indexed_at=None,
            href="/memory",
        )

    async def reindex(self, owner_id: str, *, current_model: str | None = None) -> int:
        return await self._store.reembed(owner_id, current_model=current_model)


class ConversationAdapter(SourceAdapter):
    """Cross-chat history as a corpus source — wraps :class:`ConversationSearch`."""

    source_kind = "conversations"
    SOURCE_ID = "surf-conversations"

    def __init__(self, search: ConversationSearch) -> None:
        self._search = search

    async def retrieve(
        self,
        owner_id: str,
        query: str,
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        *,
        limit: int,
    ) -> list[CorpusHit]:
        # ConversationSearch.search embeds + hybrid-fuses internally; it takes the raw
        # query and returns hits already ranked (one per conversation).
        hits = await self._search.search(owner_id, query, limit=limit)
        return [
            CorpusHit(
                gid=f"{self.SOURCE_ID}:{hit.conversation_id}",
                source_id=self.SOURCE_ID,
                ref=hit.conversation_id,
                text=hit.snippet,
                score=hit.score,
                matched_by=hit.matched_by,
            )
            for hit in hits
        ]

    async def status(self, owner_id: str) -> SourceStatus:
        return SourceStatus(
            source_id=self.SOURCE_ID,
            kind="surface",
            label="Conversations",
            doc_count=0,
            status="indexed",
            last_indexed_at=None,
            href="/chat",
        )


class StubSurfaceAdapter(SourceAdapter):
    """A planned in-app surface with no content yet — listed but empty.

    Uploads, gallery, and research each get one of these until their extraction
    pipeline lands (deferred). ``retrieve`` returns nothing; ``status`` reports a stale,
    empty source so the ``/rag`` list shows it as awaiting build-out.
    """

    source_kind = "surface"

    def __init__(self, source_id: str, label: str, icon: str, href: str) -> None:
        self.SOURCE_ID = source_id
        self._label = label
        self._icon = icon
        self._href = href

    async def retrieve(
        self,
        owner_id: str,
        query: str,
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        *,
        limit: int,
    ) -> list[CorpusHit]:
        return []

    async def status(self, owner_id: str) -> SourceStatus:
        return SourceStatus(
            source_id=self.SOURCE_ID,
            kind="surface",
            label=self._label,
            doc_count=0,
            status="stale",
            last_indexed_at=None,
            href=self._href,
        )


def default_surface_stubs() -> list[StubSurfaceAdapter]:
    """The planned content surfaces, each a stub until its pipeline is built."""
    return [
        StubSurfaceAdapter("surf-gallery", "Gallery", "image", "/gallery"),
        StubSurfaceAdapter("surf-research", "Research", "research", "/research"),
    ]
