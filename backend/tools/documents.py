"""Document tools — the agent writes, revises, and *proposes changes to* a document live
in the chat View.

A document is a piece of the operator's own writing (`DOC-1`/`DOC-2`), versioned and
encrypted at rest by ``services/documents``. These tools give the agent the three ways
`DOC-3` asks for: *create* one (a full rewrite is a create or a whole-body edit), make a
*targeted* edit, or **suggest** changes without applying any of them. Each streams into
the conversation's View (``document.created`` / ``document.delta`` /
``document.committed``), so the operator watches the document take shape beside the chat
and can edit it back inline.

**The first two apply; the third does not.** ``suggest`` records a pending set of anchored
changes and leaves the document byte-identical — the operator accepts or rejects them one
by one from the review surface, and only an accepted change ever mints a version.

Provenance decides approval, not a blanket gate: a document the agent created **in this
conversation** is its own scratch surface and edits run freely; touching a document it did
*not* create here — one from the operator's library or another thread — **pauses for
approval** on the first write (the same ``ApprovalRequired`` defer the recall gate uses),
so the agent can't silently rewrite the operator's existing writing. The operator can
approve once or for the whole conversation. Suggesting is gated on the same terms as
editing: it writes nothing to the document, but it does put a decision in front of the
operator about *their* writing, and the same one-time grant then covers both.

Like every tool here this is a thin adapter: the versioning, encryption, and corpus
re-indexing live in ``DocumentStore``; a missing store degrades to an "unavailable"
message rather than failing the turn.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired

from core.container import ServiceContainer
from core.exceptions import DocumentSpanError, NotFoundError
from runs import DocumentCommitted, DocumentCreated, DocumentDelta
from services.document_suggestions import ProposedChange, stream_preview
from services.documents import DocumentStore, DocumentVersionOrigin

from .deps import RunDeps


class ProposedEdit(BaseModel):
    """One change the agent proposes but does not apply."""

    old_text: str = Field(
        description="The exact span to replace, copied verbatim from the current document "
        "(including whitespace). Must match exactly one place."
    )
    new_text: str = Field(description="What that span should say instead.")
    explanation: str = Field(
        default="",
        description="A short plain-language note on why, shown beside this change in the "
        "operator's review.",
    )


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
        store = ctx.deps.caps.get_optional(DocumentStore)
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
        store = ctx.deps.caps.get_optional(DocumentStore)
        if store is None:
            return "Documents are unavailable right now."
        doc = await _load(store, ctx, document_id)
        _gate_foreign_document(ctx, doc)

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
            raise _span_retry(exc) from exc
        ctx.deps.run.emit(DocumentDelta(document_id=document_id, text=_view.body))
        ctx.deps.run.emit(
            DocumentCommitted(
                document_id=document_id, version=version, created_at=created_at
            )
        )
        return f"Edited {doc.title!r} (now version {version})."

    @toolset.tool
    async def suggest(
        ctx: RunContext[RunDeps],
        document_id: str,
        changes: list[ProposedEdit],
        summary: str = "",
    ) -> str:
        """Propose changes to a document **without applying any of them**.

        Use this instead of ``document_edit`` whenever the operator should decide — a pass
        over their own writing, anything stylistic or opinionated, or a set of changes worth
        weighing one at a time. Each entry in ``changes`` is an independent proposal: the
        operator reviews them change by change and accepts or rejects each one (or accepts
        them all at once). The document does not change until they accept, and rejecting
        leaves no trace.

        Every ``old_text`` must match **exactly one** span of the current document — copy it
        verbatim, whitespace included, and include more surrounding text if a short span
        would be ambiguous. If any single change fails that test the whole set is refused,
        so fix it and call again. ``summary`` is a one-line description of the pass as a
        whole ("tightened the intro and fixed the dates").

        Prefer this over rewriting a document that isn't yours to rewrite; use
        ``document_edit`` when the operator has already asked for the change directly."""
        store = ctx.deps.caps.get_optional(DocumentStore)
        if store is None:
            return "Documents are unavailable right now."
        if not changes:
            raise ModelRetry(
                "changes was empty — pass at least one proposed change, or use "
                "document_edit if you meant to apply an edit directly."
            )
        doc = await _load(store, ctx, document_id)
        _gate_foreign_document(ctx, doc)

        try:
            proposed = await store.suggestions.propose(
                ctx.deps.owner_id,
                document_id,
                [
                    ProposedChange(c.old_text, c.new_text, c.explanation)
                    for c in changes
                ],
                summary=summary,
                conversation_id=ctx.deps.conversation_id,
            )
        except DocumentSpanError as exc:
            raise _span_retry(exc) from exc

        # Stream the proposal into the View *as it is produced* (`DOC-3`), reusing the
        # document delta rather than inventing an event: each step shows what the document
        # would say once one more change lands. The last delta deliberately restores the
        # **current, unchanged** body — the View settles back on what the document actually
        # says, because nothing has been applied. The pending changes themselves are the
        # review surface, and no `document.committed` follows: a version exists only once
        # the operator accepts.
        for preview in stream_preview(
            doc.body, [(c.old_text, c.new_text) for c in changes]
        ):
            ctx.deps.run.emit(DocumentDelta(document_id=document_id, text=preview))
        ctx.deps.run.emit(DocumentDelta(document_id=document_id, text=doc.body))

        count = len(proposed.changes)
        return (
            f"Proposed {count} change{'' if count == 1 else 's'} to {doc.title!r} for the "
            "operator to review. Nothing has been applied — they accept or reject each "
            "change themselves, so don't re-apply these with document_edit."
        )

    return toolset


# --- shared tool-layer concerns ------------------------------------------


async def _load(store, ctx: RunContext[RunDeps], document_id: str):
    """The document, or a model-facing retry when the id is stale."""
    try:
        return await store.get(ctx.deps.owner_id, document_id)
    except NotFoundError as exc:
        raise ModelRetry(
            f"No document with id {document_id!r} — it may have been deleted. "
            "Check the id or create a new document instead."
        ) from exc


def _gate_foreign_document(ctx: RunContext[RunDeps], doc) -> None:
    """Provenance gate: a document born in *this* conversation is the agent's own surface
    (ungated); anything else — a library doc (no conversation) or one from another thread —
    pauses for approval on the first write. Keyed off positive provenance (a real matching
    conversation), so a run with no conversation can't slip an ungated write through on the
    ``None == None`` coincidence. ``tool_call_approved`` is set on the re-invocation after
    the operator approves, so this raises at most once — and one grant covers editing and
    suggesting alike."""
    born_here = (
        ctx.deps.conversation_id is not None
        and doc.conversation_id == ctx.deps.conversation_id
    )
    if not born_here and not ctx.tool_call_approved:
        raise ApprovalRequired()


def _span_retry(exc: DocumentSpanError) -> ModelRetry:
    """Turn a failed anchor into the phrasing that tells the model how to fix it."""
    if exc.occurrences == 0:
        return ModelRetry(
            "old_text was not found in the document — copy it verbatim from the "
            "current body (including whitespace)."
        )
    return ModelRetry(
        f"old_text matches {exc.occurrences} places — include more surrounding text "
        "so it identifies exactly one span."
    )


async def document_state_context(
    caps: ServiceContainer, owner_id: str, conversation_id: str | None
) -> str:
    """Give the agent the current text of any document the operator edited since its last
    write — as **per-turn prompt context** (the documents manifest's ``prompt_context``
    export), re-resolved fresh each turn (always the latest state) and never persisted,
    so there's exactly one copy in context, no compounding. The engine appends it at the
    *tail* of the current turn's user prompt rather than the instructions block: the
    instructions render at the head of every request, so this volatile (and potentially
    large) text there would invalidate the inference engine's prompt-prefix cache from
    byte 0 on every operator edit — at the tail, the whole replayed history stays
    byte-stable. Empty (no-op) when there's no such document or no store/conversation.

    Only documents whose *latest* version the operator authored qualify — the agent works
    from what the operator actually has now, not the copy it last produced (`DOC-*`); a
    document whose latest version is the agent's own is skipped (the model already knows
    that text). This is the operator's own content, so it is *not* wrapped as untrusted."""
    store = caps.get_optional(DocumentStore)
    if store is None or conversation_id is None:
        return ""
    docs = await store.list_user_edited(owner_id, conversation_id)
    return "\n\n".join(
        f'[Current state of the document "{doc.title}" — the operator may have edited it '
        f"since your last change]\n\n{doc.body}"
        for doc in docs
    )
