"""Operator authentication and the global auth gate.

Single operator: the password both verifies login and derives the encryption key
(through the vault). :class:`AuthManager` tracks issued session tokens; they live
in memory and are cleared on lock or restart — which is also when the vault
re-locks, so a valid token always implies an unlocked vault.

:class:`AuthMiddleware` is a **pure ASGI** middleware (not BaseHTTPMiddleware) so
it never buffers responses — important for the SSE event stream. It enforces the
gate before any feature is reached and passes streaming responses through
untouched.
"""

from __future__ import annotations

import json
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_COOKIE = "odysseus_session"

# Reachable without authentication: status, first-run setup, login/logout/lock,
# liveness, and the API docs.
_PUBLIC_PREFIXES = ("/auth", "/setup", "/health", "/docs", "/redoc", "/openapi.json")


class AuthManager:
    def __init__(self) -> None:
        self._tokens: set[str] = set()

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        return token

    def verify(self, token: str | None) -> bool:
        return token is not None and token in self._tokens

    def revoke(self, token: str) -> None:
        self._tokens.discard(token)

    def revoke_all(self) -> None:
        self._tokens.clear()


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _PUBLIC_PREFIXES)


def token_from_headers(authorization: str | None, cookie_token: str | None) -> str | None:
    """Resolve the session token from a bearer header or the session cookie."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return cookie_token


def _token_from_scope(scope: Scope) -> str | None:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    cookie_token = None
    for part in headers.get("cookie", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE:
            cookie_token = value
            break
    return token_from_headers(headers.get("authorization"), cookie_token)


async def _reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or _is_public(scope["path"]):
            return await self.app(scope, receive, send)

        state = scope["app"].state
        if state.settings.auth_enabled and not state.auth_manager.verify(_token_from_scope(scope)):
            return await _reject(send, 401, "authentication required")
        if not state.vault.is_unlocked:
            return await _reject(send, 423, "the vault is locked")
        await self.app(scope, receive, send)
