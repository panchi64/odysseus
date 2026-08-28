"""Documents — create, edit, version, archive, and restore the operator's library.

The capability behind `DOC-1`/`DOC-2`. A document is encrypted at rest (title + body);
the operator owns it, so reads come back decrypted. Two invariants the store keeps:

- **Every change is a version** (`DOC-2`). Create, edit, and a version-restore each
  append a full sealed snapshot stamped with its origin (user | ai | extraction). The
  history is append-only and any version is restorable — restoring copies a snapshot
  back onto the live row *and* records that as a fresh version, so the timeline never
  rewrites itself.
- **The body is corpus content.** After every write the store tells the
  :class:`~services.corpus.documents.DocumentsAdapter` to (re)index the body, so the
  agent retrieves the current text through ``corpus.retrieve``. Archiving or deleting a
  document drops its chunks (an archived document shouldn't surface in retrieval).

Search is deliberately *not* a method here: document search — for the operator and the
agent alike — flows through the corpus's hybrid recall (the adapter above), not a
second hand-rolled scan over decrypted bodies. The store only browses (`list_documents`).

The detected ``doc_type``/``language`` are display hints, not content, so they stay in
the clear. Detection is best-effort and off the DB hot path: a coarse type heuristic
plus a pure-Python language guess that degrades to ``None`` rather than failing a write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from core.db import get_owned, in_session
from core.exceptions import DocumentSpanError, NotFoundError
from core.text import replace_unique
from core.vault import Vault
from models.document import Document, DocumentVersion, DocumentVersionOrigin
from services.corpus.documents import DocumentsAdapter
from services.projects import project_clause


@dataclass(frozen=True)
class DocumentView:
    """A decrypted document for listing/editing (content in the clear to the owner)."""

    id: str
    title: str
    body: str
    doc_type: str
    language: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime
    # The conversation that created this document (null for a library-born doc). Clear
    # provenance the chat layer reads to gate edits and seed the View.
    conversation_id: str | None = None


@dataclass(frozen=True)
class DocumentSummaryView:
    """A library-list row: enough to render without shipping the full body. The snippet
    and word count are derived from the (decrypted) body here so the list response stays
    small even when documents are large."""

    id: str
    title: str
    snippet: str
    word_count: int
    archived: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentVersionView:
    """A decrypted snapshot from a document's history (`DOC-2`)."""

    id: str
    version: int
    origin: str
    title: str
    body: str
    created_at: datetime
    # The operator's durable bookmark on this version.
    keeper: bool = False


