"""The window onto the agent's browser — a live frame stream, and who has one.

Two surfaces with two different credentials, which is why they sit under two prefixes:

``/browser/stream/{token}`` is the frame stream (and its status). The unguessable
per-session token **is** the credential, so the subtree is exempt from the cookie gate the
same way ``/previews`` is — it carries pixels of pages the agent opened, never operator
data, and a WebSocket cannot send an ``Authorization`` header anyway.

``/browser/session/{conversation_id}`` answers "does this thread have a live browser, and
what is its token" for a panel that just loaded. That *is* operator data, so it stays
behind the gate under the chat scope. This is what makes the panel survive a page reload:
the run event that announced the session is long gone by then, and the manager — not the
transcript — is the source of truth for what is live right now.

``AuthMiddleware`` returns early for non-HTTP scopes, so the socket is not covered by it,
and CORS does not apply to WebSockets either. The handshake therefore checks ``Origin``
itself against the configured list, so a page the operator merely *visits* cannot open a
socket to a token it somehow learned.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from core.config import get_settings
from routes import deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/browser", tags=["browser"])

#: Close codes the panel reads. 4404 is "no such token" (a stale link, or a session from
#: before a restart); 4410 is "there was one and it is gone" — the distinction is what
#: lets the panel say "the browser was closed" instead of failing silently.
_CLOSE_UNKNOWN = 4404
_CLOSE_GONE = 4410
_CLOSE_UNAVAILABLE = 1011


class BrowserSessionInfo(BaseModel):
    """The live browser for a conversation, or ``active=False`` when there is none."""

    active: bool
    url: str | None = None  # "/browser/stream/{token}", ready to open as a socket
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
    return BrowserSessionInfo(
        active=True,
        url=f"/browser/stream/{live.token}",
        page_url=live.page_url or None,
    )


@router.get("/stream/{token}/status")
async def stream_status(request: Request, token: str) -> dict[str, str]:
    """``live``, ``stopped``, or ``unknown`` — for a panel whose socket dropped and needs
    to tell "the browser was closed" from "the backend restarted"."""
    sessions = deps.browser_sessions(request)
    if sessions is None:
        raise HTTPException(status_code=503, detail="browser control is not available")
    return {"status": sessions.status(token)}


@router.websocket("/stream/{token}")
async def stream(websocket: WebSocket, token: str) -> None:
    """Stream the live page to one watcher until it disconnects or the session ends."""
    if not _origin_allowed(websocket):
        await websocket.close(code=_CLOSE_UNAVAILABLE)
        return
    sessions = deps.browser_sessions(websocket)
    live = sessions.resolve(token) if sessions is not None else None
    if live is None:
        status = sessions.status(token) if sessions is not None else "unknown"
        await websocket.close(code=_CLOSE_GONE if status == "stopped" else _CLOSE_UNKNOWN)
        return

    screencast = live.screencast
    queue = screencast.subscribe()
    await websocket.accept()
    try:
        # Streaming only runs while somebody is watching, so the first watcher starts it.
        # Idempotent, so a second panel on the same session just joins the fan-out.
        await screencast.start()
        while True:
            frame = await queue.get()
            if frame is None:  # the session was torn down under us
                await websocket.send_json({"t": "end", "reason": "stopped"})
                break
            # Every frame counts as watching: an operator following a long page load must
            # not have the browser reaped out from under them mid-stream.
            live.touch()
            await websocket.send_json(frame.envelope())
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:  # noqa: BLE001 — one bad socket must not disturb the session
        logger.debug("browser: frame stream failed", exc_info=True)
    finally:
        screencast.unsubscribe(queue)
        if screencast.watchers == 0:
            # Nobody left watching: stop encoding frames nobody reads. The session itself
            # stays open — the agent is still using it.
            await screencast.stop()
        with_close = websocket.client_state.name == "CONNECTED"
        if with_close:
            await websocket.close()


def _origin_allowed(websocket: WebSocket) -> bool:
    """Whether the handshake's ``Origin`` is one the app serves its frontend to.

    A socket with no ``Origin`` at all is a non-browser client (a test, a script), which
    the token already authenticates; the header exists to stop a *browser* on some other
    page from opening one.
    """
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return origin in get_settings().cors_origins
