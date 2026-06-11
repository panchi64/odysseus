"""Live-preview reverse proxy — the token-gated window into a sandbox server.

The agent runs a dev server in its sandbox (``start_preview``); this forwards the
operator's browser to it. The address carries an unguessable per-preview **token**
(``/previews/{token}/…``) which *is* the credential: that lets the frontend host
the preview in a sandboxed iframe **without** ``allow-same-origin`` (an opaque
origin that can't send the operator's auth cookie), and the token rides every
relative subresource load automatically. So this subtree is exempt from the cookie
gate (see ``core/auth``) — it only ever proxies to a loopback preview container,
never to operator data.

Both legs are byte-transparent: HTTP via a streaming ``httpx`` proxy, WebSocket via
a ``websockets`` bridge (so Vite/HMR live-reload works). The operator's credentials
are never forwarded inward, and the preview can't set cookies on the API origin.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from services.sandbox import PreviewHandle

router = APIRouter(prefix="/previews", tags=["previews"])

_HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

# Connection-scoped headers a proxy must not forward (RFC 7230 §6.1).
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
# Inbound: never leak the operator's credentials to the model's server.
_STRIP_REQUEST = _HOP_BY_HOP | {"cookie", "authorization", "host"}
# Outbound: the preview must not plant cookies on the API origin, and a server
# default of `x-frame-options: deny` must not block the iframe this feature renders
# into (the sandboxed iframe is the isolation boundary, not a framing header).
_STRIP_RESPONSE = _HOP_BY_HOP | {"set-cookie", "x-frame-options"}


def _preview(request_or_ws: Request | WebSocket, token: str) -> PreviewHandle | None:
    manager = request_or_ws.app.state.sandbox
    return manager.resolve_preview(token) if manager is not None else None


def _rewrite_location(value: str, prefix: str) -> str:
    """Pull a redirect that points at the upstream (or site root) back under the
    token prefix, so the browser stays inside the preview."""
    for scheme in ("http://", "https://"):
        if value.startswith(scheme):
            rest = value[len(scheme) :]
            slash = rest.find("/")
            return prefix + (rest[slash:] if slash != -1 else "/")
    if value.startswith("/"):
        return prefix + value
    return value


def _response_headers(headers: httpx.Headers, prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in _STRIP_RESPONSE:
            continue
        out[key] = _rewrite_location(value, prefix) if lower == "location" else value
    out["x-content-type-options"] = "nosniff"
    return out


@router.api_route("/{token}/{path:path}", methods=_HTTP_METHODS)
async def proxy_http(token: str, path: str, request: Request) -> Response:
    handle = _preview(request, token)
    if handle is None:
        raise HTTPException(status_code=404, detail="preview not found")

    prefix = f"/previews/{token}"
    client: httpx.AsyncClient = request.app.state.preview_client
    url = httpx.URL(
        scheme="http",
        host="127.0.0.1",
        port=handle.host_port,
        path="/" + path,
        query=request.url.query.encode("ascii"),
    )
    headers = [
        (k, v)
        for k, v in request.headers.raw
        if k.decode("latin-1").lower() not in _STRIP_REQUEST
    ]
    headers.append((b"x-forwarded-prefix", prefix.encode("ascii")))
    upstream = client.build_request(
        request.method, url, headers=headers, content=request.stream()
    )
    try:
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"preview server error: {exc}") from exc

    async def _body():
        # The finally returns the upstream connection to the pool even when the
        # operator's browser disconnects mid-stream — Starlette aclose()s this
        # generator on disconnect, whereas a background task only runs on a clean
        # finish, so without it a navigated-away stream would leak a connection.
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        _body(),
        status_code=response.status_code,
        headers=_response_headers(response.headers, prefix),
    )


@router.websocket("/{token}/{path:path}")
async def proxy_ws(websocket: WebSocket, token: str, path: str) -> None:
    handle = _preview(websocket, token)
    if handle is None:
        await websocket.close(code=4404)
        return

    query = websocket.url.query
    upstream_url = f"ws://127.0.0.1:{handle.host_port}/{path}" + (f"?{query}" if query else "")
    subprotocols = websocket.scope.get("subprotocols") or None
    try:
        upstream = await ws_connect(upstream_url, subprotocols=subprotocols, open_timeout=10)
    except (OSError, ConnectionClosed, TimeoutError, InvalidHandshake):
        await websocket.close(code=1011)
        return

    await websocket.accept(subprotocol=upstream.subprotocol)
    try:
        await _bridge(websocket, upstream)
    finally:
        await upstream.close()


async def _bridge(client_ws: WebSocket, upstream) -> None:
    """Pump frames both ways until either side closes."""

    async def client_to_upstream() -> None:
        try:
            while True:
                message = await client_ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if (text := message.get("text")) is not None:
                    await upstream.send(text)
                elif (data := message.get("bytes")) is not None:
                    await upstream.send(data)
        except (WebSocketDisconnect, ConnectionClosed):
            return

    async def upstream_to_client() -> None:
        try:
            async for message in upstream:
                if isinstance(message, str):
                    await client_ws.send_text(message)
                else:
                    await client_ws.send_bytes(message)
        except (WebSocketDisconnect, ConnectionClosed):
            return

    tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    # Await the cancelled side so its teardown finishes and no exception is orphaned.
    await asyncio.gather(*pending, return_exceptions=True)
