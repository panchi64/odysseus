"""The generic chunk store — CRUD + hybrid rank over ``corpus_chunk``.

The shared backend for every *chunked* source (folders and uploads now; research
later). It is the corpus counterpart of ``MemoryStore`` /
``ConversationSearch``: rows are encrypted at rest (text + vector), so recall is the
same **hybrid, brute-force** pass — decrypt the owner's chunks for a source, score
each dense (cosine over the per-chunk vector) and sparse (token overlap), and return
the per-chunk scores *unfused* (``CorpusIndex`` fuses across sources). The scoring
primitives are the shared ones in :mod:`services.ranking`.

Inserts are **idempotent per item**: a re-crawl of an unchanged item hashes to the same
values and is skipped, so reindex never dupes. The dedup key is ``(item, content)``, not
content alone — two byte-identical files under one source (a repeated LICENSE, two empty
``__init__.py``) are two items and must both be indexed, or one of them is invisible to
search and every hit on the shared text is cited to the other's path.

``upsert`` only ever *inserts*, so a source whose origin can lose or change items needs
``prune_stale`` to reconcile the other direction. Embedding reuses the one shared loop,
``embed_and_seal_rows(model_cls=CorpusChunk)``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping

import numpy as np
from sqlalchemy import Engine, func, or_
from sqlmodel import Session, delete, select, update

from core.db import in_session
from core.vault import Vault
from models.corpus import CorpusChunk
from services import ranking
from services.chunking import Chunk
from services.corpus.adapter import CorpusHit
from services.embeddings import Embedder, decode_vector, embed_and_seal_rows


def content_hash(text: str) -> str:
    """The dedup/idempotency key for a chunk — sha256 of its text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item_of(external_ref: str) -> str:
    """The origin item an ``external_ref`` points into — its ``"<item>#<offset>"`` head.

    The offset moves whenever an edit shifts the text, so the *item* is the stable half
    and the only thing two crawls can compare. Split on the **last** ``#`` so a path that
    itself contains one stays intact."""
    return external_ref.rsplit("#", 1)[0]


# How many ids one delete statement binds. A wide re-crawl (a whole subtree removed) can
# doom more rows than SQLite will accept parameters for in a single statement, so the
# prune goes out in batches rather than betting on the driver's limit.
_DELETE_BATCH = 500


