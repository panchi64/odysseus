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

from pydantic import BaseModel, ConfigDict, Field, computed_field

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


class ContextWindow(_Body):
    """How full a model's context window is after a turn — the single owner of
    the fullness derivation and its severity thresholds. Built by
    :meth:`from_usage` and emitted both live (run metrics) and on load
    (conversation detail), so clients render one shape from either source."""

    used: int  # tokens occupying the window: last response's prompt + generation
    window: int  # the model's context window
    fraction: float  # used / window, clamped to 0–1
    level: Literal["nominal", "warn", "alert"]

    @classmethod
    def from_used(cls, used: int | None, window: int | None) -> ContextWindow | None:
        """Derive the window state from the context footprint (``used``), or None
        when there's no ceiling to measure against or no footprint was reported.
        Severity is nominal until 75% full, warn to 90%, then alert."""
        if not window or used is None:
            return None
        fraction = min(1.0, used / window)
        level = "alert" if fraction >= 0.9 else "warn" if fraction >= 0.75 else "nominal"
        return cls(used=used, window=window, fraction=fraction, level=level)


class RunMetrics(_Body):
    type: Literal["run.metrics"] = "run.metrics"
    steps: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    # The model's context window, when known — the ceiling the derived `context`
    # measures against. Null when the endpoint declares none.
    context_window: int | None = None
    # The context footprint after this turn: the *last* model response's prompt +
    # generation (what the next turn carries forward). Deliberately NOT the run's
    # cumulative input/output above — those sum every internal model request and
    # would overstate fullness several-fold on tool-calling or multi-turn runs.
    context_used: int | None = None

    @computed_field
    @property
    def context(self) -> ContextWindow | None:
        """The context-window fullness after this turn — null when unmeasurable
        (no window, or no footprint). Clients render it; they never derive it."""
        return ContextWindow.from_used(self.context_used, self.context_window)


class RunEnded(_Body):
    """The closing frame for a run that reached an *expected* end.

    A run closes with exactly one of `run.ended` or `run.error`, never both — the
    terminal frame has two shapes because the two carry different payloads, and a
    failure has a message and an exception kind where an expected end has an outcome
    and a detail. Readers treat either as end-of-stream (`isTerminal` on the client).
    `error` is deliberately absent from ``outcome`` for that reason: it is not an
    outcome this frame ever carries. Both are preceded by `run.metrics`.
    """

    type: Literal["run.ended"] = "run.ended"
    outcome: Literal["done", "blocked", "cancelled"]
    detail: str | None = None


class RunError(_Body):
    """The closing frame for a run that failed. See :class:`RunEnded` — these two are
    the same terminal position in the protocol, not a frame plus an extra."""

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
    # The committed version's mint time — the authoritative ordering key, the same
    # ``DocumentVersion.created_at`` the cold read serves. The frontend orders the View's
    # versions by it, so a version minted live sorts identically to one read back on
    # refresh (without it the client had to fabricate a timestamp and could misorder).
    created_at: datetime


# --- View (the conversation's one versioned output surface) ------------------
# The View is one canvas with a history of **versions** to compare plus an optional
# live **head**. A version is one ``view.snapshot`` (the captured workspace tree +
# how it previews); ``view.live`` / ``view.live.stopped`` are the interactive head
# overlaid on the latest version.
class ViewLive(_Body):
    """The agent started (or replaced) the View's live head — a running server.
    ``url`` is a token-gated proxy path on this same API origin
    (``/previews/{token}/…``) that streams the server's HTTP and WebSocket traffic
    out of the sandbox.

    Frontend contract: mount it as ``<iframe src={url}>`` with
    ``sandbox="allow-scripts allow-forms allow-popups"`` — deliberately **without**
    ``allow-same-origin``, so the framed (model-generated) app runs in an opaque
    origin and cannot act as the operator against the API. The token in the path is
    the credential, so no auth header is needed and relative subresources/WebSockets
    resolve automatically. ``url`` already carries the entry path when one was given,
    so it renders the page rather than a directory listing. Additive to v1; no bump."""

    type: Literal["view.live"] = "view.live"
    conversation_id: str
    url: str  # "/previews/{token}/<entry>"
    title: str | None = None
    command: str  # the server command, for display
    port: int  # the in-container port it listens on


class ViewLiveStopped(_Body):
    """The View's live head was torn down (explicitly via close_view, or reaped with
    its idle session); the frontend drops the live iframe for this conversation."""

    type: Literal["view.live.stopped"] = "view.live.stopped"
    conversation_id: str


