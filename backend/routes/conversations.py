"""Conversations surface — browse, read, rename, and delete chat threads.

Thin pass-throughs to the :class:`ConversationStore`. Creating a conversation is
a chat concern (``POST /chat`` does it as a side effect of starting a turn); this
router only reads and manages the threads that already exist. History is returned
as a render-ready projection — the durable record stays full-fidelity
``ModelMessage`` blobs; the frontend never sees those.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent.title import title_from_history
from core.config import get_settings
from core.exceptions import DegradedCapabilityError, NotFoundError
from routes import deps
from routes.deps import OPERATOR_ID
from runs import ContextWindow
from services.artifacts import ArtifactView, artifact_id_from_result
from services.conversation_view import MessageView
from services.conversations import ConversationSummaryView, context_footprint

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str | None = None
    model: str | None = None  # the model the conversation last ran on


class ToolCallOut(BaseModel):
    id: str
    name: str
    args: dict[str, Any]
    status: str
    result: Any = None
    error: str | None = None


class ArtifactRefOut(BaseModel):
    """A published artifact re-attached to the message that produced it, mirroring
    the live ``artifact.published`` event so a cold read renders like a warm one."""

    artifact_id: str
    title: str
    filename: str
    content_type: str
    kind: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    reasoning: str | None = None
    tools: list[ToolCallOut] = []
    artifacts: list[ArtifactRefOut] = []
    created_at: datetime | None = None
    model: str | None = None  # the model that produced this assistant turn
    # Version navigation: position among this turn's siblings and how many exist.
    # version_count > 1 ⇒ the operator can cycle ‹ k/n › between regenerations/edits.
    version_index: int = 0
    version_count: int = 1
    pinned: bool = False  # the operator's durable bookmark on this turn


class ActiveRun(BaseModel):
    """The in-flight run driving this conversation, when one exists. A streaming
    turn isn't persisted until it finishes, so on a cold read (e.g. a page reload
    mid-stream) the messages alone show no answer — this points the client at the
    run whose events it can replay and resume from ``last_seq``."""

    id: str
    status: str
    last_seq: int


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]
    # The context-window state reconstructed from the last turn's stored usage, so
    # an existing thread shows its fullness on load — not just after the next turn.
    # Null when usage or a window is unavailable.
    context: ContextWindow | None = None
    # Present only while a turn is still streaming server-side — lets a reattaching
    # client resume the live run instead of rendering a reply-less thread.
    active_run: ActiveRun | None = None


class TitleUpdate(BaseModel):
    title: str | None = None


class RetitleRequest(BaseModel):
    """The picker selection to name the thread with. The conversation does not
    persist a per-turn endpoint, so a manual re-title resolves the title model the
    same way a chat turn does — through the operator's current pick — rather than the
    bare default ``main``/``utility`` roles (which a picker-driven operator may never
    have bound). Both optional: an absent pick falls back to those defaults."""

    endpoint_id: str | None = None
    model: str | None = None


class VersionSwitch(BaseModel):
    index: int  # which sibling version to make active (0-based)


class PinUpdate(BaseModel):
    pinned: bool


def _summary(view: ConversationSummaryView) -> ConversationSummary:
    return ConversationSummary(
        id=view.id,
        title=view.title,
        created_at=view.created_at,
        updated_at=view.updated_at,
        message_count=view.message_count,
        preview=view.preview,
        model=view.model,
    )


def _message_artifacts(
    view: MessageView, by_id: dict[str, ArtifactView]
) -> list[ArtifactRefOut]:
    """The artifacts this turn published, recovered from its ``publish_artifact``
    tool results (each carries the artifact id). A failed publish has no id and is
    skipped, so the cold read attaches exactly what warmly streamed."""
    refs: list[ArtifactRefOut] = []
    for tool in view.tools:
        if not tool.name.endswith("publish_artifact") or not isinstance(tool.result, str):
            continue
        artifact_id = artifact_id_from_result(tool.result)
        artifact = by_id.get(artifact_id) if artifact_id else None
        if artifact is not None:
            refs.append(
                ArtifactRefOut(
                    artifact_id=artifact.id,
                    title=artifact.title,
                    filename=artifact.filename,
                    content_type=artifact.content_type,
                    kind=artifact.kind,
                )
            )
    return refs


def _message(view: MessageView, by_id: dict[str, ArtifactView]) -> MessageOut:
    return MessageOut(
        id=view.id,
        role=view.role,
        content=view.content,
        reasoning=view.reasoning or None,
        tools=[
            ToolCallOut(
                id=t.id, name=t.name, args=t.args, status=t.status, result=t.result, error=t.error
            )
            for t in view.tools
        ],
        artifacts=_message_artifacts(view, by_id),
        created_at=view.timestamp,
        model=view.model,
        version_index=view.version_index,
        version_count=view.version_count,
        pinned=view.pinned,
    )


async def _detail(
    request: Request, conversation_id: str, summary: ConversationSummaryView
) -> ConversationDetail:
    """Assemble a conversation's full render-ready detail (active path + published
    artifacts + reconstructed context-window state). Shared by the read endpoint
    and the navigation endpoints that return the post-move thread (version switch,
    rewind)."""
    store = deps.store(request)
    messages = await store.messages_view(conversation_id)
    # Seed the context meter from the last turn's footprint; only pay to resolve the
    # window when there's a footprint to measure against it. The window is the
    # default ``main`` model's (no per-conversation endpoint is persisted, so that's
    # what the next turn would run on).
    used = context_footprint(await store.history(conversation_id))
    context: ContextWindow | None = None
    if used is not None:
        window = await deps.models(request).main_context_window(OPERATOR_ID)
        context = ContextWindow.from_used(used, window)
    # Only pay for the artifacts lookup when a turn actually published something —
    # the vast majority of conversations never call publish_artifact.
    published = any(t.name.endswith("publish_artifact") for m in messages for t in m.tools)
    by_id: dict[str, ArtifactView] = {}
    if published:
        artifacts = await deps.artifacts(request).list(OPERATOR_ID, conversation_id)
        by_id = {a.id: a for a in artifacts}
    run = deps.registry(request).active_run_for(conversation_id, OPERATOR_ID)
    active_run = (
        ActiveRun(id=run.id, status=run.status.value, last_seq=run.stream.last_seq)
        if run is not None
        else None
    )
    return ConversationDetail(
        **_summary(summary).model_dump(),
        messages=[_message(m, by_id) for m in messages],
        context=context,
        active_run=active_run,
    )


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(request: Request) -> list[ConversationSummary]:
    views = await deps.store(request).list_conversations(OPERATOR_ID)
    return [_summary(v) for v in views]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    summary = await deps.store(request).get_summary(conversation_id, OPERATOR_ID)
    if summary is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return await _detail(request, conversation_id, summary)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str, body: TitleUpdate, request: Request
) -> ConversationSummary:
    store = deps.store(request)
    if await store.get_summary(conversation_id, OPERATOR_ID) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    await store.set_title(conversation_id, body.title)
    summary = await store.get_summary(conversation_id, OPERATOR_ID)
    if summary is None:  # pragma: no cover — just confirmed it exists
        raise HTTPException(status_code=404, detail="conversation not found")
    return _summary(summary)


@router.post("/{conversation_id}/retitle", response_model=ConversationSummary)
async def retitle_conversation(
    conversation_id: str, request: Request, body: RetitleRequest | None = None
) -> ConversationSummary:
    """Regenerate a thread's title on demand, from every question the operator asked
    across the whole conversation — not just its opening line (the first-turn
    auto-titler's input). A manual re-name exists to fix a title that the opening
    missed or that went stale as the thread drifted, so feeding the full arc is what
    makes it meaningful. Only the operator's turns are fed in, never assistant or
    tool output, keeping the small title model off injectable content. Unlike the
    fill-only-if-blank auto-titler, this overwrites unconditionally — it is a
    deliberate operator action.

    The title model is resolved exactly as a chat turn resolves its background work
    (``utility`` → the picked ``main``), requesting reasoning **off** — and it works
    for a picker-driven operator who has no default role bound. The full-arc input here
    is longer than the auto-titler's opening-message excerpt, so a model whose runtime
    ignores the reasoning-off lever (e.g. LM Studio + Qwen) produces a longer ``<think>``
    block; the wider ``retitle_max_tokens`` budget and ``retitle_timeout_s`` give it room
    to think *and* emit the title, which :func:`agent.title` then strips clean."""
    store = deps.store(request)
    if await store.get_summary(conversation_id, OPERATOR_ID) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    pick = body or RetitleRequest()
    try:
        title = await deps.models(request).resolve_background(
            owner_id=OPERATOR_ID,
            override_endpoint_id=pick.endpoint_id,
            override_model=pick.model,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="model endpoint not found") from None
    except DegradedCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    name = await title_from_history(
        title.model,
        await store.history(conversation_id),
        full=True,
        reasoning_off=title.reasoning_off,
        timeout_s=get_settings().retitle_timeout_s,
        max_tokens=get_settings().retitle_max_tokens,
    )
    if name is None:
        raise HTTPException(status_code=503, detail="could not generate a title")
    await store.set_title(conversation_id, name)
    summary = await store.get_summary(conversation_id, OPERATOR_ID)
    if summary is None:  # pragma: no cover — just confirmed it exists
        raise HTTPException(status_code=404, detail="conversation not found")
    return _summary(summary)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request) -> None:
    store = deps.store(request)
    if await store.get_summary(conversation_id, OPERATOR_ID) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    await store.delete_conversation(conversation_id)


async def _require_owned(request: Request, conversation_id: str) -> ConversationSummaryView:
    summary = await deps.store(request).get_summary(conversation_id, OPERATOR_ID)
    if summary is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return summary


@router.delete("/{conversation_id}/messages/{message_id}", response_model=ConversationDetail)
async def delete_message(
    conversation_id: str, message_id: str, request: Request
) -> ConversationDetail:
    """Remove a turn and everything after it on every branch (its subtree). The
    active path falls back to the deleted turn's parent. Returns the resulting
    thread so the client reseats in one round-trip (like version switch / rewind)."""
    store = deps.store(request)
    summary = await _require_owned(request, conversation_id)
    if not await store.delete_message(conversation_id, message_id):
        raise HTTPException(status_code=404, detail="message not found")
    return await _detail(request, conversation_id, summary)


@router.post("/{conversation_id}/messages/{message_id}/version", response_model=ConversationDetail)
async def switch_version(
    conversation_id: str, message_id: str, body: VersionSwitch, request: Request
) -> ConversationDetail:
    """Cycle a turn to one of its sibling versions (a prior regeneration/edit) and
    return the resulting thread."""
    store = deps.store(request)
    summary = await _require_owned(request, conversation_id)
    if not await store.switch_version(conversation_id, message_id, body.index):
        raise HTTPException(status_code=404, detail="version not found")
    return await _detail(request, conversation_id, summary)


@router.post("/{conversation_id}/messages/{message_id}/pin", status_code=204)
async def pin_message(
    conversation_id: str, message_id: str, body: PinUpdate, request: Request
) -> None:
    """Pin or unpin a turn — a durable bookmark surfaced in the projection."""
    store = deps.store(request)
    await _require_owned(request, conversation_id)
    if not await store.set_pin(conversation_id, message_id, body.pinned):
        raise HTTPException(status_code=404, detail="message not found")


@router.post("/{conversation_id}/messages/{message_id}/rewind", response_model=ConversationDetail)
async def rewind(conversation_id: str, message_id: str, request: Request) -> ConversationDetail:
    """Move the active tip back to this turn so the thread ends there; the next
    message branches from it (the later turns stay reachable as a sibling version)."""
    store = deps.store(request)
    summary = await _require_owned(request, conversation_id)
    if not await store.rewind(conversation_id, message_id):
        raise HTTPException(status_code=404, detail="message not found")
    return await _detail(request, conversation_id, summary)
