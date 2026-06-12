"""Model construction — turn an endpoint spec (or a chain) into a Pydantic AI model.

Roles the engine consumes: ``main`` (chat/agent), ``utility`` (cheap background
work), ``embedding`` (recall). Resolution of a *role* to a model is the
**registry's** job (:mod:`services.registry`, the single source of truth — manual
config today, the automatic-setup/Cookbook write path later). This module owns
the layer below it: building one OpenAI-compatible model from a spec, and
wrapping an ordered chain in ``FallbackModel``. Both registry-sourced and
Cookbook-sourced endpoints flow through these builders.

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
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.exceptions import DegradedCapabilityError

ROLES = frozenset({"main", "utility", "embedding"})
# Roles that drive the agent loop must support native tool-calling (AE-8.1).
TOOL_CALLING_ROLES = frozenset({"main", "utility"})
# Placeholder key for local servers that ignore auth — never sent as a header.
NO_API_KEY = "not-needed"


@dataclass(frozen=True)
class EndpointSpec:
    """A resolved, decrypted endpoint — everything needed to build a model."""

    base_url: str
    model: str
    api_key: str = NO_API_KEY  # local servers ignore it
    context_window: int | None = None
    native_tools: bool = True
    vision: bool = False
    thinking: bool = False


def build_model(spec: EndpointSpec) -> Model:
    """Build one Pydantic AI model from an endpoint spec."""
    provider = OpenAIProvider(base_url=spec.base_url, api_key=spec.api_key or NO_API_KEY)
    return OpenAIChatModel(spec.model, provider=provider)


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


async def discover_models(
    base_url: str,
    api_key: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Discover the model ids a provider advertises.

    Hits the OpenAI-style ``GET {base_url}/models`` — the de-facto standard most
    OpenAI-compatible servers (Ollama, vLLM, LM Studio, …) expose — and dispatches
    the body through per-provider adapters, so providers that instead return a
    ``models`` array (or a bare list) still resolve. Reuses the caller's pooled
    ``client`` when given (one per app, connection-reused), else a transient one.

    Returns the ids de-duplicated and sorted — possibly **empty** when the
    provider has a models API that lists nothing. Raises ``DegradedCapabilityError``
    only when the provider can't be reached or returns an unrecognized payload, so
    the caller distinguishes "supported but empty" from "no models API".
    """
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key and api_key != NO_API_KEY else {}
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
        if isinstance(ident, str) and ident:
            ids.append(ident.removeprefix("models/"))
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
