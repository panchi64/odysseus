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

from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.exceptions import DegradedCapabilityError

ROLES = frozenset({"main", "utility", "embedding"})
# Roles that drive the agent loop must support native tool-calling (AE-8.1).
TOOL_CALLING_ROLES = frozenset({"main", "utility"})


@dataclass(frozen=True)
class EndpointSpec:
    """A resolved, decrypted endpoint — everything needed to build a model."""

    base_url: str
    model: str
    api_key: str = "not-needed"  # local servers ignore it
    context_window: int | None = None
    native_tools: bool = True
    vision: bool = False
    thinking: bool = False


def build_model(spec: EndpointSpec) -> Model:
    """Build one Pydantic AI model from an endpoint spec."""
    provider = OpenAIProvider(base_url=spec.base_url, api_key=spec.api_key or "not-needed")
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
