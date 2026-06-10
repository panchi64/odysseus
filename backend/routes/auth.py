"""Auth surface: status, first-run setup, login, logout, lock.

Login and setup unlock the vault (deriving the encryption key from the password)
and issue a session token — returned in the body (for bearer clients) and set as
an httpOnly cookie (for the browser, including the SSE stream).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from core.auth import SESSION_COOKIE, token_from_headers
from routes import deps

router = APIRouter(tags=["auth"])

_MIN_PASSWORD_LEN = 8


class PasswordBody(BaseModel):
    password: str


class AuthStatus(BaseModel):
    initialized: bool
    unlocked: bool
    auth_enabled: bool


class TokenResponse(BaseModel):
    token: str


def _issue_session(request: Request, response: Response) -> TokenResponse:
    token = deps.auth_manager(request).issue()
    # secure=False: the app serves plain HTTP; put TLS in front for remote use.
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=False)
    return TokenResponse(token=token)


@router.get("/auth/status", response_model=AuthStatus)
async def auth_status(request: Request) -> AuthStatus:
    vault = deps.vault(request)
    return AuthStatus(
        initialized=vault.is_initialized,
        unlocked=vault.is_unlocked,
        auth_enabled=request.app.state.settings.auth_enabled,
    )


@router.post("/setup", response_model=TokenResponse)
async def setup(body: PasswordBody, request: Request, response: Response) -> TokenResponse:
    """First run only: choose the operator password (which derives the key)."""
    vault = deps.vault(request)
    if vault.is_initialized:
        raise HTTPException(status_code=409, detail="already set up")
    if len(body.password) < _MIN_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    await vault.setup(body.password)
    return _issue_session(request, response)


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: PasswordBody, request: Request, response: Response) -> TokenResponse:
    vault = deps.vault(request)
    if not vault.is_initialized:
        raise HTTPException(status_code=409, detail="not set up yet")
    if not await vault.unlock(body.password):
        raise HTTPException(status_code=401, detail="invalid password")
    return _issue_session(request, response)


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    token = token_from_headers(
        request.headers.get("authorization"), request.cookies.get(SESSION_COOKIE)
    )
    if token:
        deps.auth_manager(request).revoke(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged out"}


@router.post("/auth/lock")
async def lock(request: Request) -> dict[str, str]:
    """Wipe the key from memory and revoke all sessions; re-unlock requires login."""
    deps.vault(request).lock()
    deps.auth_manager(request).revoke_all()
    return {"status": "locked"}
