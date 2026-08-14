"""Operator authentication and the global auth gate.

Single operator: the password both verifies login and derives the encryption key
(through the vault). :class:`AuthManager` tracks issued session tokens; they live
in memory and are cleared on lock or restart — which is also when the vault
re-locks, so a valid token always implies an unlocked vault.

Alongside that session there is a second, *programmatic* way in: a scoped API token
(`AUTH-4`), issued to a client and presented as a bearer credential. The two are told apart
by the token's own shape (``odyt_``), and they differ in reach — a session is the operator
and may do anything, while a token may only touch the surfaces its scopes claim
(``core.api_scopes``, deny-by-default). Both are throttled through one shared attempt
limiter (`AUTH-1`), keyed per client, so guessing either credential is rate-bound.

:class:`AuthMiddleware` is a **pure ASGI** middleware (not BaseHTTPMiddleware) so
it never buffers responses — important for the SSE event stream. It enforces the
gate before any feature is reached and passes streaming responses through
untouched.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from starlette.types import ASGIApp, Receive, Scope, Send

from core.api_scopes import scope_for_path
from core.exceptions import RateLimitedError
from core.ratelimit import RateLimiter

SESSION_COOKIE = "odysseus_session"

# Marks a credential as an inbound API token rather than an operator session token, so the
# gate can route it without a database lookup. The minted form is `odyt_<prefix>_<secret>`.
TOKEN_SCHEME = "odyt_"

# Password guesses and token guesses are the same attack, so they share one limiter under
# separate key namespaces. Generous enough that a human never meets it and a script does.
_AUTH_ATTEMPT_RATE_PER_MINUTE = 12.0
_AUTH_ATTEMPT_BURST = 10

# Reachable without authentication: status probe, first-run setup, login, and
# liveness. Everything else — including the *state-changing* /auth/lock and
# /auth/logout — stays behind the gate, so an unauthenticated caller can't lock
# the vault or revoke sessions.
_PUBLIC_PATHS = frozenset({"/auth/status", "/auth/login", "/setup", "/openapi.json"})
# Prefixes whose sub-paths are also public (liveness probes, the docs UIs).
# `/previews` is a token-gated subtree: the unguessable token in the path is the
# credential (so a sandboxed, opaque-origin iframe can load assets without the
# operator's cookie), and the route only ever proxies to a loopback preview
# container — never to operator data.
# `/tasks/hooks` is the same pattern for the task scheduler's inbound webhook
# trigger (`POST /tasks/hooks/{token}`): the per-task unguessable token in the path
# is the credential, so an external caller can fire a task without the operator's
# session. Every other `/tasks` route stays behind the gate.
_PUBLIC_PREFIXES = ("/health", "/docs", "/redoc", "/previews", "/tasks/hooks")


@dataclass(frozen=True)
class TokenIdentity:
    """Who a verified API token is, and how far it reaches."""

    token_id: str
    owner_id: str
    scopes: tuple[str, ...]


class ApiTokenAuthenticator(Protocol):
    """What the gate needs from the token store — the whole of the dependency."""

    def cached(self, presented: str) -> TokenIdentity | None: ...

    async def authenticate(self, presented: str) -> TokenIdentity | None: ...

    async def touch(self, token_id: str) -> None: ...


# `core` must not import `services`, so the token store registers itself here instead
# (`services/api_token_store.py`, pulled in when the app assembles its routers) and the gate
# builds it on first use from the engine on `app.state`. Until then there is no second
# authentication method and only the operator session is accepted.
_store_factory: Callable[[Any], ApiTokenAuthenticator] | None = None


def register_api_token_store(factory: Callable[[Any], ApiTokenAuthenticator]) -> None:
    global _store_factory
    _store_factory = factory


def api_token_store(state: Any) -> ApiTokenAuthenticator | None:
    """The shared token store, built on first use. ``None`` when none is registered."""
    store = getattr(state, "api_tokens", None)
    if store is None and _store_factory is not None:
        # No await between the read and the write, so concurrent first requests on the
        # event loop can't each build one.
        store = _store_factory(state.db_engine)
        state.api_tokens = store
    return store


def auth_attempt_limiter(state: Any) -> RateLimiter:
    """The shared login/token attempt throttle, built on first use."""
    limiter = getattr(state, "auth_attempt_limiter", None)
    if limiter is None:
        limiter = RateLimiter(
            rate_per_second=_AUTH_ATTEMPT_RATE_PER_MINUTE / 60.0,
            burst=_AUTH_ATTEMPT_BURST,
        )
        state.auth_attempt_limiter = limiter
    return limiter


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
    if path in _PUBLIC_PATHS:
        return True
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


def client_key(client: tuple[str, int] | None) -> str:
    """The rate-limit key for a caller. Brute force varies the credential, not the
    source, so the source is what has to be throttled."""
    return client[0] if client else "unknown"


async def _reject(
    send: Send, status: int, detail: str, headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *(headers or [])],
        }
    )
    await send({"type": "http.response.body", "body": body})


# What a failed API-token authentication should become on the wire.
_Rejection = tuple[int, str, list[tuple[bytes, bytes]]]
_UNAUTHENTICATED: _Rejection = (401, "authentication required", [])


async def _authenticate_api_token(
    state: Any, scope: Scope, presented: str | None
) -> _Rejection | None:
    """Try the presented credential as a scoped API token. ``None`` = authenticated.

    Order matters: the in-memory cache is consulted before the limiter so a working client
    is never throttled, while a guess — which can't be cached — always is, and only then
    pays for the Argon2id comparison."""
    if presented is None or not presented.startswith(TOKEN_SCHEME):
        return _UNAUTHENTICATED
    store = api_token_store(state)
    if store is None:
        return _UNAUTHENTICATED

    identity = store.cached(presented)
    if identity is None:
        try:
            auth_attempt_limiter(state).check(f"token:{client_key(scope.get('client'))}")
        except RateLimitedError as exc:
            retry_after = str(max(1, int(exc.retry_after_s))).encode()
            return (429, str(exc), [(b"retry-after", retry_after)])
        identity = await store.authenticate(presented)
        if identity is None:
            return _UNAUTHENTICATED

    required = scope_for_path(scope["path"])
    if required is None or required not in identity.scopes:
        # Deny-by-default: an unclaimed path (`/tokens`, `/vault`, `/shell`) is out of
        # reach for every token, whatever it carries.
        return (403, "this token's scopes do not cover this endpoint", [])

    await store.touch(identity.token_id)
    return None


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or _is_public(scope["path"]):
            return await self.app(scope, receive, send)

        state = scope["app"].state
        if state.settings.auth_enabled:
            presented = _token_from_scope(scope)
            # The operator session comes first: an in-memory set membership test, so the
            # browser's every request stays free of the token path entirely.
            if not state.auth_manager.verify(presented):
                rejection = await _authenticate_api_token(state, scope, presented)
                if rejection is not None:
                    return await _reject(send, *rejection)
        if not state.vault.is_unlocked:
            return await _reject(send, 423, "the vault is locked")
        await self.app(scope, receive, send)
