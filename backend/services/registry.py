"""The model registry — resolve a named role to a model, and manage endpoints.

The single source of truth for model resolution: it owns the operator's endpoint
catalog and the role→chain bindings, and turns a role into a Pydantic AI model at
run start (there is no ``.env`` model seam):

- ``main`` is **overridable per conversation** — the chat model picker passes a
  provider (endpoint id) and a model on it; every other role is a global binding.
- ``utility`` and ``embedding`` resolve their own bindings only; an unbound role
  is a degraded capability (the chat layer reuses ``main`` when ``utility`` is
  unset, so verification works without separate setup).

The API key is the only encrypted field: it is sealed with the vault on write
and opened on resolve. Resolution validates that tool-driving roles
(``main``/``utility``) only use native-tool-calling endpoints (AE-8.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from sqlalchemy import Engine
from sqlmodel import Session, select

from core.db import in_session
from core.exceptions import DegradedCapabilityError, NotFoundError
from core.vault import Vault
from models.registry import ModelEndpoint, ModelRole
from services import embeddings, llm, reasoning


@dataclass(frozen=True)
class ResolvedModel:
    """A resolved role: the model to run, plus the settings that disable its
    reasoning (empty when the model isn't a recognized thinking model). Background
    callers that want a fast, no-reasoning pass (titling) read ``reasoning_off``.
    ``context_window`` is the primary endpoint's window (None when undeclared) —
    the chat layer forwards it so the run can report context fullness."""

    model: Model
    reasoning_off: ModelSettings
    context_window: int | None = None


class ModelRegistry:
    def __init__(
        self, engine: Engine, vault: Vault, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._engine = engine
        self._vault = vault
        # Pooled client for provider model discovery; None ⇒ a transient client
        # per call (the path tests take, where discovery is monkeypatched out).
        self._http_client = http_client

    # --- endpoint catalog -------------------------------------------------

    async def list_endpoints(self, owner_id: str) -> list[ModelEndpoint]:
        def work(session: Session) -> list[ModelEndpoint]:
            return list(
                session.exec(
                    select(ModelEndpoint)
                    .where(ModelEndpoint.owner_id == owner_id)
                    .order_by(ModelEndpoint.name)
                ).all()
            )

        return await in_session(self._engine, work)

    async def get_endpoint(self, owner_id: str, endpoint_id: str) -> ModelEndpoint:
        def work(session: Session) -> ModelEndpoint | None:
            endpoint = session.get(ModelEndpoint, endpoint_id)
            return endpoint if endpoint is not None and endpoint.owner_id == owner_id else None

        endpoint = await in_session(self._engine, work)
        if endpoint is None:
            raise NotFoundError(f"endpoint {endpoint_id!r} not found")
        return endpoint

    async def create_endpoint(
        self,
        owner_id: str,
        *,
        name: str,
        base_url: str,
        model: str | None = None,
        api_key: str | None = None,
        context_window: int | None = None,
        native_tools: bool = True,
        vision: bool = False,
        thinking: bool = False,
    ) -> ModelEndpoint:
        endpoint = ModelEndpoint(
            owner_id=owner_id,
            name=name,
            base_url=base_url,
            model=model,
            api_key_enc=self._vault.encrypt_str(api_key) if api_key else None,
            context_window=context_window,
            native_tools=native_tools,
            vision=vision,
            thinking=thinking,
        )

        def work(session: Session) -> ModelEndpoint:
            session.add(endpoint)
            session.flush()
            session.refresh(endpoint)
            return endpoint

        return await in_session(self._engine, work)

    async def update_endpoint(
        self, owner_id: str, endpoint_id: str, **changes: object
    ) -> ModelEndpoint:
        """Apply field changes. ``api_key`` (plaintext, or "" to clear) is sealed
        before storage; ``model`` accepts "" to clear the default back to null;
        every other key maps straight onto the column."""
        await self.get_endpoint(owner_id, endpoint_id)  # ownership check

        def work(session: Session) -> ModelEndpoint:
            endpoint = session.get(ModelEndpoint, endpoint_id)
            assert endpoint is not None  # just confirmed it exists and is owned
            for key, value in changes.items():
                if key == "api_key":
                    endpoint.api_key_enc = self._vault.encrypt_str(str(value)) if value else None
                elif key == "model":
                    # An explicit empty value clears the default back to discovery-only.
                    endpoint.model = str(value) if value else None
                elif value is not None:
                    setattr(endpoint, key, value)
            endpoint.updated_at = datetime.now(UTC)
            session.add(endpoint)
            session.flush()
            session.refresh(endpoint)
            return endpoint

        return await in_session(self._engine, work)

    async def delete_endpoint(self, owner_id: str, endpoint_id: str) -> None:
        await self.get_endpoint(owner_id, endpoint_id)  # ownership check

        def work(session: Session) -> None:
            endpoint = session.get(ModelEndpoint, endpoint_id)
            if endpoint is not None:
                session.delete(endpoint)
            # Prune the id from every role chain that referenced it, so deleting an
            # endpoint can never leave a dangling reference a later resolve trips on.
            bindings = session.exec(
                select(ModelRole).where(ModelRole.owner_id == owner_id)
            ).all()
            for binding in bindings:
                if endpoint_id in binding.endpoint_ids:
                    binding.endpoint_ids = [e for e in binding.endpoint_ids if e != endpoint_id]
                    binding.updated_at = datetime.now(UTC)
                    session.add(binding)

        await in_session(self._engine, work)

    # --- role bindings ----------------------------------------------------

    async def get_role(self, owner_id: str, role: str) -> list[str]:
        """The ordered endpoint-id chain bound to ``role`` (empty if unbound)."""
        def work(session: Session) -> list[str]:
            binding = session.exec(
                select(ModelRole)
                .where(ModelRole.owner_id == owner_id)
                .where(ModelRole.role == role)
            ).first()
            return list(binding.endpoint_ids) if binding is not None else []

        return await in_session(self._engine, work)

    async def get_role_model(self, owner_id: str, role: str) -> str | None:
        """The explicit model pinned on ``role`` (``None`` ⇒ the endpoint's default)."""
        def work(session: Session) -> str | None:
            binding = session.exec(
                select(ModelRole)
                .where(ModelRole.owner_id == owner_id)
                .where(ModelRole.role == role)
            ).first()
            return binding.model if binding is not None else None

        return await in_session(self._engine, work)

    async def get_role_binding(
        self, owner_id: str, role: str
    ) -> tuple[list[str], str | None]:
        """The role's endpoint chain and pinned model in a single read — the chain
        and the model live on one row, so callers that need both (resolution,
        change-detection) shouldn't pay two round-trips."""
        def work(session: Session) -> tuple[list[str], str | None]:
            binding = session.exec(
                select(ModelRole)
                .where(ModelRole.owner_id == owner_id)
                .where(ModelRole.role == role)
            ).first()
            if binding is None:
                return [], None
            return list(binding.endpoint_ids), binding.model

        return await in_session(self._engine, work)

    async def list_role_models(self, owner_id: str) -> dict[str, str | None]:
        """The explicit model pinned on each bound role — the picker counterpart to
        :meth:`list_roles` (which returns the endpoint chains)."""
        def work(session: Session) -> dict[str, str | None]:
            bindings = session.exec(
                select(ModelRole).where(ModelRole.owner_id == owner_id)
            ).all()
            return {b.role: b.model for b in bindings}

        return await in_session(self._engine, work)

    async def list_roles(self, owner_id: str) -> dict[str, list[str]]:
        def work(session: Session) -> dict[str, list[str]]:
            bindings = session.exec(
                select(ModelRole).where(ModelRole.owner_id == owner_id)
            ).all()
            return {b.role: list(b.endpoint_ids) for b in bindings}

        return await in_session(self._engine, work)

    async def set_role(
        self, owner_id: str, role: str, endpoint_ids: list[str], *, model: str | None = None
    ) -> None:
        """Bind ``role`` to an ordered chain. Validates each endpoint exists and
        is owned, that tool-driving roles use only tool-calling endpoints, and —
        for ``embedding`` — that the bound endpoint/model actually serves vectors.

        ``model`` pins an explicit model on the bound endpoint (``None`` ⇒ the
        endpoint's default). It is the embedding role's stand-in for ``main``'s
        per-conversation picker: a global binding, so it persists here."""
        if role not in llm.ROLES:
            raise ValueError(f"unknown model role: {role!r}")
        endpoints = [await self.get_endpoint(owner_id, eid) for eid in endpoint_ids]
        if role in llm.TOOL_CALLING_ROLES:
            non_tool = [e.name for e in endpoints if not e.native_tools]
            if non_tool:
                raise ValueError(
                    f"role {role!r} requires native tool-calling; these lack it: {non_tool}"
                )
        if role == "embedding":
            await self._validate_embedding_endpoints(endpoints, model)

        def work(session: Session) -> None:
            binding = session.exec(
                select(ModelRole)
                .where(ModelRole.owner_id == owner_id)
                .where(ModelRole.role == role)
            ).first()
            if binding is None:
                session.add(
                    ModelRole(
                        owner_id=owner_id, role=role, endpoint_ids=endpoint_ids, model=model
                    )
                )
            else:
                binding.endpoint_ids = endpoint_ids
                binding.model = model
                binding.updated_at = datetime.now(UTC)
                session.add(binding)

        await in_session(self._engine, work)

    async def _validate_embedding_endpoints(
        self, endpoints: list[ModelEndpoint], model: str | None
    ) -> None:
        """Probe the primary endpoint with the selected model before the binding is
        saved, so a non-embeddings model (or an unreachable server) is rejected up
        front rather than silently degrading recall to keyword-only after the fact.
        Only the primary is probed — embedding resolution uses the chain head, not a
        fallback — so a chain whose endpoints serve different embedding models isn't
        wrongly rejected. A probe failure surfaces as ``ValueError`` → 422 at the route."""
        if not endpoints:
            return
        spec = self._to_spec(endpoints[0], "embedding", model_override=model)
        try:
            await embeddings.probe_embedding(spec)
        except DegradedCapabilityError as exc:
            raise ValueError(str(exc)) from exc

    # --- resolution -------------------------------------------------------

    async def _resolve_specs(
        self,
        role: str,
        *,
        owner_id: str,
        override_endpoint_id: str | None = None,
        override_model: str | None = None,
    ) -> list[llm.EndpointSpec]:
        """The ordered, decrypted endpoint specs ``role`` resolves to: a
        per-conversation ``main`` override → the role's own chain. Shared by
        :meth:`resolve` (which builds a model) and :meth:`resolve_detailed` (which
        also derives reasoning-off settings), so both see identical resolution."""
        if role not in llm.ROLES:
            raise ValueError(f"unknown model role: {role!r}")

        if override_endpoint_id is not None and role == "main":
            endpoint = await self.get_endpoint(owner_id, override_endpoint_id)
            return [self._to_spec(endpoint, role, model_override=override_model)]

        chain_ids = await self.get_role(owner_id, role)
        if not chain_ids:
            raise DegradedCapabilityError(f"no model endpoints configured for role {role!r}")

        endpoints = [await self.get_endpoint(owner_id, eid) for eid in chain_ids]
        return [self._to_spec(endpoint, role) for endpoint in endpoints]

    async def resolve(
        self,
        role: str,
        *,
        owner_id: str,
        override_endpoint_id: str | None = None,
        override_model: str | None = None,
    ) -> Model:
        """Resolve ``role`` to a model: per-conversation ``main`` override → the
        role's own chain. The chat picker overrides ``main`` with a provider
        (``override_endpoint_id``) and a specific model on it (``override_model``,
        discovered from the provider); ``utility``/``embedding`` resolve their own
        bindings. Wraps a multi-endpoint chain in ``FallbackModel`` (AE-5.3). An
        unconfigured role is a degraded capability — the registry is the only
        source of truth (the chat layer reuses ``main`` when ``utility`` is unset)."""
        return llm.build_chain(
            await self._resolve_specs(
                role,
                owner_id=owner_id,
                override_endpoint_id=override_endpoint_id,
                override_model=override_model,
            )
        )

    async def resolve_detailed(
        self,
        role: str,
        *,
        owner_id: str,
        override_endpoint_id: str | None = None,
        override_model: str | None = None,
    ) -> ResolvedModel:
        """Like :meth:`resolve`, but also returns the settings that disable the
        model's reasoning (from the **primary** endpoint — settings are uniform
        per run, so the chain's head decides). Background work that must be fast
        and not reason (titling) uses this; a model with no recognized thinking
        lever yields empty settings and is left to reason normally."""
        specs = await self._resolve_specs(
            role,
            owner_id=owner_id,
            override_endpoint_id=override_endpoint_id,
            override_model=override_model,
        )
        primary = specs[0]
        reasoning_off = reasoning.disable_thinking(
            reasoning.ModelDescriptor(
                model_id=primary.model,
                base_url=primary.base_url,
                thinking=primary.thinking,
            )
        )
        return ResolvedModel(
            model=llm.build_chain(specs),
            reasoning_off=reasoning_off,
            context_window=primary.context_window,
        )

    async def resolve_background(
        self,
        *,
        owner_id: str,
        override_endpoint_id: str | None = None,
        override_model: str | None = None,
    ) -> ResolvedModel:
        """The cheap model for background work — titling and verification — with its
        reasoning-off settings. Resolves the ``utility`` role, degrading to the picked
        ``main`` when ``utility`` is unbound (the picker override flows to that
        fallback, so it works for an operator who drives chat purely through the
        per-conversation picker). The reasoning-off settings travel with it
        unconditionally: a thinking model must be told not to think so it doesn't spend
        its capped output on a ``<think>`` block and die before emitting the title.
        One home for the utility→main rule both the chat layer and the manual
        re-title share."""
        try:
            return await self.resolve_detailed("utility", owner_id=owner_id)
        except (DegradedCapabilityError, NotFoundError):
            return await self.resolve_detailed(
                "main",
                owner_id=owner_id,
                override_endpoint_id=override_endpoint_id,
                override_model=override_model,
            )

    async def main_context_window(self, owner_id: str) -> int | None:
        """The default ``main`` chain head's context window, resolved without
        building a runnable model — for read paths (conversation detail) that need
        only the ceiling. None when ``main`` is unconfigured — or when its chain is
        unresolvable (e.g. a stale id left by an out-of-band delete): the context
        meter is a read-path nicety and must never fail the conversation read."""
        try:
            specs = await self._resolve_specs("main", owner_id=owner_id)
        except (DegradedCapabilityError, NotFoundError):
            return None
        return specs[0].context_window if specs else None

    async def resolve_embedding_spec(self, owner_id: str) -> llm.EndpointSpec:
        """The embedding endpoint as a raw spec — embeddings hit the provider's
        ``/embeddings`` API directly, not a Pydantic AI chat model, so the
        embedding service needs the base_url/model/key, not a built model.
        Unconfigured ⇒ degraded (recall falls back to keyword)."""
        chain_ids, model = await self.get_role_binding(owner_id, "embedding")
        if not chain_ids:
            raise DegradedCapabilityError("no embedding endpoint configured")
        endpoint = await self.get_endpoint(owner_id, chain_ids[0])
        return self._to_spec(endpoint, "embedding", model_override=model)

    async def list_provider_models(self, owner_id: str, endpoint_id: str) -> list[str]:
        """Ask the endpoint's provider which models it serves (the chat picker's
        dynamic list). Raises ``NotFoundError`` for an unknown endpoint and
        ``DegradedCapabilityError`` when the provider can't be reached or exposes
        no models API — the caller falls back to the endpoint's configured model."""
        endpoint = await self.get_endpoint(owner_id, endpoint_id)
        api_key = self._vault.decrypt_str(endpoint.api_key_enc) if endpoint.api_key_enc else None
        return await llm.discover_models(
            endpoint.base_url, api_key, client=self._http_client
        )

    def _to_spec(
        self, endpoint: ModelEndpoint, role: str, *, model_override: str | None = None
    ) -> llm.EndpointSpec:
        if role in llm.TOOL_CALLING_ROLES and not endpoint.native_tools:
            raise DegradedCapabilityError(
                f"role {role!r} requires native tool-calling, but endpoint "
                f"{endpoint.name!r} does not support it"
            )
        model = model_override or endpoint.model
        if not model:
            raise DegradedCapabilityError(
                f"endpoint {endpoint.name!r} has no model configured and none was selected"
            )
        api_key = (
            self._vault.decrypt_str(endpoint.api_key_enc)
            if endpoint.api_key_enc
            else llm.NO_API_KEY
        )
        return llm.EndpointSpec(
            base_url=endpoint.base_url,
            model=model,
            api_key=api_key,
            context_window=endpoint.context_window,
            native_tools=endpoint.native_tools,
            vision=endpoint.vision,
            thinking=endpoint.thinking,
        )
