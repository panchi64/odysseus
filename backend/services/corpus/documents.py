"""The documents source — index document bodies into the corpus.

The in-app counterpart to :class:`~services.corpus.folder.FolderAdapter`: instead of
crawling a host path, it indexes the operator's **documents** (the `DOC-*` library) so
the agent retrieves them through the one ``corpus.retrieve`` tool. The bodies are
chunked (token-window + overlap) and sealed into the generic ``corpus_chunk`` store,
exactly as folders are.

Each document is its own ``source_id`` (the document id) under the shared
``source_kind="documents"``, so one document's chunks are addressable on their own —
which is what lets an edit re-index just that document. Indexing runs on the same
lock-aware :class:`~core.worker.WriteBehindWorker` the folder source uses: writes
submit a job, the worker drains it off the request path and **parks while the vault is
locked** (it seals chunk text + vectors).

**The one deviation from the folder source:** an edit must *clear then re-insert* a
document's chunks, not just upsert. ``CorpusChunkStore.upsert`` is additive and dedups
by content hash, so a folder rebuild (which re-crawls the whole tree) never strands a
row. A single document edit that *shortens* the body would leave the removed text's
chunks behind — so every index job deletes the document's existing chunks first, then
inserts the current body's. At document scale a full re-chunk is cheap, and it keeps the
index honest about what the document says now.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import Engine

from core.worker import WriteBehindWorker
from services.chunking import chunk_text
from services.corpus.adapter import CorpusHit, SourceAdapter, SourceStatus
from services.corpus.chunk_store import CorpusChunkStore


@dataclass(frozen=True)
class DocIndexJob:
    """A queued (re)index of one document, drained off the request path.

    ``body`` is the current text to index, or ``None`` for a removal (archive/delete):
    either way the worker first clears the document's existing chunks, then — when a
    body is present — chunks, seals, and embeds it. Carrying the plaintext body avoids
    handing the corpus layer the vault; it lives only in memory on the unlocked side."""

    owner_id: str
    document_id: str
    body: str | None


class DocumentsAdapter(SourceAdapter):
    source_kind = "documents"
    SOURCE_ID = "surf-documents"

    def __init__(self, engine: Engine, chunk_store: CorpusChunkStore, unlocked) -> None:
        self._engine = engine
        self._chunks = chunk_store
        self._worker: WriteBehindWorker[DocIndexJob] = WriteBehindWorker(
            self._index, name="corpus-documents", unlocked=unlocked
        )

    async def start(self) -> None:
        await self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()

    # --- document lifecycle (called by the DocumentStore after each write) ----

    def index_document(self, owner_id: str, document_id: str, body: str) -> None:
        """Queue a (re)index of one document's body. Idempotent: the job clears the
        document's prior chunks before inserting the current ones, so create and edit
        share one path (a create has nothing to clear)."""
        self._worker.submit(DocIndexJob(owner_id, document_id, body))

    def remove_document(self, owner_id: str, document_id: str) -> None:
        """Queue removal of a document's chunks (archive or delete). Routed through the
        worker so it can't race a still-queued index of the same document."""
        self._worker.submit(DocIndexJob(owner_id, document_id, None))

    # --- adapter contract -------------------------------------------------

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
        # Chunks are scored from the pre-computed dense/sparse forms; the raw query
        # string isn't needed here. All documents share one source_kind.
        return await self._chunks.retrieve(
            owner_id, self.source_kind, query_vec, query_model, query_tokens, limit=limit
        )

    async def status(self, owner_id: str) -> SourceStatus:
        return SourceStatus(
            source_id=self.SOURCE_ID,
            kind="surface",
            label="Documents",
            doc_count=await self._chunks.count_items(owner_id, self.source_kind),
            status="indexed",
            last_indexed_at=None,
            href="/documents",
        )

    async def reindex(self, owner_id: str, *, current_model: str | None = None) -> int:
        # Scoped to this surface's own chunks — re-embedding the whole store here would
        # redo every other source's work each time a single surface is reindexed.
        return await self._chunks.reembed(
            owner_id, source_kind=self.source_kind, current_model=current_model
        )

    # --- indexing ---------------------------------------------------------

    async def _index(self, job: DocIndexJob) -> None:
        """Clear the document's existing chunks, then (when a body is present) chunk,
        seal, and embed the current body. The worker handler — runs only while the vault
        is unlocked, since it seals text + vectors."""
        await self._chunks.delete_source(job.owner_id, job.document_id)
        if job.body is None:
            return  # removal — nothing to re-insert
        chunks = chunk_text(job.body)
        if not chunks:
            return
        await self._chunks.upsert(
            job.owner_id, self.source_kind, job.document_id, job.document_id, chunks
        )
        # Best-effort embed of the freshly inserted (null-vector) chunks.
        await self._chunks.reembed(job.owner_id, job.document_id)
