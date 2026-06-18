"""The folder source — crawl a host path, chunk it, embed it into the corpus.

The one concrete *content* source today: an operator-added host directory the
backend walks for text-like files, chunks (token-window + overlap), and seals into
the generic ``corpus_chunk`` store. Indexing runs on a lock-aware
:class:`~core.worker.WriteBehindWorker`: ``add_folder``/``rebuild`` submit a job, the
worker drains it off the request path and **parks while the vault is locked** (it must
seal text + vectors, so it can't run without the key), resuming on unlock.

Crawl is conservative: only text-like extensions, skipping binaries and oversized
files, so a stray archive never poisons the index. A missing path is recorded as an
``error`` source with a terse hint ("PATH NOT FOUND") rather than failing the request.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.worker import WriteBehindWorker
from models.corpus import CorpusSource
from services.chunking import chunk_text
from services.corpus.adapter import CorpusHit, SourceAdapter, SourceStatus
from services.corpus.chunk_store import CorpusChunkStore

logger = logging.getLogger(__name__)

# Text-like extensions the crawler reads; everything else is skipped as a binary.
_TEXT_EXTENSIONS = frozenset(
    {
        ".txt", ".md", ".markdown", ".rst", ".text", ".log", ".csv", ".tsv",
        ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".scss",
        ".sh", ".bash", ".zsh", ".sql", ".xml", ".go", ".rs", ".java", ".c",
        ".h", ".cpp", ".hpp", ".rb", ".php", ".swift", ".kt",
    }
)
_MAX_FILE_BYTES = 2_000_000  # skip anything larger than ~2 MB (likely not a document)


@dataclass(frozen=True)
class IndexJob:
    """A queued crawl-and-index of one folder, drained off the request path."""

    owner_id: str
    source_id: str


class FolderAdapter(SourceAdapter):
    source_kind = "folder"

    def __init__(self, engine: Engine, chunk_store: CorpusChunkStore, unlocked) -> None:
        self._engine = engine
        self._chunks = chunk_store
        self._worker: WriteBehindWorker[IndexJob] = WriteBehindWorker(
            self._index, name="corpus-folder", unlocked=unlocked
        )

    async def start(self) -> None:
        await self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()

    # --- registry ---------------------------------------------------------

    async def add_folder(self, owner_id: str, path: str) -> CorpusSource:
        """Register a folder and queue its first crawl (drained while unlocked)."""
        source = CorpusSource(owner_id=owner_id, path=path, status="indexing")

        def work(session: Session) -> CorpusSource:
            session.add(source)
            session.flush()
            session.refresh(source)
            return source

        created = await in_session(self._engine, work)
        self._worker.submit(IndexJob(owner_id, created.id))
        return created

    async def remove_folder(self, owner_id: str, source_id: str) -> bool:
        """Drop a folder and every chunk it contributed. False if not the owner's."""

        def work(session: Session) -> bool:
            source = session.get(CorpusSource, source_id)
            if source is None or source.owner_id != owner_id:
                return False
            session.delete(source)
            return True

        removed = await in_session(self._engine, work)
        if removed:
            await self._chunks.delete_source(owner_id, source_id)
        return removed

    async def rebuild(self, owner_id: str, source_id: str) -> bool:
        """Re-queue a folder's crawl (status → indexing). False if not the owner's."""

        def work(session: Session) -> bool:
            source = session.get(CorpusSource, source_id)
            if source is None or source.owner_id != owner_id:
                return False
            source.status = "indexing"
            source.error_hint = None
            session.add(source)
            return True

        ok = await in_session(self._engine, work)
        if ok:
            self._worker.submit(IndexJob(owner_id, source_id))
        return ok

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
        # Chunks are scored directly from the pre-computed dense/sparse forms; the raw
        # query string isn't needed here.
        return await self._chunks.retrieve(
            owner_id, self.source_kind, query_vec, query_model, query_tokens, limit=limit
        )

    async def status(self, owner_id: str) -> list[SourceStatus]:
        def work(session: Session) -> list[CorpusSource]:
            return list(
                session.exec(select(CorpusSource).where(CorpusSource.owner_id == owner_id)).all()
            )

        sources = await in_session(self._engine, work)
        statuses: list[SourceStatus] = []
        for source in sources:
            statuses.append(
                SourceStatus(
                    source_id=source.id,
                    kind="folder",
                    label=source.path,
                    doc_count=await self._chunks.count(owner_id, source.id),
                    status=source.status,
                    last_indexed_at=source.last_indexed_at,
                    error_hint=source.error_hint,
                )
            )
        return statuses

    async def reindex(self, owner_id: str, *, current_model: str | None = None) -> int:
        return await self._chunks.reembed(owner_id, current_model=current_model)

    # --- indexing ---------------------------------------------------------

    async def _index(self, job: IndexJob) -> None:
        """Crawl one folder, chunk every text-like file, seal new chunks, embed them.

        The worker handler — runs only while the vault is unlocked. A missing path
        records an error status; a present one crawls, dedups by content hash, and
        backfills vectors for the freshly inserted chunks."""

        def load(session: Session) -> CorpusSource | None:
            source = session.get(CorpusSource, job.source_id)
            return source if source is not None and source.owner_id == job.owner_id else None

        source = await in_session(self._engine, load)
        if source is None:
            return  # removed before the job ran

        path = source.path
        if not os.path.isdir(path):
            await self._mark(job.source_id, status="error", error_hint="PATH NOT FOUND")
            return
        root = os.path.realpath(path)

        for file_path in self._walk(root):
            try:
                text = self._read(file_path)
            except OSError:
                logger.warning("corpus folder: could not read %s", file_path, exc_info=True)
                continue
            chunks = chunk_text(text)
            if chunks:
                await self._chunks.upsert(
                    job.owner_id, self.source_kind, job.source_id, file_path, chunks
                )
        # Best-effort embed of the freshly inserted (null-vector) chunks.
        await self._chunks.reembed(job.owner_id, job.source_id)
        await self._mark(job.source_id, status="indexed", last_indexed_at=datetime.now(UTC))

    def _walk(self, root: str) -> list[str]:
        """Text-like files under ``root`` (a realpath), contained to that tree.

        ``followlinks=False`` keeps the walk from recursing through symlinked
        directories; the per-file realpath check additionally drops a symlinked *file*
        that points outside ``root`` (e.g. a ``link.txt`` → ``/etc/passwd``), so a stray
        symlink can never pull external content into the index."""
        found: list[str] = []
        prefix = root + os.sep
        for dirpath, _dirs, files in os.walk(root, followlinks=False):
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in _TEXT_EXTENSIONS:
                    continue
                full = os.path.join(dirpath, name)
                real = os.path.realpath(full)
                if real != root and not real.startswith(prefix):
                    continue  # symlink escaping the indexed tree
                try:
                    if os.path.getsize(full) > _MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                found.append(full)
        return found

    @staticmethod
    def _read(path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()

    async def _mark(
        self,
        source_id: str,
        *,
        status: str,
        error_hint: str | None = None,
        last_indexed_at: datetime | None = None,
    ) -> None:
        def work(session: Session) -> None:
            source = session.get(CorpusSource, source_id)
            if source is None:
                return
            source.status = status
            source.error_hint = error_hint
            if last_indexed_at is not None:
                source.last_indexed_at = last_indexed_at
            session.add(source)

        await in_session(self._engine, work)
