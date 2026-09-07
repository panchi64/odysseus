"""The agent's browser, from the app's side: does this thread have one, and open it.

The browser itself is a window on the operator's own machine, so there is nothing here
that carries a page — no stream, no frames, no pixels. What is left is the two questions
the chat UI actually asks about it.

``GET /browser/session/{conversation_id}`` answers "is there a live browser for this
thread right now". Read-only on purpose: it never touches the session, so a UI that polls
it cannot keep an otherwise-idle window alive. The manager, not the transcript, is the
source of truth — a page reload has no run events to replay.

``POST`` on the same path is the operator opening one themselves, before the agent has
touched anything: it attaches a session and brings the window to the front. Both live
under the chat scope, because whether a conversation has a browser is operator data.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes import deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/browser", tags=["browser"])

#: Said to the operator when no window could be opened — Chromium missing, the SSRF proxy
#: refusing to start, or the feature not assembled at all. One sentence, because the UI
#: shows it verbatim in a toast.
_UNAVAILABLE = "The browser could not be opened on this machine."


class BrowserSessionInfo(BaseModel):
    """The live browser for a conversation, or ``active=False`` when there is none."""

    active: bool
    page_url: str | None = None


@router.get("/session/{conversation_id}", response_model=BrowserSessionInfo)
async def session_info(request: Request, conversation_id: str) -> BrowserSessionInfo:
    """Whether this conversation has a live browser right now.

    Read-only: it deliberately does **not** touch the session, so polling this never keeps
    an otherwise-idle browser alive.
    """
    sessions = deps.browser_sessions(request)
    live = sessions.existing(conversation_id) if sessions is not None else None
    if live is None:
        return BrowserSessionInfo(active=False)
    return BrowserSessionInfo(active=True, page_url=live.page_url or None)


@router.post("/session/{conversation_id}", response_model=BrowserSessionInfo)
async def open_session(request: Request, conversation_id: str) -> BrowserSessionInfo:
    """Open this conversation's browser and put the window in front of the operator.

    Idempotent: a thread that already has one gets that same session, focused. A failure
    is a 503 rather than an empty success — the operator asked for a window, and one not
    appearing has to say why.
    """
    sessions = deps.browser_sessions(request)
    live = await sessions.acquire(conversation_id, focus=True) if sessions is not None else None
    if live is None:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    return BrowserSessionInfo(active=True, page_url=live.page_url or None)
