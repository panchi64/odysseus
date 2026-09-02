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

    async def probe(self, base_url: str, api_key: str | None, *, client: object = None) -> None:
        """One lightweight reachability+auth check. Unlike ``discover`` this lets the
        **typed** httpx error propagate so the registry's connection test can tell
        auth from rate-limit from timeout from unreachable."""
        ...

    async def context_window(
        self, base_url: str, api_key: str | None, model: str, *, client: object = None
    ) -> int | None:
        """The context window ``model`` reports, or None when this provider has no way
        to say — which is the common case, not the exception.

        **Never raises.** A window is a fact the provider either states or doesn't; a
        failure to reach it is indistinguishable, to every caller, from it not being
        there, and both answers are "fall back to what the operator configured".

        Per *model*, not per endpoint, because that is the grain of the truth: one
        OpenAI-compatible server happily serves a 256k model and a 32k model at the
        same base URL, and a window cached against the endpoint would be wrong for one
        of them."""
        ...

    def reasoning_off(self, descriptor: ModelDescriptor) -> ModelSettings:
        """The settings that stop this provider's model from spending tokens on
        thinking for background work — ``{}`` when there is nothing to turn off."""
        ...

    def model_settings(self, descriptor: ModelDescriptor) -> ModelSettings:
        """Standing settings every request to this provider's models carries.

        Distinct from :meth:`reasoning_off`, which one *caller* asks for when it wants a
        cheap background pass. These are the model's own defaults — a lab-wide request
        shape that is true whoever is calling — so the adapter hands them to the model
        **at construction** (``Model(settings=…)``) rather than to any one call site.
        That placement is the whole point: a setting applied there survives a fallback
        chain, a parked turn resumed hours later, and every path that builds its own
        per-request settings, none of which have to know the lab exists. Pydantic AI
        merges a request's settings *over* the model's, so a caller can still override
        one deliberately.

        Defaulted rather than required: most families need nothing here, and an adapter
        that says nothing means ``{}``.
        """
        return {}
