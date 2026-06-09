"""Model resolution — turn a named role into a Pydantic AI model.

Roles the engine consumes: ``main`` (chat/agent), ``utility`` (cheap background
work), ``embedding`` (recall). Each binds to an OpenAI-compatible endpoint (or,
later, an ordered fallback chain wrapped in ``FallbackModel``).

This is the **minimal seam**: a single endpoint from config. The full role→
endpoint registry (in encrypted settings, with per-role fallback chains) swaps in
here later without touching callers — the engine only ever asks for a role.
"""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from core.config import get_settings
from core.exceptions import DegradedCapabilityError

ROLES = frozenset({"main", "utility", "embedding"})


def resolve_model(role: str = "main") -> Model:
    """Build the model bound to ``role``. Raises if the role is unconfigured."""
    if role not in ROLES:
        raise ValueError(f"unknown model role: {role!r}")

    settings = get_settings()
    name = settings.llm_model
    if role == "utility":
        name = settings.utility_model or settings.llm_model
    if not name:
        raise DegradedCapabilityError(f"no model configured for role {role!r}")

    provider = OpenAIProvider(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return OpenAIChatModel(name, provider=provider)