class ViewSnapshot(_Body):
    """A new **version** of the conversation's View — minted by a ``show``. It captures
    the agent's sandbox tree (the version's code, browsable + diffable via
    ``/views/snapshots/{snapshot_id}/…``) and how it previews: ``preview_artifact_id``
    + ``preview_kind`` point at the captured-bytes preview of a ``show(file=…)`` (fetch
    them from ``/views/{preview_artifact_id}/content``), or both are null for a
    live/auto preview (a running head, or the frontend auto-picks an entry HTML page).
    Additive to v1; no bump."""

    type: Literal["view.snapshot"] = "view.snapshot"
    conversation_id: str
    snapshot_id: str
    title: str | None = None
    created_at: datetime
    files_changed: int
    summary: str  # compact change tally, e.g. "+2 ~1 −0"
    preview_kind: str | None = None  # "html" | "image" | "text" | "other" | None
    preview_artifact_id: str | None = None


# --- Conversation ------------------------------------------------------------
class ConversationTitled(_Body):
    """The chassis named a freshly-created conversation from its first exchange,
    so the operator never has to. The title is persisted too; the frontend reveals
    it with a typing animation. Emitted mid-run (before ``run.ended``) so a still-
    open stream carries it. Additive to v1; no bump."""

    type: Literal["conversation.titled"] = "conversation.titled"
    conversation_id: str
    title: str


class ConversationCompacted(_Body):
    """The thread's earlier turns were folded into a summary before this turn ran,
    because its context footprint had reached the operator's threshold. Nothing was
    deleted — the transcript keeps every turn; this marks where the *model's* replayed
    view narrows to ``summary`` plus the turns after it. Emitted mid-run (before the
    answer streams) so a live client can drop the divider in as it happens, and
    persisted as its own message so a reload renders the same thing. Additive to v1;
    no bump."""

    type: Literal["conversation.compacted"] = "conversation.compacted"
    conversation_id: str
    # The checkpoint message the summary is stored on — the node the client renders
    # the divider against, and the same id a cold read returns.
    message_id: str
    summary: str
    # How many messages the summary stands in for, so the divider can say so without
    # the client counting anything itself.
    messages_compacted: int
    # The rendered turn the divider follows. A live client addresses turns, not tree
    # nodes, so the backend resolves the position rather than leaving the client to
    # approximate it and land somewhere a reload disagrees with. Null => append.
    after_message_id: str | None = None


# --- Notices -----------------------------------------------------------------
class CitationAdded(_Body):
    type: Literal["citation.added"] = "citation.added"
    url: str
    title: str | None = None


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


class MessageQueued(_Body):
    """The operator sent a message while this run was still executing; it is
    queued for injection at the run's next model-request boundary. ``text`` rides
    inline so a reattaching client can rebuild the pending bubble purely from
    replay. Additive to v1; no bump."""

    type: Literal["message.queued"] = "message.queued"
    message_id: str
    text: str


class MessageEdited(_Body):
    """The operator rewrote a queued message's text before the run consumed it.
    ``text`` is the full replacement (not a delta), inline for the same reason as
    ``message.queued``'s: a reattaching client rebuilds the pending bubble purely
    from replay. Additive to v1; no bump."""

    type: Literal["message.edited"] = "message.edited"
    message_id: str
    text: str


class MessageWithdrawn(_Body):
    """The operator withdrew a queued message before the run consumed it.
    Additive to v1; no bump."""

    type: Literal["message.withdrawn"] = "message.withdrawn"
    message_id: str


class MessageInjected(_Body):
    """A queued message was handed to the model (emitted in drain order). From
    here on the message is part of the turn and will persist as a normal user
    message. Additive to v1; no bump."""

    type: Literal["message.injected"] = "message.injected"
    message_id: str


class PlanUpdated(_Body):
    """The agent's task list changed. Carries the **whole** list, not a delta: the stream
    is replayable from any seq, so full state is idempotent on replay and needs no ordering
    rules, and the list is small enough that the bytes don't matter. Each item is
    ``{id, content, status, active_form}`` with status one of pending/in_progress/
    completed/cancelled. Additive to v1; no bump."""

    type: Literal["plan.updated"] = "plan.updated"
    items: list[dict]


class LimitNotice(_Body):
    type: Literal["limit.notice"] = "limit.notice"
    # "steps" | "tool_calls" | "tokens" | "time" | "loop" | "verify" | "context" | "search"
    # ("context" = the model's context window was exceeded; the run stops, it isn't degraded.
    # "search" = deep research's two-empty-rounds abort.)
    limit: str
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
    | ViewLive
    | ViewLiveStopped
    | ViewSnapshot
    | ConversationTitled
    | ConversationCompacted
    | ApprovalRequired
    | MessageQueued
    | MessageEdited
    | MessageWithdrawn
    | MessageInjected
    | PlanUpdated
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