class CorpusChunkStore:
    def __init__(self, engine: Engine, vault: Vault, embedder: Embedder) -> None:
        self._engine = engine
        self._vault = vault
        self._embedder = embedder

    @property
    def vault(self) -> Vault:
        """The corpus's at-rest key. Exposed so an adapter that seals a column on its own
        registry table (``FolderAdapter``'s host path) uses the same vault the chunks it
        produces are sealed with, rather than being handed a second one at construction."""
        return self._vault

    # --- write path -------------------------------------------------------

    async def upsert(
        self,
        owner_id: str,
        source_kind: str,
        source_id: str,
        base_ref: str,
        chunks: list[Chunk],
        *,
        kb_excluded: bool = False,
    ) -> int:
        """Insert each chunk's sealed text with a null vector, skipping any whose content
        hash this source already holds **for this same item** (idempotent reindex).
        Returns how many new chunks were inserted. ``kb_excluded`` is stamped on every new
        chunk so a source that's currently scoped out of the knowledge base stays out
        across a reindex (the source row is authoritative; the caller passes its state).

        Insert-only: a caller whose origin can drop or edit items pairs this with
        :meth:`prune_stale`."""
        prepared = [
            (
                content_hash(chunk.text),
                f"{base_ref}#{chunk.offset}",
                chunk.ordinal,
                self._vault.encrypt_str(chunk.text),
            )
            for chunk in chunks
            if chunk.text.strip()
        ]

        def work(session: Session) -> int:
            # Scoped to *this item*, not the whole source. The hash set exists to stop a
            # re-crawl re-inserting a chunk it already holds for the same file; widened to
            # the source it also swallows a different file that happens to be byte-identical
            # — the second file is then never indexed at all, and every retrieval hit on the
            # shared text is cited against the first path that claimed it. `autoescape`
            # matters: a prefix goes into a LIKE, and paths are full of `_` (`__init__.py`
            # is the collision case), which would otherwise match any character.
            existing = set(
                session.exec(
                    select(CorpusChunk.content_hash).where(
                        CorpusChunk.owner_id == owner_id,
                        CorpusChunk.source_id == source_id,
                        CorpusChunk.external_ref.startswith(  # type: ignore[attr-defined]
                            f"{base_ref}#", autoescape=True
                        ),
                    )
                ).all()
            )
            inserted = 0
            for chash, ref, ordinal, text_enc in prepared:
                if chash in existing:
                    continue
                existing.add(chash)  # dedup within this batch too
                session.add(
                    CorpusChunk(
                        owner_id=owner_id,
                        source_kind=source_kind,
                        source_id=source_id,
                        external_ref=ref,
                        content_hash=chash,
                        ordinal=ordinal,
                        text_enc=text_enc,
                        kb_excluded=kb_excluded,
                    )
                )
                inserted += 1
            return inserted

        return await in_session(self._engine, work)

    async def prune_stale(
        self,
        owner_id: str,
        source_id: str,
        *,
        live_refs: Collection[str],
        live_hashes: Mapping[str, set[str]],
    ) -> int:
        """Reconcile a source down to what its origin still holds — the *delete* half of a
        re-index, which the insert-only :meth:`upsert` cannot do on its own.

        Two kinds of row go. One whose item is absent from ``live_refs``: the file was
        deleted, renamed, grew past the crawler's size cap, or stopped being text-like, so
        nothing behind it exists any more and leaving it in means recall keeps quoting
        content the operator removed. And one whose item *is* live but whose content hash
        is absent from ``live_hashes`` for it: the file was edited, so that slice is
        superseded and would otherwise sit alongside the new text as a second, stale
        version of the same passage.

        An item in ``live_refs`` with **no** ``live_hashes`` entry is left entirely alone.
        That is the "seen but unreadable" case — the crawler knows the file is there but
        couldn't open it — and a transient permission error must never erase a file's
        index. Callers pass hashes only for items they actually read.

        Returns how many chunks were removed."""
        live = set(live_refs)

        def work(session: Session) -> int:
            # Only the three structural columns — the sealed text and vector are never
            # needed to decide this, and they are by far the widest columns in the row.
            rows = session.exec(
                select(
                    CorpusChunk.id, CorpusChunk.external_ref, CorpusChunk.content_hash
                ).where(
                    CorpusChunk.owner_id == owner_id,
                    CorpusChunk.source_id == source_id,
                )
            ).all()
            doomed: list[str] = []
            for row_id, ref, chash in rows:
                item = item_of(ref)
                keep = live_hashes.get(item)
                if item not in live or (keep is not None and chash not in keep):
                    doomed.append(row_id)
            for start in range(0, len(doomed), _DELETE_BATCH):
                session.exec(
                    delete(CorpusChunk).where(
                        CorpusChunk.id.in_(doomed[start : start + _DELETE_BATCH])  # type: ignore[attr-defined]
                    )
                )
            return len(doomed)

        return await in_session(self._engine, work)

    async def delete_source(self, owner_id: str, source_id: str) -> None:
        """Drop every chunk a source contributed (folder removal)."""

        def work(session: Session) -> None:
            session.exec(
                delete(CorpusChunk).where(
                    CorpusChunk.owner_id == owner_id,
                    CorpusChunk.source_id == source_id,
                )
            )

        await in_session(self._engine, work)

    async def set_excluded(self, owner_id: str, source_id: str, value: bool) -> None:
        """Flip ``kb_excluded`` on every chunk a source contributed — the retroactive
        knowledge-base toggle. The write itself needs no vault key (a clear column), but
        callers serialize it against (re)index jobs via their lock-aware worker (the
        uploads adapter does), so in practice it parks while the vault is locked. The
        denormalized flag is what ambient ``retrieve`` filters on, so this is what makes
        an already-indexed file vanish from (or return to) general recall. Idempotent."""

        def work(session: Session) -> None:
            session.exec(
                update(CorpusChunk)
                .where(
                    CorpusChunk.owner_id == owner_id,
                    CorpusChunk.source_id == source_id,
                )
                .values(kb_excluded=value)
            )

        await in_session(self._engine, work)

    async def reembed(
        self,
        owner_id: str,
        source_id: str | None = None,
        *,
        source_kind: str | None = None,
        current_model: str | None = None,
        batch_size: int = 64,
    ) -> int:
        """Embed chunks whose vector is missing, or was produced by a model other than
        ``current_model`` (the EMB-2 heal path after an embedding-model change). Scoped
        to one ``source_id`` or one ``source_kind`` when given, else the owner's whole
        chunk store (the global heal). A per-surface heal passes its ``source_kind`` so
        it touches only its own chunks, not every other surface's. Reuses the one shared
        embed→seal loop. Returns how many chunks were embedded."""

        def pending(session: Session) -> list[tuple[str, str]]:
            query = select(CorpusChunk).where(CorpusChunk.owner_id == owner_id)
            if source_id is not None:
                query = query.where(CorpusChunk.source_id == source_id)
            if source_kind is not None:
                query = query.where(CorpusChunk.source_kind == source_kind)
            if current_model is None:
                query = query.where(CorpusChunk.embedding_enc.is_(None))  # type: ignore[union-attr]
            else:
                query = query.where(
                    or_(
                        CorpusChunk.embedding_enc.is_(None),  # type: ignore[union-attr]
                        CorpusChunk.embedding_model != current_model,
                    )
                )
            rows = session.exec(query).all()
            return [(row.id, self._vault.decrypt_str(row.text_enc)) for row in rows]

        rows = await in_session(self._engine, pending)
        items = [(rid, text) for rid, text in rows if text.strip()]
        return await embed_and_seal_rows(
            engine=self._engine,
            vault=self._vault,
            embedder=self._embedder,
            owner_id=owner_id,
            model_cls=CorpusChunk,
            pending=items,
            batch_size=batch_size,
        )

    # --- read path --------------------------------------------------------

    async def count(self, owner_id: str, source_id: str) -> int:
        """How many chunks a source has indexed (never decrypts)."""

        def work(session: Session) -> int:
            return session.exec(
                select(func.count())
                .select_from(CorpusChunk)
                .where(CorpusChunk.owner_id == owner_id, CorpusChunk.source_id == source_id)
            ).one()

        return await in_session(self._engine, work)

    async def count_items(
        self, owner_id: str, source_kind: str, source_id: str | None = None
    ) -> int:
        """How many distinct source *items* a kind has indexed (never decrypts).

        An item is one origin document/file, regardless of how many chunks it split
        into — the count the ``/rag`` row labels "DOCS". An item is identified the same
        way :meth:`prune_stale` identifies one, via :func:`item_of`. Scoped to one
        ``source_id`` when given (a single folder's file count), else the whole kind
        (e.g. every document). ``external_ref`` is structural/unencrypted, so this only
        loads short ref strings."""

        def work(session: Session) -> int:
            # Counts indexed items regardless of kb_excluded — the /rag DOCS readout
            # reflects what's been indexed/managed, not what ambient recall returns; an
            # excluded file is still indexed and reachable from the uploads page.
            query = select(CorpusChunk.external_ref).where(
                CorpusChunk.owner_id == owner_id,
                CorpusChunk.source_kind == source_kind,
            )
            if source_id is not None:
                query = query.where(CorpusChunk.source_id == source_id)
            refs = session.exec(query).all()
            return len({item_of(ref) for ref in refs})

        return await in_session(self._engine, work)

    async def count_all(self, owner_id: str) -> int:
        """Total chunks across every chunked source (the corpus-stats readout)."""

        def work(session: Session) -> int:
            return session.exec(
                select(func.count())
                .select_from(CorpusChunk)
                .where(CorpusChunk.owner_id == owner_id)
            ).one()

        return await in_session(self._engine, work)

    async def retrieve(
        self,
        owner_id: str,
        source_kind: str | None,
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        *,
        limit: int,
        source_id: str | None = None,
        source_ids: list[str] | None = None,
    ) -> list[CorpusHit]:
        """Hybrid recall over a source's chunks, scored but **unfused** (the index
        fuses across sources). Filtered to ``source_kind`` (pass ``None`` to span every
        kind — a targeted read by id), to one ``source_id``, or to a set of
        ``source_ids`` (e.g. a chat's own attached files). ``kb_excluded`` governs
        **ambient recall only**: a kind-scoped/fan-out read hides excluded chunks, but an
        explicit ``source_ids`` fetch overrides exclusion — a caller that names a file
        (the chat reading its own attachment from the marker) still gets it, while it
        stays out of every other chat's general recall. A degraded query vector collapses
        to sparse-only."""

        def work(session: Session) -> list[CorpusHit]:
            query = select(CorpusChunk).where(CorpusChunk.owner_id == owner_id)
            if source_kind is not None:
                query = query.where(CorpusChunk.source_kind == source_kind)
            if source_id is not None:
                query = query.where(CorpusChunk.source_id == source_id)
            if source_ids is not None:
                # Explicit by-id fetch — overrides exclusion (see docstring).
                query = query.where(CorpusChunk.source_id.in_(source_ids))  # type: ignore[attr-defined]
            else:
                # Ambient recall: a file scoped out of the knowledge base is hidden.
                query = query.where(CorpusChunk.kb_excluded == False)  # noqa: E712 — SQL boolean
            rows = session.exec(query).all()
            return self._rank(rows, query_vec, query_model, query_tokens, limit)

        return await in_session(self._engine, work)

    def _rank(
        self,
        rows: list[CorpusChunk],
        query_vec: np.ndarray | None,
        query_model: str | None,
        query_tokens: set[str],
        limit: int,
    ) -> list[CorpusHit]:
        dense: dict[str, float] = {}
        sparse: dict[str, float] = {}
        by_id: dict[str, CorpusChunk] = {}
        text_by_id: dict[str, str] = {}
        for row in rows:
            text = self._vault.decrypt_str(row.text_enc)
            if not text.strip():
                continue
            by_id[row.id] = row
            text_by_id[row.id] = text
            overlap = len(query_tokens & ranking.tokens(text))
            if overlap:
                sparse[row.id] = float(overlap)
            # Dense only within the same embedding space (EMB-2), and only when there
            # is actual similarity — a zero/orthogonal vector carries no signal.
            if (
                query_vec is not None
                and row.embedding_enc is not None
                and row.embedding_model == query_model
            ):
                vector = np.asarray(decode_vector(self._vault, row.embedding_enc))
                score = ranking.cosine(query_vec, vector)
                if score > 0:
                    dense[row.id] = score

        # Fuse this source's own dense + sparse signals with RRF (same hybrid memory
        # and conversation recall use), so cosine and keyword overlap combine by rank
        # rather than letting the larger raw number win. The index then fuses the
        # already-ranked sources together.
        fused = ranking.rrf(dense, sparse)
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        hits: list[CorpusHit] = []
        for cid, _score in ordered:
            row = by_id[cid]
            hits.append(
                CorpusHit(
                    gid=f"{row.source_id}:{row.external_ref}",
                    source_id=row.source_id,
                    ref=row.external_ref,
                    text=text_by_id[cid],
                    dense_score=dense.get(cid),
                    sparse_score=sparse.get(cid),
                    matched_by=ranking.matched_by(cid, dense, sparse),
                )
            )
        return hits
