"""Pillar II — the event protocol (the backend↔frontend contract).

The frozen v1 typed event union. Framing: SSE, each frame's ``id:`` is the
per-run monotonic ``seq`` and ``data:`` is the flat JSON envelope
``{type, seq, ts, ...payload}``. Naming is ``entity.event``, dot.lowercase —
past-tense verbs for things that happened, ``delta``/``progress`` for streams.

Producers build a typed body (e.g. ``AnswerDelta(text=...)``); the Run stamps
``seq``/``ts`` at emit time and wraps it in an :class:`Event`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1


def now_utc() -> datetime:
    return datetime.now(UTC)


class _Body(BaseModel):
    model_config = ConfigDict(frozen=True)


# --- Run ---------------------------------------------------------------------
class RunStarted(_Body):
    type: Literal["run.started"] = "run.started"
    run_id: str
    kind: str
    protocol_version: int = PROTOCOL_VERSION


class RunMetrics(_Body):
    type: Literal["run.metrics"] = "run.metrics"
    steps: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


class RunEnded(_Body):
    type: Literal["run.ended"] = "run.ended"
    outcome: Literal["done", "blocked", "cancelled"]
    detail: str | None = None


class RunError(_Body):
    type: Literal["run.error"] = "run.error"
    message: str
    kind: str | None = None


# --- Step --------------------------------------------------------------------
class StepStarted(_Body):
    type: Literal["step.started"] = "step.started"
    index: int
    title: str | None = None


class StepCompleted(_Body):
    type: Literal["step.completed"] = "step.completed"
    index: int


# --- Content (the reasoning/answer split) ------------------------------------
class ThinkingDelta(_Body):
    type: Literal["thinking.delta"] = "thinking.delta"
    text: str


class AnswerDelta(_Body):
    type: Literal["answer.delta"] = "answer.delta"
    text: str


# --- Tools (full args + results inline, not summaries) -----------------------
class ToolStarted(_Body):
    type: Literal["tool.started"] = "tool.started"
    tool_call_id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolProgress(_Body):
    type: Literal["tool.progress"] = "tool.progress"
    tool_call_id: str
    elapsed_s: float | None = None
    partial: str | None = None


class ToolCompleted(_Body):
    type: Literal["tool.completed"] = "tool.completed"
    tool_call_id: str
    name: str
    result: Any = None


class ToolFailed(_Body):
    type: Literal["tool.failed"] = "tool.failed"
    tool_call_id: str
    name: str
    error: str


# --- Documents ---------------------------------------------------------------
class DocumentCreated(_Body):
    type: Literal["document.created"] = "document.created"
    document_id: str
    title: str | None = None


class DocumentDelta(_Body):
    type: Literal["document.delta"] = "document.delta"
    document_id: str
    text: str


class DocumentCommitted(_Body):
    type: Literal["document.committed"] = "document.committed"
    document_id: str
    version: int


# --- Artifacts (previewable output the agent published) ----------------------
class ArtifactPublished(_Body):
    """The agent surfaced a file for preview; fetch its bytes from the artifact
    route. ``kind`` is a coarse rendering hint. Additive to v1; no bump."""

    type: Literal["artifact.published"] = "artifact.published"
    artifact_id: str
    conversation_id: str
    title: str
    filename: str
    content_type: str
    kind: str  # "html" | "image" | "text" | "other"


class PreviewReady(_Body):
    """The agent started a live server. ``url`` is a token-gated proxy path on this
    same API origin (``/previews/{token}/``) that streams the server's HTTP and
    WebSocket traffic out of the sandbox.

    Frontend contract: mount it as ``<iframe src={url}>`` with
    ``sandbox="allow-scripts allow-forms allow-popups"`` — deliberately **without**
    ``allow-same-origin``, so the framed (model-generated) app runs in an opaque
    origin and cannot act as the operator against the API. The token in the path is
    the credential, so no auth header is needed and relative subresources/WebSockets
    resolve automatically. Additive to v1; no bump."""

    type: Literal["preview.ready"] = "preview.ready"
    conversation_id: str
    url: str  # "/previews/{token}/"
    title: str | None = None
    command: str  # the server command, for display
    port: int  # the in-container port it listens on


class PreviewStopped(_Body):
    """A live preview was torn down (explicitly via stop_preview, or reaped with its
    idle session); the frontend should drop the iframe for this conversation."""

    type: Literal["preview.stopped"] = "preview.stopped"
    conversation_id: str


# --- Conversation ------------------------------------------------------------
class ConversationTitled(_Body):
    """The chassis named a freshly-created conversation from its first exchange,
    so the operator never has to. The title is persisted too; the frontend reveals
    it with a typing animation. Emitted mid-run (before ``run.ended``) so a still-
    open stream carries it. Additive to v1; no bump."""

    type: Literal["conversation.titled"] = "conversation.titled"
    conversation_id: str
    title: str


# --- Notices -----------------------------------------------------------------
class CitationAdded(_Body):
    type: Literal["citation.added"] = "citation.added"
    url: str
    title: str | None = None
    source_index: int | None = None


class ApprovalRequired(_Body):
    """A sensitive action is parked awaiting operator approval."""

    type: Literal["approval.required"] = "approval.required"
    tool_call_id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str
    # Plain-language description of what the action does and its effect, so the
    # operator can judge it without reading the raw arguments — set when the tool
    # supplies one (the host-execution path requires it). Additive to v1; no bump.
    explanation: str | None = None


class LimitNotice(_Body):
    type: Literal["limit.notice"] = "limit.notice"
    limit: str  # "steps" | "tool_calls" | "tokens" | "time"
    message: str


EventBody = Annotated[
    RunStarted
    | RunMetrics
    | RunEnded
    | RunError
    | StepStarted
    | StepCompleted
    | ThinkingDelta
    | AnswerDelta
    | ToolStarted
    | ToolProgress
    | ToolCompleted
    | ToolFailed
    | DocumentCreated
    | DocumentDelta
    | DocumentCommitted
    | CitationAdded
    | ArtifactPublished
    | PreviewReady
    | PreviewStopped
    | ConversationTitled
    | ApprovalRequired
    | LimitNotice,
    Field(discriminator="type"),
]


@dataclass(frozen=True, slots=True)
class Event:
    """A stamped event: the producer's body plus the run-assigned seq/ts."""

    seq: int
    ts: datetime
    body: BaseModel

    def envelope(self) -> dict[str, Any]:
        """Flat ``{type, seq, ts, ...payload}`` dict — the on-the-wire shape."""
        data = self.body.model_dump(mode="json")
        data["seq"] = self.seq
        data["ts"] = self.ts.isoformat()
        return data

    def sse(self) -> str:
        """One SSE frame: ``id:`` carries seq for Last-Event-ID resume."""
        payload = json.dumps(self.envelope(), separators=(",", ":"))
        return f"id: {self.seq}\ndata: {payload}\n\n"
