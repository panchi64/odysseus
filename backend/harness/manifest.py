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

from core.container import ServiceContainer

if TYPE_CHECKING:
    from fastapi import APIRouter
    from pydantic_ai import AbstractToolset
    from sqlalchemy import Engine

    from core.api_scopes import ScopeClaim
    from core.config import Settings
    from core.vault import Vault
    from harness.lifecycle import LifecycleRegistry
    from harness.run_terminal import RunTerminalHook, SyncRunTerminalHook
    from tools import InstructionProvider, PromptContextProvider, RunDeps

__all__ = [
    "FeatureManifest",
    "FeatureRuntime",
    "HarnessContext",
    "ServiceContainer",
]


@dataclass(frozen=True)
class HarnessContext:
    """What a feature's ``build`` sees: the core handles plus every service built
    before it (its own ``after`` edges guarantee which those are)."""

    settings: Settings
    engine: Engine
    vault: Vault
    lifecycle: LifecycleRegistry
    services: ServiceContainer
    # The agent-facing capability bag (`RunDeps.caps`) as assembled so far — what a
    # feature composing agent runs (the task scheduler) hands to the engine.
    capabilities: ServiceContainer
    # The assembled tool-category mapping and instruction providers (core + every
    # enabled manifest's declarations, complete before any build runs) — so a feature
    # composing agent runs hands the engine exactly what an interactive turn gets.
    tool_categories: Mapping[str, AbstractToolset[RunDeps]] = field(default_factory=dict)
    instruction_providers: tuple[InstructionProvider, ...] = ()
    prompt_context_providers: tuple[PromptContextProvider, ...] = ()


@dataclass(frozen=True)
class FeatureRuntime:
    """What a feature's ``build`` hands back for the harness to wire in."""

    # Capability instances other features resolve from the container — keyed by
    # each instance's concrete type.
    services: tuple[object, ...] = ()
    # The subset of those instances the *agent's tools* may reach through
    # ``RunDeps.caps`` — the curated agent-facing boundary. A service not exported
    # here is invisible to every tool (the shell exports nothing, by design).
    capabilities: tuple[object, ...] = ()
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
    # The tool categories this feature contributes to the agent's catalog, as
    # (category, factory) pairs — declared as factories so importing a manifest
    # builds nothing. Assembled with the core categories at app startup; a duplicate
    # category name fails the boot loudly.
    toolsets: tuple[tuple[str, Callable[[], AbstractToolset[RunDeps]]], ...] = ()
    # Namespaced tool names whose approval gate is runtime-conditional (they raise
    # ``ApprovalRequired`` from inside the call, so inspection can't find them) —
    # this feature's contribution to the approval-scope vocabulary.
    gated_tools: frozenset[str] = frozenset()
    # Dynamic instruction providers the engine registers on every agent it builds —
    # each resolves its capability from the run's bag and returns "" to no-op. These
    # render at the *head* of every request, so they should stay small and low-churn:
    # any byte change here invalidates the inference engine's prompt-prefix cache for
    # the entire history behind it.
    instructions: tuple[InstructionProvider, ...] = ()
    # Per-turn prompt-context providers — like `instructions` re-resolved fresh each
    # turn and never persisted, but delivered at the *tail* of the current turn's user
    # prompt, where volatile or large content leaves the request prefix (and so the
    # engine's prompt cache) intact.
    prompt_context: tuple[PromptContextProvider, ...] = ()
    # Constructs the feature's services at lifespan time. None ⇒ routes-only.
    build: Callable[[HarnessContext], Awaitable[FeatureRuntime]] | None = None
