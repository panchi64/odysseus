"""What a feature declares to the harness — one file names all its layered pieces.

A feature stays split across the layers (`routes/` + `tools/` + `services/` +
`models/`), because the layer law is what keeps the dependency direction honest;
its *cohesion* lives here instead: a single `FeatureManifest` in
``harness/manifests/<name>.py`` declares the routers it serves, the API scopes it
claims, the services it builds, and the hooks it registers. The harness discovers
manifests by walking that package — presence is registration, the same contract as
``models/_discovery`` and the backup marker — so landing a feature never edits a
central list.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter
    from sqlalchemy import Engine

    from core.api_scopes import ScopeClaim
    from core.config import Settings
    from core.vault import Vault
    from harness.lifecycle import LifecycleRegistry
    from harness.run_terminal import RunTerminalHook, SyncRunTerminalHook


class ServiceContainer:
    """Typed service handles, keyed by concrete class.

    The one place a built capability is looked up by another — a feature's build
    resolves its cross-feature dependencies here instead of importing another
    feature's wiring. Missing means a wiring bug (a manifest forgot an ``after``
    edge or an export), so ``get`` raises rather than degrades; optionality is the
    *caller's* semantic and spelled ``get_optional``.
    """

    def __init__(self) -> None:
        self._services: dict[type, object] = {}

    def add(self, instance: object, *, as_type: type | None = None) -> None:
        key = as_type if as_type is not None else type(instance)
        if key in self._services:
            raise LookupError(f"service already registered for {key.__name__}")
        self._services[key] = instance

    def get[T](self, service_type: type[T]) -> T:
        try:
            return self._services[service_type]  # type: ignore[return-value]
        except KeyError:
            raise LookupError(
                f"no service registered for {service_type.__name__} — "
                "a manifest is missing an `after` edge or an export"
            ) from None

    def get_optional[T](self, service_type: type[T]) -> T | None:
        return self._services.get(service_type)  # type: ignore[return-value]


@dataclass(frozen=True)
class HarnessContext:
    """What a feature's ``build`` sees: the core handles plus every service built
    before it (its own ``after`` edges guarantee which those are)."""

    settings: Settings
    engine: Engine
    vault: Vault
    lifecycle: LifecycleRegistry
    services: ServiceContainer


@dataclass(frozen=True)
class FeatureRuntime:
    """What a feature's ``build`` hands back for the harness to wire in."""

    # Capability instances other features (and, later, the agent's tools) resolve
    # from the container — keyed by each instance's concrete type.
    services: tuple[object, ...] = ()
    # Names hung on ``app.state`` — the transitional seam ``routes/deps.py``'s
    # accessors read; shrinks as those accessors move onto the container.
    state: Mapping[str, object] = field(default_factory=dict)
    # Run-terminal participation (see ``harness/run_terminal.py``): sync hooks run
    # inline in the registry's terminal transition, async hooks run as tracked tasks.
    run_terminal_sync: tuple[SyncRunTerminalHook, ...] = ()
    run_terminal: tuple[RunTerminalHook, ...] = ()


@dataclass(frozen=True)
class FeatureManifest:
    """One feature, declared. ``harness/manifests/<name>.py`` exposes it as
    ``MANIFEST``; everything else follows from discovery."""

    name: str
    # Manifest names whose services this build resolves — the only ordering input.
    after: tuple[str, ...] = ()
    # Routers registered at app assembly (before the lifespan runs).
    routers: tuple[APIRouter, ...] = ()
    # Inbound-token scope claims for this feature's surfaces (`AUTH-4`). A surface
    # no manifest (and no core claim) covers stays token-unreachable.
    api_scopes: tuple[ScopeClaim, ...] = ()
    # Path prefixes exempt from the auth gate — for surfaces whose unguessable
    # path token *is* the credential. Claiming one is a deliberate, visible act.
    public_prefixes: tuple[str, ...] = ()
    # Feature kill-switch: when it returns False the routers are never registered
    # and the build never runs.
    enabled: Callable[[Settings], bool] | None = None
    # Constructs the feature's services at lifespan time. None ⇒ routes-only.
    build: Callable[[HarnessContext], Awaitable[FeatureRuntime]] | None = None
