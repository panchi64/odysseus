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

from routes import deps
from routes.deps import OPERATOR_ID
from services.artifacts import ArtifactView, artifact_id_from_result
from services.conversation_view import MessageView
from services.conversations import ConversationSummaryView

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    preview: str | None = None


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


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


class TitleUpdate(BaseModel):
    title: str | None = None


def _summary(view: ConversationSummaryView) -> ConversationSummary:
    return ConversationSummary(
        id=view.id,
        title=view.title,
        created_at=view.created_at,
        updated_at=view.updated_at,
        message_count=view.message_count,
        preview=view.preview,
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


def _message(index: int, view: MessageView, by_id: dict[str, ArtifactView]) -> MessageOut:
    return MessageOut(
        id=f"m{index}",
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
    )


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(request: Request) -> list[ConversationSummary]:
    views = await deps.store(request).list_conversations(OPERATOR_ID)
    return [_summary(v) for v in views]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    store = deps.store(request)
    summary = await store.get_summary(conversation_id, OPERATOR_ID)
    if summary is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = await store.messages_view(conversation_id)
    # Only pay for the artifacts lookup when a turn actually published something —
    # the vast majority of conversations never call publish_artifact.
    published = any(
        t.name.endswith("publish_artifact") for m in messages for t in m.tools
    )
    by_id: dict[str, ArtifactView] = {}
    if published:
        artifacts = await deps.artifacts(request).list(OPERATOR_ID, conversation_id)
        by_id = {a.id: a for a in artifacts}
    return ConversationDetail(
        **_summary(summary).model_dump(),
        messages=[_message(i, m, by_id) for i, m in enumerate(messages)],
    )


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


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request) -> None:
    store = deps.store(request)
    if await store.get_summary(conversation_id, OPERATOR_ID) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    await store.delete_conversation(conversation_id)
