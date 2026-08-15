"""The provider contract — what one model-API family knows how to do.

A *provider* is the adapter between an operator's endpoint row and a concrete
Pydantic AI model class: it builds the model, lists/probes the remote catalog,
declares whether a key is required, ships the preset the frontend prefills a new
endpoint from, and knows how to turn reasoning off for its own models. Everything
above (the registry's role resolution, fallback chains, encryption) is
provider-agnostic; everything provider-specific lives in one adapter module.

Adapters register by presence: a module in this package exposing ``PROVIDER``
is discovered by the pkgutil walk in ``__init__`` — the same contract as the
feature manifests. Adding a lab is one file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.settings import ModelSettings

    from services.llm import EndpointSpec
    from services.reasoning import ModelDescriptor


@dataclass(frozen=True)
class ProviderPreset:
    """What the frontend prefills when the operator picks this provider — served by
    ``GET /models/providers`` so the client never hardcodes a lab's details."""

    # Prefilled base URL; None ⇒ the operator must supply one (a self-hosted server).
    default_base_url: str | None = None
    # A hint for the key field (e.g. "sk-ant-…"); None ⇒ no key expected.
    key_hint: str | None = None
    # Where the operator gets a key / reads the docs.
    docs_url: str | None = None
    # Capability defaults for a fresh endpoint of this kind.
    native_tools: bool = True
    vision: bool = False


@runtime_checkable
class Provider(Protocol):
    """One model-API family. Stateless; safe to share across requests."""

    # Stable identifier persisted on ModelEndpoint.provider.
    id: str
    display_name: str
    # Whether an endpoint of this kind must carry an API key — validated at save.
    requires_key: bool
    preset: ProviderPreset

    def build_model(self, spec: EndpointSpec) -> Model:
        """A concrete Pydantic AI model from a resolved, decrypted spec."""
        ...

    async def discover(
        self, base_url: str, api_key: str | None, *, client: object = None
    ) -> list[str]:
        """The model ids the remote advertises — possibly empty. Raises
        ``DegradedCapabilityError`` when unreachable or unrecognized (the caller
        distinguishes "supported but empty" from "no models API"). ``client`` is an
        optional pooled ``httpx.AsyncClient`` to reuse; None ⇒ a transient one."""
        ...

    async def probe(
        self, base_url: str, api_key: str | None, *, client: object = None
    ) -> None:
        """One lightweight reachability+auth check. Unlike ``discover`` this lets the
        **typed** httpx error propagate so the registry's connection test can tell
        auth from rate-limit from timeout from unreachable."""
        ...

    def reasoning_off(self, descriptor: ModelDescriptor) -> ModelSettings:
        """The settings that stop this provider's model from spending tokens on
        thinking for background work — ``{}`` when there is nothing to turn off."""
        ...
