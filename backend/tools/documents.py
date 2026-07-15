"""Document tools — the agent writes and revises a document live in the chat View.

A document is a piece of the operator's own writing (`DOC-1`/`DOC-2`), versioned and
encrypted at rest by ``services/documents``. These tools let the agent *create* one and
make *targeted* edits to it; each write streams into the conversation's View as a new
version (``document.created`` / ``document.delta`` / ``document.committed``), so the
operator watches the document take shape beside the chat and can edit it back inline.

Provenance decides approval, not a blanket gate: a document the agent created **in this
conversation** is its own scratch surface and edits run freely; editing a document it did
*not* create here — one from the operator's library or another thread — **pauses for
approval** on the first edit (the same ``ApprovalRequired`` defer the recall gate uses),
so the agent can't silently rewrite the operator's existing writing. The operator can
approve once or for the whole conversation.

Like every tool here this is a thin adapter: the versioning, encryption, and corpus
re-indexing live in ``DocumentStore``; a missing store degrades to an "unavailable"
message rather than failing the turn.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired

from core.exceptions import DocumentSpanError, NotFoundError
from runs import DocumentCommitted, DocumentCreated, DocumentDelta
from services.documents import DocumentVersionOrigin

from .deps import RunDeps


def document_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def create(ctx: RunContext[RunDeps], title: str, content: str) -> str:
        """Create a new document and show it to the operator in this conversation's View,
        beside the chat, where it renders as markdown (with LaTeX math).

        Use this to *write* something the operator keeps and reads — a report, a draft, a
        summary, notes — not to store scratch data or code you run. ``content`` is the full
        initial body (Markdown). Returns the document's id; pass it to ``document_edit`` to
        revise the document rather than creating a new one each time."""
        store = ctx.deps.documents
        if store is None:
            return "Documents are unavailable right now."
        view = await store.create(
            ctx.deps.owner_id,
            title,
            content,
            conversation_id=ctx.deps.conversation_id,
            origin=DocumentVersionOrigin.AI,
        )
        ctx.deps.run.emit(DocumentCreated(document_id=view.id, title=title))
        ctx.deps.run.emit(DocumentDelta(document_id=view.id, text=content))
        # Version 1 is the document's first version, minted microseconds after the row in
        # the same atomic create — no other version or snapshot can sort between them — so
        # the document's ``created_at`` is a safe, inversion-free ordering key here.
        ctx.deps.run.emit(
            DocumentCommitted(document_id=view.id, version=1, created_at=view.created_at)
        )
        return (
            f"Created the document {title!r} (id: {view.id}). "
            "Edit it later with document_edit using this id."
        )

    @toolset.tool
    async def edit(
        ctx: RunContext[RunDeps],
        document_id: str,
        old_text: str,
        new_text: str,
        explanation: str = "",
    ) -> str:
        """Make a targeted edit to a document: replace ``old_text`` with ``new_text``.

        ``old_text`` must match **exactly one** span of the current document (copy it
        verbatim, including whitespace); if it's ambiguous, include more surrounding text
        until it's unique. To replace a whole section, let ``old_text`` be that whole
        section. The View updates live and records a new version.

        If you are editing a document you did **not** create in this conversation (one from
        the operator's library or another chat), the operator is asked to approve the first
        edit — set ``explanation`` to a plain-language note of what you're changing and why,
        which is shown on the approval prompt. For a document you created here, no approval
        is needed and ``explanation`` is ignored."""
        store = ctx.deps.documents
        if store is None:
            return "Documents are unavailable right now."
        try:
            doc = await store.get(ctx.deps.owner_id, document_id)
        except NotFoundError as exc:
            raise ModelRetry(
                f"No document with id {document_id!r} — it may have been deleted. "
                "Check the id or create a new document instead."
            ) from exc

        # Provenance gate: a document born in *this* conversation is the agent's own surface
        # (ungated); anything else — a library doc (no conversation) or one from another
        # thread — pauses for approval on the first edit. Keyed off positive provenance (a
        # real matching conversation), so a run with no conversation can't slip an ungated
        # edit through on the None == None coincidence. `tool_call_approved` is set on the
        # re-invocation after the operator approves, so this raises at most once.
        born_here = (
            ctx.deps.conversation_id is not None
            and doc.conversation_id == ctx.deps.conversation_id
        )
        if not born_here and not ctx.tool_call_approved:
            raise ApprovalRequired()

        # The find/replace + uniqueness check is the store's job (a domain edit reusable by
        # non-agent callers); the tool only maps its span error to a model-facing retry.
        try:
            _view, version, created_at = await store.replace_span(
                ctx.deps.owner_id,
                document_id,
                old_text,
                new_text,
                origin=DocumentVersionOrigin.AI,
            )
        except DocumentSpanError as exc:
            if exc.occurrences == 0:
                raise ModelRetry(
                    "old_text was not found in the document — copy it verbatim from the "
                    "current body (including whitespace)."
                ) from exc
            raise ModelRetry(
                f"old_text matches {exc.occurrences} places — include more surrounding text "
                "so it identifies exactly one span."
            ) from exc
        ctx.deps.run.emit(DocumentDelta(document_id=document_id, text=_view.body))
        ctx.deps.run.emit(
            DocumentCommitted(
                document_id=document_id, version=version, created_at=created_at
            )
        )
        return f"Edited {doc.title!r} (now version {version})."

    return toolset
