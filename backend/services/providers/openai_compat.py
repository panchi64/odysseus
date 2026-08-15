"""The universal adapter — any server speaking the OpenAI wire protocol.

The default for every endpoint (and the shape every local engine — vLLM, LM Studio,
llama.cpp, MLX servers — speaks). Reasoning-off falls back to the model-name
heuristics in ``services/reasoning``, because a generic gateway can front any model
family.
"""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from services import llm, reasoning
from services.llm import EndpointSpec
from services.providers.base import ProviderPreset


class OpenAICompatProvider:
    id = "openai-compatible"
    display_name = "OpenAI-compatible"
    # A key is the server's choice, not the protocol's — a local engine ignores auth,
    # a hosted gateway demands it. The operator decides; nothing is validated away.
    requires_key = False
    preset = ProviderPreset(
        default_base_url=None,
        key_hint="sk-… (only if the server requires one)",
        docs_url=None,
    )

    def build_model(self, spec: EndpointSpec) -> Model:
        # The OpenAI client refuses a None key outright, so a keyless local server
        # gets a placeholder — an auth header the server ignores. The placeholder is
        # an adapter-boundary quirk, never a value other layers see or store.
        provider = OpenAIProvider(base_url=spec.base_url, api_key=spec.api_key or "unused")
        return OpenAIChatModel(spec.model, provider=provider)

    # Reached through the module (not from-imports) so a test that monkeypatches
    # `services.llm` still intercepts the adapter's calls.
    async def discover(
        self, base_url: str, api_key: str | None, *, client=None
    ) -> list[str]:
        return await llm.discover_openai_models(base_url, api_key, client=client)

    async def probe(self, base_url: str, api_key: str | None, *, client=None) -> None:
        await llm.probe_openai_endpoint(base_url, api_key, client=client)

    def reasoning_off(self, descriptor: reasoning.ModelDescriptor) -> ModelSettings:
        return reasoning.disable_thinking(descriptor)


PROVIDER = OpenAICompatProvider()
