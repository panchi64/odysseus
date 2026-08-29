"""Model construction — turn an endpoint spec (or a chain) into a Pydantic AI model.

Roles the engine consumes: ``main`` (chat/agent), ``utility`` (cheap background
work), ``embedding`` (recall). Resolution of a *role* to a model is the
**registry's** job (:mod:`services.registry`, the single source of truth — manual
config today, an automatic-setup write path later). This module owns
the layer below it: dispatching one spec to its **provider adapter**
(:mod:`services.providers` — OpenAI-compatible, Anthropic, Google, local) and
wrapping an ordered chain in ``FallbackModel``. Both registry-sourced and
Every endpoint flows through these builders. The OpenAI-wire discovery
and probe helpers live here too — they are what the openai-compatible and local
adapters delegate to.

**The AE-5.3 rule — "don't switch endpoints once answer text has streamed" — is
ours, not the library's.** ``FallbackModel`` only ever falls back while *opening*
a request stream (a dead/erroring endpoint before any output); once a stream is
open and answer text is flowing it propagates errors rather than re-trying a
different endpoint. We complete the guarantee in the orchestrator: a model error
after the first ``answer.delta`` ends the run (``run.answer_started`` is set in
the translation layer) — we never re-drive a turn onto another endpoint once the
user has seen partial output.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel

from core.exceptions import DegradedCapabilityError

ROLES = frozenset({"main", "utility", "embedding"})
# Roles that drive the agent loop must support native tool-calling (AE-8.1).
TOOL_CALLING_ROLES = frozenset({"main", "utility"})


@dataclass(frozen=True)
class EndpointSpec:
    """A resolved, decrypted endpoint — everything needed to build a model."""

    base_url: str
    model: str
    # Which adapter builds the model (`services/providers`). Every pre-provider
    # endpoint is OpenAI-compatible, hence the default.
    provider: str = "openai-compatible"
    # None ⇒ the server doesn't authenticate (a local engine). Never a sentinel.
    api_key: str | None = None
    context_window: int | None = None
    native_tools: bool = True
    vision: bool = False
    thinking: bool = False


def build_model(spec: EndpointSpec) -> Model:
    """Build one Pydantic AI model from an endpoint spec, via its provider adapter."""
    # Deferred import: the adapters type against EndpointSpec, so the registry loads
    # on first build rather than at module import.
    from services.providers import get_provider

    return get_provider(spec.provider).build_model(spec)


def build_chain(specs: Sequence[EndpointSpec]) -> Model:
    """Build a model for an ordered fallback chain.

    One endpoint resolves to a plain model; two or more are wrapped in
    ``FallbackModel`` (tried in order on connection/HTTP failure — pre-answer
    only, per AE-5.3). An empty chain is a degraded capability.
    """
    if not specs:
        raise DegradedCapabilityError("no endpoints in the model chain")
    models = [build_model(spec) for spec in specs]
    if len(models) == 1:
        return models[0]
    return FallbackModel(*models)


async def discover_openai_models(
    base_url: str,
    api_key: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Discover the model ids an OpenAI-wire server advertises.

    Hits the OpenAI-style ``GET {base_url}/models`` — the de-facto standard most
    OpenAI-compatible servers (Ollama, vLLM, LM Studio, …) expose — and dispatches
    the body through per-shape adapters, so servers that instead return a
    ``models`` array (or a bare list) still resolve. Reuses the caller's pooled
    ``client`` when given (one per app, connection-reused), else a transient one.

    Returns the ids de-duplicated and sorted — possibly **empty** when the
    server has a models API that lists nothing. Raises ``DegradedCapabilityError``
    only when the server can't be reached or returns an unrecognized payload, so
    the caller distinguishes "supported but empty" from "no models API".
    """
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # Short connect timeout so an unreachable host fails fast; the read budget is
    # larger for slow-but-alive providers.
    timeout = httpx.Timeout(8.0, connect=3.0)
    http = client or httpx.AsyncClient(follow_redirects=True)
    try:
        response = await http.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DegradedCapabilityError(f"could not list models from {base_url!r}: {exc}") from exc
    finally:
        if client is None:
            await http.aclose()
    ids = _extract_model_ids(payload)
    if ids is None:
        raise DegradedCapabilityError(f"{base_url!r} returned an unrecognized models payload")
    return ids


