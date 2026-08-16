"""Pillar I + II — the Run substrate and the event protocol (the chassis).

A Run is one server-side, background-executing unit of work for one request.
Chat, agent, and research all ride it, so continuity, resume, cancellation,
timeouts, and metrics are written once here and inherited everywhere.

- :class:`RunRegistry` — launch/track/bound/cancel Runs (in-process asyncio).
- :class:`Run` / :class:`RunStatus` — the unit of work and its lifecycle.
- :class:`RunStream` — per-run event buffer + broker (resume via Last-Event-ID).
- ``events`` — the frozen v1 typed event union.
- :func:`sse_response` — stream a Run to a client over SSE.

See docs/architecture/README.md (Pillars I & II).
"""

from __future__ import annotations

from . import events
from .events import (
    PROTOCOL_VERSION,
    AnswerDelta,
    ApprovalRequired,
    CitationAdded,
    ContextWindow,
    ConversationTitled,
    DocumentCommitted,
    DocumentCreated,
    DocumentDelta,
    Event,
    EventBody,
    LimitNotice,
    MessageInjected,
    MessageQueued,
    MessageWithdrawn,
    RunEnded,
    RunError,
    RunMetrics,
    RunStarted,
    StepCompleted,
    StepStarted,
    ThinkingDelta,
    ToolCompleted,
    ToolFailed,
    ToolProgress,
    ToolStarted,
    ViewLive,
    ViewLiveStopped,
    ViewSnapshot,
)
from .registry import ConversationBusyError, RunRegistry, RunTimeout
from .run import Orchestrator, QueuedMessage, Run, RunStatus
from .stream import RunStream
from .transport import parse_last_event_id, sse_response

__all__ = [
    "events",
    "PROTOCOL_VERSION",
    "Event",
    "EventBody",
    "RunRegistry",
    "RunTimeout",
    "ConversationBusyError",
    "Run",
    "RunStatus",
    "QueuedMessage",
    "Orchestrator",
    "RunStream",
    "sse_response",
    "parse_last_event_id",
    # event bodies (re-exported for producers)
    "RunStarted",
    "RunMetrics",
    "ContextWindow",
    "RunEnded",
    "RunError",
    "StepStarted",
    "StepCompleted",
    "ThinkingDelta",
    "AnswerDelta",
    "ToolStarted",
    "ToolProgress",
    "ToolCompleted",
    "ToolFailed",
    "DocumentCreated",
    "DocumentDelta",
    "DocumentCommitted",
    "CitationAdded",
    "ViewLive",
    "ViewLiveStopped",
    "ViewSnapshot",
    "ConversationTitled",
    "ApprovalRequired",
    "MessageQueued",
    "MessageWithdrawn",
    "MessageInjected",
    "LimitNotice",
]
