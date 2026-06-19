"""The uploads source — index extracted upload text into the corpus.

The in-app counterpart to :class:`~services.corpus.documents.DocumentsAdapter`: where
that indexes document bodies, this indexes the **text extracted from uploaded files**
(the `UP-2` output) so the agent retrieves an upload's contents through the one
``corpus.retrieve`` tool. Only the extracted text is indexed — never the raw bytes —
and it's chunked and sealed into the shared ``corpus_chunk`` store exactly as documents
and folders are.

Each upload is its own ``source_id`` (the upload id) under the shared
``source_kind="uploads"``, so re-indexing a single upload (after the operator corrects
its extracted text) touches only that upload's chunks. Indexing runs on the same
lock-aware :class:`~core.worker.WriteBehindWorker` the documents source uses, and like
that source an index job **clears the upload's existing chunks before inserting** — a
correction that shortens the text must not strand orphan chunks.
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
class UploadIndexJob:
    """A queued (re)index of one upload's extracted text, drained off the request path.

    ``text`` is the current extracted text to index, or ``None`` for a removal
    (delete): either way the worker first clears the upload's existing chunks, then —
    when text is present — chunks, seals, and embeds it."""

    owner_id: str
    upload_id: str
    text: str | None


class UploadsAdapter(SourceAdapter):
    source_kind = "uploads"
    SOURCE_ID = "surf-uploads"

    def __init__(self, engine: Engine, chunk_store: CorpusChunkStore, unlocked) -> None:
        self._engine = engine
        self._chunks = chunk_store
        self._worker: WriteBehindWorker[UploadIndexJob] = WriteBehindWorker(
            self._index, name="corpus-uploads", unlocked=unlocked
        )

    async def start(self) -> None:
        await self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()

    # --- upload lifecycle (called by the UploadStore after extraction) --------

    def index_upload(self, owner_id: str, upload_id: str, text: str) -> None:
        """Queue a (re)index of one upload's extracted text. Idempotent: the job clears
        the upload's prior chunks before inserting the current ones, so first-extraction
        and a later correction share one path."""
        self._worker.submit(UploadIndexJob(owner_id, upload_id, text))

    def remove_upload(self, owner_id: str, upload_id: str) -> None:
        """Queue removal of an upload's chunks (delete). Routed through the worker so it
        can't race a still-queued index of the same upload."""
        self._worker.submit(UploadIndexJob(owner_id, upload_id, None))

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
        return await self._chunks.retrieve(
            owner_id, self.source_kind, query_vec, query_model, query_tokens, limit=limit
        )

    async def status(self, owner_id: str) -> SourceStatus:
        return SourceStatus(
            source_id=self.SOURCE_ID,
            kind="surface",
            label="Uploads",
            doc_count=await self._chunks.count_items(owner_id, self.source_kind),
            status="indexed",
            last_indexed_at=None,
            href="/uploads",
        )

    async def reindex(self, owner_id: str, *, current_model: str | None = None) -> int:
        return await self._chunks.reembed(
            owner_id, source_kind=self.source_kind, current_model=current_model
        )

    # --- indexing ---------------------------------------------------------

    async def _index(self, job: UploadIndexJob) -> None:
        """Clear the upload's existing chunks, then (when text is present) chunk, seal,
        and embed it. The worker handler — runs only while the vault is unlocked, since
        it seals text + vectors."""
        await self._chunks.delete_source(job.owner_id, job.upload_id)
        if job.text is None:
            return  # removal — nothing to re-insert
        chunks = chunk_text(job.text)
        if not chunks:
            return
        await self._chunks.upsert(
            job.owner_id, self.source_kind, job.upload_id, job.upload_id, chunks
        )
        await self._chunks.reembed(job.owner_id, job.upload_id)