async def probe_openai_endpoint(
    base_url: str,
    api_key: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Check an OpenAI-wire endpoint's reachability + auth with one lightweight request.

    Unlike :func:`discover_openai_models` — which collapses every failure into
    ``DegradedCapabilityError`` — this lets the **typed** httpx error propagate so the
    caller (the registry's connection test) can tell auth from rate-limit from timeout
    from unreachable. Probes the same ``GET {base_url}/models`` discovery uses. Returns
    ``None`` on a healthy, parseable 2xx; otherwise raises ``httpx.HTTPStatusError``
    (non-2xx), ``httpx.TimeoutException``, ``httpx.ConnectError`` / other
    ``httpx.TransportError``, or ``ValueError`` (a body that isn't JSON).
    """
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    timeout = httpx.Timeout(8.0, connect=3.0)
    http = client or httpx.AsyncClient(follow_redirects=True)
    try:
        response = await http.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        response.json()  # a recognized provider answers JSON; a non-JSON body is bad_response
    finally:
        if client is None:
            await http.aclose()


# The keys OpenAI-wire servers use for a model's context window, in the order we
# trust them. There is no standard — the OpenAI `/v1/models` schema has no such field
# at all — so each server that bothers to report one invented its own name. vLLM says
# `max_model_len`, LM Studio `max_context_length`, llama.cpp-derived servers `n_ctx`,
# and several gateways `context_length`. Reading all of them is what makes discovery
# work across "OpenAI-compatible" servers that agree on nothing but the chat route.
_CONTEXT_KEYS = (
    "context_length",
    "max_context_length",
    "max_model_len",
    "context_window",
    "n_ctx",
)
# LM Studio reports nothing useful on the OpenAI route but exposes its own richer
# listing alongside it. Checked only after the standard route comes back silent.
_LMSTUDIO_NATIVE = "/api/v0/models"


def _context_from_row(row: object) -> int | None:
    """A positive context length from a model listing entry, whichever key it used.

    LM Studio's `loaded_context_length` is preferred over its `max_context_length`
    when present: a model loaded at 32k in a server that *could* do 256k has a real
    ceiling of 32k, and the gauge has to measure the one the next turn will hit."""
    if not isinstance(row, dict):
        return None
    for key in ("loaded_context_length", *_CONTEXT_KEYS):
        value = row.get(key)
        # Guard `bool` explicitly: it is an `int` subclass, and a server answering
        # `"context_length": true` would otherwise yield a one-token window.
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None


def _find_model_row(payload: object, model: str) -> object | None:
    """The listing entry describing ``model``, across the same shapes
    :func:`_extract_model_ids` understands."""
    rows: list[object] = []
    if isinstance(payload, dict):
        for key in ("data", "models"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    elif isinstance(payload, list):
        rows = payload
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = row.get("id") or row.get("name")
        if isinstance(ident, str) and ident.removeprefix("models/") == model:
            return row
    return None


async def discover_openai_context_window(
    base_url: str,
    model: str,
    api_key: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> int | None:
    """The context window an OpenAI-wire server reports for ``model``, or None.

    **Never raises.** A window we can't discover is not an error — it is a fact the
    server didn't state, and every caller's answer to that is the same (fall back to
    whatever the operator configured). Collapsing the failure here keeps that decision
    in one place instead of at each call site.

    Tries the standard listing first, then LM Studio's native listing, which reports a
    window where the OpenAI route reports none. That second request is the reason this
    is worth doing at all for local servers: the OpenAI `/v1/models` schema has no
    context field, so the most common local setup can never answer on that route.
    """
    for url in (base_url.rstrip("/") + "/models", _native_listing_url(base_url)):
        if url is None:
            continue
        row = _find_model_row(await _get_json(url, api_key, client=client), model)
        window = _context_from_row(row)
        if window is not None:
            return window
    return None


def _native_listing_url(base_url: str) -> str | None:
    """LM Studio's own listing, derived from an OpenAI base URL by swapping the
    version segment. Only attempted for a `/v1` base — anything else is a server
    whose native API (if it has one) we know nothing about."""
    trimmed = base_url.rstrip("/")
    if not trimmed.endswith("/v1"):
        return None
    return trimmed[: -len("/v1")] + _LMSTUDIO_NATIVE


async def _get_json(
    url: str, api_key: str | None, *, client: httpx.AsyncClient | None = None
) -> object | None:
    """A best-effort JSON GET for discovery's optional extras — None on any failure.
    Short timeouts: this rides on paths the operator is waiting on, and a window we
    didn't get is survivable where a stall is not."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    http = client or httpx.AsyncClient(follow_redirects=True)
    try:
        response = await http.get(url, headers=headers, timeout=httpx.Timeout(5.0, connect=2.0))
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError, ValueError:
        return None
    finally:
        if client is None:
            await http.aclose()


def _extract_model_ids(payload: object) -> list[str] | None:
    """Pull model identifiers out of whichever shape a provider returned.

    Each adapter recognizes one convention and returns its ids, or ``None`` if the
    payload isn't its shape; the first match wins. ``None`` overall means no shape
    matched (an unrecognized payload); an empty list means a recognized response
    that simply lists no models. Splitting the adapters keeps provider-specific
    quirks (Gemini's ``models/`` name prefix) from mangling other providers' ids.
    """
    for adapter in (_openai_models, _named_models, _bare_list):
        ids = adapter(payload)
        if ids is not None:
            return sorted(dict.fromkeys(ids))
    return None


def _openai_models(payload: object) -> list[str] | None:
    """OpenAI/Anthropic and most OpenAI-compatible servers: ``{"data": [{"id"}]}``."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    return [
        row["id"]
        for row in payload["data"]
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]
    ]


def _named_models(payload: object) -> list[str] | None:
    """Gemini/Cohere/Ollama-native: ``{"models": [{"id" | "name"}]}``. Strips the
    ``models/`` prefix Gemini puts on names — scoped here so it can't touch an
    OpenAI-shaped id that legitimately starts with ``models/``."""
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return None
    ids: list[str] = []
    for row in payload["models"]:
        if not isinstance(row, dict):
            continue
        ident = row.get("id") or row.get("name")
        if isinstance(ident, str):
            stripped = ident.removeprefix("models/")
            if stripped:
                ids.append(stripped)
    return ids


def _bare_list(payload: object) -> list[str] | None:
    """Some servers return a bare list — of id strings, or of ``{"id" | "name"}``."""
    if not isinstance(payload, list):
        return None
    ids: list[str] = []
    for row in payload:
        if isinstance(row, str):
            ident: str | None = row
        elif isinstance(row, dict):
            ident = row.get("id") or row.get("name")
        else:
            ident = None
        if isinstance(ident, str) and ident:
            ids.append(ident)
    return ids
