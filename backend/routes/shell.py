"""The Operator Shell surface (`SHELL-1..3`): a host PTY streamed to the browser.

`POST /shell/host-mode` requires a fresh password check (rate-limited like
uploads) and mints a single-use, TTL-bounded token; `WS /shell/ws` spends that
token as part of a first-message auth handshake (the WebSocket upgrade bypasses
the global ASGI auth gate entirely, so the socket authenticates itself — see
`services/host_shell.py`). Agent-unreachable by construction: no tool in
`tools/`/`agent/`/`research/` references this module (`tests/test_shell_guard.py`
asserts it).

Wire casing here is snake_case — a new surface, not one of the camelCase
exceptions (`documents`/`uploads`/`gallery`/`corpus`).
"""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel

from core.exceptions import RateLimitedError
from routes import deps

router = APIRouter(prefix="/shell", tags=["shell"])


class HostModeRequest(BaseModel):
    password: str


class HostModeResponse(BaseModel):
    token: str
    expires_in_s: float


@router.post("/host-mode", response_model=HostModeResponse)
async def request_host_mode(body: HostModeRequest, request: Request) -> HostModeResponse:
    vault = deps.vault(request)
    if not vault.is_unlocked:
        raise HTTPException(status_code=423, detail="the vault is locked")
    try:
        deps.shell_auth_rate_limiter(request).check("host-mode")
    except RateLimitedError as exc:
        retry_after = exc.retry_after_s if math.isfinite(exc.retry_after_s) else 60.0
        raise HTTPException(
            status_code=429,
            detail="too many attempts",
            headers={"Retry-After": str(int(retry_after) + 1)},
        ) from None
    if not vault.verify_password(body.password):
        raise HTTPException(status_code=401, detail="invalid password")
    token, ttl = deps.shell(request).mint_host_token()
    return HostModeResponse(token=token, expires_in_s=ttl)


@router.websocket("/ws")
async def shell_ws(websocket: WebSocket) -> None:
    # `deps.py` accessors take a `Request`, not a `WebSocket` — reach `app.state`
    # directly here, mirroring `routes/previews.py`'s websocket handler.
    await websocket.app.state.shell.open_session(websocket)