class DocumentStore:
    def __init__(self, engine: Engine, vault: Vault, adapter: DocumentsAdapter) -> None:
        self._engine = engine
        self._vault = vault
        self._adapter = adapter
        # The suggestion lifecycle (`DOC-3`) hangs off the same store so every caller that
        # already resolves `documents` reaches it without new wiring. Imported here rather
        # than at module scope because that module reads this one's write helpers — a
        # deliberate one-way dependency broken at the single point where it would loop.
        from .document_suggestions import DocumentSuggestionStore

        self.suggestions = DocumentSuggestionStore(engine, vault, adapter)

    # --- write path -------------------------------------------------------

    async def create(
        self,
        owner_id: str,
        title: str,
        body: str,
        *,
        conversation_id: str | None = None,
        project_id: str | None = None,
        origin: str = DocumentVersionOrigin.USER,
    ) -> DocumentView:
        """Create a document and record its first version. ``origin`` stamps that version's
        author (`DOC-2`): the library UI creates USER-authored documents (the default), while
        the agent's ``document_create`` passes ``ai`` so the first version reads as the agent's
        work — which is what lets the chat layer tell a later operator edit apart from it.

        ``project_id`` files it. Null is *unfiled*, which is visible under every scope, so
        omitting it is safe — but a document written inside a project conversation that
        came back unfiled would be the one the operator later can't find beside the work it
        belongs to, which is why the callers resolve it."""
        doc_type, language = detect_type_language(body)
        document = Document(
            owner_id=owner_id,
            conversation_id=conversation_id,
            project_id=project_id,
            title_enc=self._vault.encrypt_str(title),
            body_enc=self._vault.encrypt_str(body),
            doc_type=doc_type,
            language=language,
        )

        def work(session: Session) -> DocumentView:
            session.add(document)
            session.flush()
            snapshot_version(session, document, origin)
            return self._to_view(document, title, body)

        view = await in_session(self._engine, work)
        self._adapter.index_document(owner_id, view.id, body)
        return view

    async def edit(
        self,
        owner_id: str,
        document_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        origin: str = DocumentVersionOrigin.USER,
    ) -> tuple[DocumentView, int]:
        """Apply a partial edit, snapshot the result as a new version, and re-index when
        the body changed. Every call records a version (`DOC-2`) — even a title-only
        change, since the history tracks the whole document, not just its text — but a
        title-only edit skips re-indexing: the corpus only holds the body, so re-chunking
        and re-embedding it would be wasted work. Returns the updated view **and the new
        version number** (mirroring ``replace_span``), so a caller need not re-query the
        history to report it."""
        await self._require(owner_id, document_id)

        def work(session: Session) -> tuple[DocumentView, int]:
            document = session.get(Document, document_id)
            assert document is not None
            if title is not None:
                document.title_enc = self._vault.encrypt_str(title)
            if body is not None:
                write_body(self._vault, document, body)
            document.updated_at = datetime.now(UTC)
            session.add(document)
            session.flush()
            version = snapshot_version(session, document, origin).version
            new_title = title if title is not None else self._vault.decrypt_str(document.title_enc)
            new_body = body if body is not None else self._vault.decrypt_str(document.body_enc)
            return self._to_view(document, new_title, new_body), version

        view, version = await in_session(self._engine, work)
        if body is not None:
            self._adapter.index_document(owner_id, document_id, body)
        return view, version

    async def replace_span(
        self,
        owner_id: str,
        document_id: str,
        old_text: str,
        new_text: str,
        *,
        origin: str = DocumentVersionOrigin.AI,
    ) -> tuple[DocumentView, int, datetime]:
        """Apply a targeted edit — replace the single occurrence of ``old_text`` with
        ``new_text`` — and snapshot the result as a new version. Raises
        :class:`DocumentSpanError` (carrying the count) when ``old_text`` doesn't match
        exactly one span, so the caller can ask for a more precise span. Returns the updated
        view, **the new version number, and that version's ``created_at``** — the authoritative
        ordering key the ``document.committed`` event carries so a live-minted version sorts
        the same as one read back on refresh — so a caller (the document tool) need not
        re-query the history. The uniqueness check runs against the decrypted body inside the
        write transaction — the whole check-and-replace is atomic."""
        await self._require(owner_id, document_id)

        def work(session: Session) -> tuple[DocumentView, str, int, datetime]:
            document = session.get(Document, document_id)
            assert document is not None
            body = self._vault.decrypt_str(document.body_enc)
            new_body = replace_unique(body, old_text, new_text, error=DocumentSpanError)
            write_body(self._vault, document, new_body)
            document.updated_at = datetime.now(UTC)
            session.add(document)
            session.flush()
            snapshot = snapshot_version(session, document, origin)
            title = self._vault.decrypt_str(document.title_enc)
            view = self._to_view(document, title, new_body)
            return view, new_body, snapshot.version, snapshot.created_at

        view, new_body, version, created_at = await in_session(self._engine, work)
        self._adapter.index_document(owner_id, document_id, new_body)
        return view, version, created_at

    async def archive(self, owner_id: str, document_id: str) -> DocumentView:
        """Soft-archive (restorable). Drops the document's corpus chunks so an archived
        document stops surfacing in retrieval."""
        view = await self._set_archived(owner_id, document_id, True)
        self._adapter.remove_document(owner_id, document_id)
        return view

    async def restore(self, owner_id: str, document_id: str) -> DocumentView:
        """Bring an archived document back and re-index its body."""
        view = await self._set_archived(owner_id, document_id, False)
        self._adapter.index_document(owner_id, document_id, view.body)
        return view

    async def restore_version(
        self, owner_id: str, document_id: str, version: int
    ) -> DocumentView:
        """Copy an earlier snapshot back onto the live document and record that as a new
        (user-origin) version — history stays append-only — then re-index."""
        await self._require(owner_id, document_id)

        def work(session: Session) -> tuple[DocumentView, str]:
            snapshot = session.exec(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version == version,
                )
            ).first()
            if snapshot is None:
                raise NotFoundError(f"document {document_id!r} has no version {version}")
            document = session.get(Document, document_id)
            assert document is not None
            document.title_enc = snapshot.title_enc
            document.body_enc = snapshot.body_enc
            document.doc_type = snapshot.doc_type
            document.language = snapshot.language
            document.updated_at = datetime.now(UTC)
            session.add(document)
            session.flush()
            snapshot_version(session, document, DocumentVersionOrigin.USER)
            title = self._vault.decrypt_str(document.title_enc)
            body = self._vault.decrypt_str(document.body_enc)
            return self._to_view(document, title, body), body

        view, body = await in_session(self._engine, work)
        self._adapter.index_document(owner_id, document_id, body)
        return view

    async def set_keeper(
        self, owner_id: str, document_id: str, version: int, keeper: bool
    ) -> bool:
        """Bookmark or unbookmark a version. Returns False if unknown/not owned."""

        def work(session: Session) -> bool:
            row = session.exec(
                select(DocumentVersion).where(
                    DocumentVersion.owner_id == owner_id,
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version == version,
                )
            ).first()
            if row is None:
                return False
            row.keeper = keeper
            session.add(row)
            session.flush()
            return True

        return await in_session(self._engine, work)

    async def delete(self, owner_id: str, document_id: str) -> None:
        """Hard-delete a document, its version history, its open suggestions, and its
        corpus chunks — nothing about it outlives it."""
        await self._require(owner_id, document_id)

        def work(session: Session) -> None:
            for snapshot in session.exec(
                select(DocumentVersion).where(DocumentVersion.document_id == document_id)
            ).all():
                session.delete(snapshot)
            self.suggestions.purge_document(session, document_id)
            document = session.get(Document, document_id)
            if document is not None:
                session.delete(document)

        await in_session(self._engine, work)
        self._adapter.remove_document(owner_id, document_id)

    # --- read path --------------------------------------------------------

    async def list_documents(
        self,
        owner_id: str,
        *,
        include_archived: bool = False,
        visible_projects: tuple[str | None, ...] | None = None,
    ) -> list[DocumentSummaryView]:
        """The library, newest first — summaries only (no full body). Active unless
        ``include_archived``.

        ``visible_projects`` is the project scope (``services.projects``); ``None`` —
        the default — means no filtering, which is what every non-route caller wants."""

        def work(session: Session) -> list[DocumentSummaryView]:
            query = select(Document).where(Document.owner_id == owner_id)
            if not include_archived:
                query = query.where(Document.archived == False)  # noqa: E712
            scope = project_clause(Document.project_id, visible_projects)
            if scope is not None:
                query = query.where(scope)
            rows = session.exec(
                query.order_by(Document.updated_at.desc())  # type: ignore[attr-defined]
            ).all()
            return [self._to_summary(row) for row in rows]

        return await in_session(self._engine, work)

    async def list_by_conversation(
        self, owner_id: str, conversation_id: str
    ) -> list[DocumentView]:
        """The active documents a chat thread created, oldest first — decrypted. Feeds
        the chat View (which documents to show) and the context injection (their current
        state), so both read the same source."""

        def work(session: Session) -> list[DocumentView]:
            rows = session.exec(
                select(Document)
                .where(
                    Document.owner_id == owner_id,
                    Document.conversation_id == conversation_id,
                    Document.archived == False,  # noqa: E712
                )
                .order_by(Document.created_at)  # type: ignore[attr-defined]
            ).all()
            return [self._view_from_row(row) for row in rows]

        return await in_session(self._engine, work)

    async def get(self, owner_id: str, document_id: str) -> DocumentView:
        document = await self._require(owner_id, document_id)
        return self._view_from_row(document)

    async def list_versions(
        self, owner_id: str, document_id: str
    ) -> list[DocumentVersionView]:
        """A document's version history, newest first (`DOC-2`)."""
        await self._require(owner_id, document_id)

        def work(session: Session) -> list[DocumentVersionView]:
            rows = session.exec(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version.desc())  # type: ignore[attr-defined]
            ).all()
            return [
                DocumentVersionView(
                    id=row.id,
                    version=row.version,
                    origin=row.origin,
                    title=self._vault.decrypt_str(row.title_enc),
                    body=self._vault.decrypt_str(row.body_enc),
                    created_at=row.created_at,
                    keeper=row.keeper,
                )
                for row in rows
            ]

        return await in_session(self._engine, work)

    async def list_user_edited(
        self, owner_id: str, conversation_id: str
    ) -> list[DocumentView]:
        """The thread's active documents whose *latest* version the operator authored — i.e.
        they edited it since the agent last wrote it. Two clear-column queries in one session
        (the docs, then their latest-version origin), decrypting a body only for the
        user-edited survivors — so a thread with no operator edits pays no decryption. Feeds
        the agent's current-document context (`DOC-*`)."""

        def work(session: Session) -> list[DocumentView]:
            docs = session.exec(
                select(Document).where(
                    Document.owner_id == owner_id,
                    Document.conversation_id == conversation_id,
                    Document.archived == False,  # noqa: E712
                )
            ).all()
            if not docs:
                return []
            ids = [d.id for d in docs]
            newest = (
                select(
                    DocumentVersion.document_id,
                    func.max(DocumentVersion.version).label("v"),
                )
                .where(DocumentVersion.document_id.in_(ids))  # type: ignore[attr-defined]
                .group_by(DocumentVersion.document_id)
                .subquery()
            )
            latest = session.exec(
                select(DocumentVersion.document_id, DocumentVersion.origin).join(
                    newest,
                    (DocumentVersion.document_id == newest.c.document_id)
                    & (DocumentVersion.version == newest.c.v),
                )
            ).all()
            user_ids = {
                did for did, origin in latest if origin == DocumentVersionOrigin.USER
            }
            return [self._view_from_row(d) for d in docs if d.id in user_ids]

        return await in_session(self._engine, work)

    async def count(self, owner_id: str) -> int:
        """How many active documents the owner has (the overview readout, never decrypts)."""

        def work(session: Session) -> int:
            return session.exec(
                select(func.count())
                .select_from(Document)
                .where(Document.owner_id == owner_id, Document.archived == False)  # noqa: E712
            ).one()

        return await in_session(self._engine, work)

    # --- internals --------------------------------------------------------

    async def _set_archived(
        self, owner_id: str, document_id: str, archived: bool
    ) -> DocumentView:
        await self._require(owner_id, document_id)

        def work(session: Session) -> DocumentView:
            document = session.get(Document, document_id)
            assert document is not None
            document.archived = archived
            document.updated_at = datetime.now(UTC)
            session.add(document)
            session.flush()
            return self._view_from_row(document)

        return await in_session(self._engine, work)

    async def _require(self, owner_id: str, document_id: str) -> Document:
        return await get_owned(self._engine, Document, document_id, owner_id, what="document")

    def _view_from_row(self, document: Document) -> DocumentView:
        return self._to_view(
            document,
            self._vault.decrypt_str(document.title_enc),
            self._vault.decrypt_str(document.body_enc),
        )

    def _to_summary(self, document: Document) -> DocumentSummaryView:
        snippet, word_count = summarize_body(self._vault.decrypt_str(document.body_enc))
        return DocumentSummaryView(
            id=document.id,
            title=self._vault.decrypt_str(document.title_enc),
            snippet=snippet,
            word_count=word_count,
            archived=document.archived,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    @staticmethod
    def _to_view(document: Document, title: str, body: str) -> DocumentView:
        return document_view(document, title, body)


# --- shared write helpers (also used by the suggestion lifecycle) ---------


def document_view(document: Document, title: str, body: str) -> DocumentView:
    """A :class:`DocumentView` over a row plus its already-decrypted title/body."""
    return DocumentView(
        id=document.id,
        title=title,
        body=body,
        doc_type=document.doc_type,
        language=document.language,
        archived=document.archived,
        created_at=document.created_at,
        updated_at=document.updated_at,
        conversation_id=document.conversation_id,
    )


def write_body(vault: Vault, document: Document, body: str) -> None:
    """Seal ``body`` onto the row and re-derive its display hints. One place where a body
    write happens, so every path (edit, targeted replace, an accepted suggestion) seals and
    re-detects identically. The caller still stamps ``updated_at`` and snapshots."""
    document.body_enc = vault.encrypt_str(body)
    document.doc_type, document.language = detect_type_language(body)


def snapshot_version(
    session: Session, document: Document, origin: str
) -> DocumentVersion:
    """Append a full sealed snapshot of ``document`` as its next version. Reuses the
    already-sealed title/body ciphertext on the row — no re-encryption."""
    next_version = _max_version(session, document.id) + 1
    snapshot = DocumentVersion(
        owner_id=document.owner_id,
        document_id=document.id,
        version=next_version,
        title_enc=document.title_enc,
        body_enc=document.body_enc,
        doc_type=document.doc_type,
        language=document.language,
        origin=origin,
    )
    session.add(snapshot)
    return snapshot


# --- list-summary derivation (off the DB hot path) ------------------------


def _max_version(session: Session, document_id: str) -> int:
    """The document's highest version number (0 if none) — the clear-column max-version read
    ``_snapshot`` uses to mint the next version."""
    return (
        session.exec(
            select(func.max(DocumentVersion.version)).where(
                DocumentVersion.document_id == document_id
            )
        ).one()
        or 0
    )


def summarize_body(body: str) -> tuple[str, int]:
    """A short first-line snippet + a word count for a library row, so the list response
    carries no full bodies. The snippet is the first non-blank line, capped at 140 chars."""
    first_line = next((line for line in body.splitlines() if line.strip()), "")
    snippet = f"{first_line[:140]}…" if len(first_line) > 140 else first_line
    return snippet, len(body.split())


# --- type / language detection (best-effort, off the DB hot path) ---------

_CODE_HINT = re.compile(
    r"^\s*(def |class |import |from \w+ import |function |const |let |var |#include|"
    r"public |private |package |using |fn |func )",
    re.MULTILINE,
)
_MD_HINT = re.compile(r"(^#{1,6}\s)|(```)|(^\s*[-*]\s)|(\[.+\]\(.+\))", re.MULTILINE)


def detect_type_language(body: str) -> tuple[str, str | None]:
    """Guess a coarse ``doc_type`` and a human ``language`` for display.

    Type is a cheap structural heuristic (markdown markers vs. code openers vs. plain
    prose). Language uses ``langdetect`` when available, best-effort — any failure
    (empty text, no model, ambiguous input) degrades to ``None`` rather than blocking
    the write, the same posture the embedder takes."""
    doc_type = "text"
    if _MD_HINT.search(body):
        doc_type = "markdown"
    elif _CODE_HINT.search(body):
        doc_type = "code"

    language: str | None = None
    stripped = body.strip()
    if stripped:
        try:
            from langdetect import detect  # imported lazily — optional, off the hot path

            language = detect(stripped)
        except Exception:  # noqa: BLE001 — detection is best-effort; never fail a write
            language = None
    return doc_type, language
