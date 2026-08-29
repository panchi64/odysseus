"""FastAPI application assembly — the slim orchestrator.

Build the app, install middleware, wire auth, register routers, and hang shared
singletons (the run registry, capability handles) on ``app.state``. Business
logic lives below this layer; this file delegates. Pydantic AI is the engine,
this is the chassis — see ``docs/architecture/README.md``.
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from core.api_scopes import CORE_CLAIMS, ScopeTable
from core.auth import AuthManager, AuthMiddleware
from core.config import Settings, get_settings
from core.db import init_db, make_engine
from core.devserver import UNGUARDED_RELOAD_WARNING, reload_watches_runtime_state
from core.http_errors import install_error_handlers
from core.vault import Vault
from harness import LifecycleRegistry
from harness.discovery import discover_manifests
from harness.manifest import HarnessContext, ServiceContainer
from harness.run_terminal import RunTerminalDispatcher
from models.artifact import Artifact
from models.conversation import Conversation
from models.corpus import CorpusSource
from routes import (
    api_tokens,
    auth,
    chat,
    conversations,
    health,
    models,
    overview,
    runs,
    tokens,
    tools,
)
from runs import RunRegistry
from services.api_token_store import ApiTokenStore
from services.approval_grants import ApprovalGrantStore
from services.context_budget import OverheadCache
from services.conversations import ConversationStore
from services.credential_store import CredentialStore
from services.embeddings import RegistryEmbedder
from services.plans import ConversationPlans
from services.registry import ModelRegistry
from services.sandbox import SandboxSessionManager, detect_sandbox, shutdown_confinement
from services.sealing import seal_legacy_column
from services.settings_store import SettingsStore
from tools import (
    CORE_GATED_TOOLS,
    InstructionProvider,
    PromptContextProvider,
    core_categories,
)
from tools.agents import delegate_instructions
from tools.plan import plan_context
from tools.repo import repo_instructions

logger = logging.getLogger(__name__)


async def _backfill_sealed_columns(engine: Engine, vault: Vault) -> None:
    """Once the vault is unlocked, seal the columns that were stored in the clear before
    they were sealed — the conversation title, the corpus source's host path, and the
    artifact's title and filename — and drop
    the cleartext behind them (`XC-SEC-3`).

    A migration can't do this: schema upgrades run at startup with the vault locked, so
    there is no key. This waits for unlock like ``_backfill_embeddings``, is idempotent (a
    healed row no longer matches), and is best-effort per column — one table failing must
    not stop the other from being healed, and neither must take the boot down."""
    await vault.unlocked_event.wait()
    for model_cls, legacy, sealed in (
        (Conversation, "title", "title_enc"),
        (CorpusSource, "path", "path_enc"),
        (Artifact, "title", "title_enc"),
        (Artifact, "filename", "filename_enc"),
    ):
        try:
            await seal_legacy_column(
                engine=engine,
                vault=vault,
                model_cls=model_cls,
                legacy_attr=legacy,
                sealed_attr=sealed,
            )
        except Exception:
            logger.exception("at-rest: sealing legacy %s values failed", legacy)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Process-lifetime startup/shutdown.

    Brings up the run registry and the persistence store (DB engine + schema +
    write-behind drainer). Shutdown flushes pending writes. Capability handles
    (``services/``) wire in here as they land.
    """
    settings: Settings = app.state.settings
    # Owns every background start/stop below: a unit registers at its construction
    # point and shutdown unwinds in reverse registration order — the `finally` block
    # is one call, not a hand-maintained mirror of this sequence. Something that must
    # stop *earlier* than its construction position implies simply registers later.
    lifecycle = LifecycleRegistry()
    # `_wire` starts long-lived units as it goes, so it runs inside the same `try` as
    # the serving phase below. A manifest that fails to build half-way has to unwind the
    # units already started — otherwise a boot that never finishes leaves containers,
    # drainers, and proxy listeners running with nothing left holding a reference.
    try:
        await _wire(app, settings, lifecycle)
        yield
    finally:
        await lifecycle.stop_all()


async def _wire(app: FastAPI, settings: Settings, lifecycle: LifecycleRegistry) -> None:
    """Build, wire, and start everything the app owns, in dependency order.

    Every unit needing shutdown registers on ``lifecycle`` at its construction point,
    so the caller's single ``stop_all`` unwinds the whole graph — including a partially
    built one, when a build raises part-way through.
    """
    # Typed capability handles. Core wiring adds what it builds; each feature
    # manifest's build resolves its cross-feature dependencies here and adds what
    # it hands back — never by importing another feature's wiring.
    container = ServiceContainer()
    # The agent-facing capability bag (`RunDeps.caps`): the curated subset of
    # services the agent's tools may reach, assembled from each manifest's
    # `capabilities` export (plus the core-owned handles below). Every run path
    # hands this same bag to the engine.
    agent_capabilities = ServiceContainer()
    app.state.capabilities = agent_capabilities
    app.state.auth_manager = AuthManager()
    # Inbound scoped API tokens (`AUTH-4`). Wired below with the engine, but named here
    # because the auth gate runs on every request — including ones that arrive before the
    # lifespan finishes — and reads it straight off `app.state`. Absent would mean "no
    # second authentication method"; an explicit None says the same thing without the
    # gate having to distinguish "not wired yet" from "deliberately not offered".
    app.state.api_tokens = None

    # The registry's injected terminal-transition point — features contribute hooks
    # (waiter resolution, notification policy) without `runs/` importing `services/`
    # (it only knows it holds an optional callback). The in-flight terminal tasks
    # stay reachable as `app.state.run_terminal_tasks` so shutdown drains them and a
    # test can await "every pending notify has settled" deterministically.
    run_terminal = RunTerminalDispatcher()
    app.state.run_terminal_tasks = run_terminal.tasks

    app.state.runs = RunRegistry(
        max_concurrency=settings.run_max_concurrency,
        wall_clock_timeout_s=settings.run_wall_clock_timeout_s,
        inactivity_timeout_s=settings.run_inactivity_timeout_s,
        on_terminal=run_terminal,
    )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # `uvicorn app:app --reload` watches the data directory, so the first serve of a model
    # restarts the server while its engine is installing. Nothing here can stop that — the
    # reloader is the parent process — but a server that knows it is about to behave that
    # way should say so, because the symptom (a serve that dies silently) points nowhere
    # near the cause.
    if reload_watches_runtime_state(sys.argv, settings.data_dir):
        logger.warning(UNGUARDED_RELOAD_WARNING, settings.data_dir)
    url = settings.db_url or f"sqlite:///{settings.data_dir / 'app.db'}"
    # Whether the database backing this workspace is intact — read *before* `init_db`
    # creates and migrates it, because afterwards a deleted database is indistinguishable
    # from a fresh one. What says a workspace exists is the keyfile, which sits beside the
    # database rather than inside it, so an operator who clears `app.db` to start over is
    # otherwise still asked to unlock a key that now protects nothing. The two facts
    # together are what `/auth/status` reports as `db_missing`. An explicit `db_url` counts
    # as intact: we make no claim about a database whose path we don't own.
    db_path = None if settings.db_url else settings.data_dir / "app.db"
    app.state.workspace_db_intact = db_path.exists() if db_path else True
    engine = make_engine(url)
    init_db(engine)
    app.state.db_engine = engine
    # The one instance both the auth gate and the `/tokens` routes use — a token revoked
    # through the route has to invalidate exactly what the gate trusts, which two stores
    # with two verification caches wouldn't do.
    app.state.api_tokens = ApiTokenStore(engine, app.state.api_scope_table)

    # The at-rest encryption vault. A passphrase (auth-disabled path) sets it up
    # or unlocks it at boot; otherwise it stays locked until the operator unlocks
    # via login/setup.
    vault = Vault(settings.data_dir / "keyfile.json")
    app.state.vault = vault
    if settings.unlock_passphrase:
        if vault.is_initialized:
            await vault.unlock(settings.unlock_passphrase)
        else:
            await vault.setup(settings.unlock_passphrase)

    # Pooled outbound client for provider model discovery (the chat model picker).
    # Connection-reused across endpoints; follows redirects (some providers 30x).
    discovery_client = httpx.AsyncClient(follow_redirects=True)
    app.state.discovery_client = discovery_client
    lifecycle.on_stop("discovery-client", discovery_client.aclose)
    # Host-command confinement configures itself lazily on the first approved host command
    # and starts proxy listeners doing so. Registered here so they stop with the app —
    # under the reloading dev server they would otherwise accumulate per restart.
    lifecycle.on_stop("host-confinement", shutdown_confinement)
    # The model registry — role→endpoint resolution + the endpoint catalog.
    registry = ModelRegistry(engine, vault, http_client=discovery_client)
    app.state.models = registry
    # One embedder over the registry's embedding role, shared by long-term memory and
    # cross-chat search; degrades to keyword recall when no embedding endpoint is set.
    embedder = RegistryEmbedder(registry)
    # The conversation store — in-memory working tree + write-behind persistence. It
    # embeds each persisted turn (best-effort) so conversations are semantically
    # searchable across chats. Built after the registry so it can share the embedder.
    app.state.conversations = ConversationStore(engine, vault, embedder)
    await lifecycle.start(
        "conversations",
        start=app.state.conversations.start,
        stop=app.state.conversations.stop,
    )
    # Outbound service credentials — the operator's API keys for third-party services,
    # sealed with the vault.
    app.state.credentials = CredentialStore(engine, vault)
    # Owner-scoped app preferences. Built here — earlier than the capabilities that read
    # it below — because the notification channels resolve their own configuration from
    # it, and they are composed with the attention surface a few lines down.
    app.state.settings_store = SettingsStore(engine)
    # What a request weighs besides the conversation, per mode — so a reloaded thread can
    # still break its context down. Deliberately in memory rather than in the database:
    # it describes the current tool/brief configuration, not the thread's history.
    app.state.context_overhead = OverheadCache()
    # Conversation-scoped tool auto-approval grants — part of the approval posture,
    # so it stays core beside the run substrate the approvals park on.
    app.state.approval_grants = ApprovalGrantStore(engine, settings.approval_grant_ttl_s)
    # Seal the columns that predate their own encryption: the migration that added
    # the sealed column ran before unlock with no key, so the healing happens here
    # once unlocked (XC-SEC-3).
    lifecycle.track("sealing-backfill", _backfill_sealed_columns(engine, vault))
    # The execution sandbox — detected once at boot. None ⇒ no runtime, so the
    # code-execution capability is disabled (it never falls back to the host).
    # Present ⇒ wrap it in a per-conversation session manager that keeps a
    # container warm for iterative work and reaps it when idle.
    backend = await detect_sandbox(settings)
    sandbox_manager = (
        SandboxSessionManager(
            backend,
            vault,
            data_dir=settings.data_dir,
            idle_ttl_s=settings.sandbox_session_idle_ttl_s,
            reap_interval_s=settings.sandbox_session_reap_interval_s,
            excludes=settings.sandbox_session_seal_excludes,
            preview_startup_timeout_s=settings.sandbox_preview_startup_timeout_s,
            spare_enabled=settings.sandbox_spare_enabled,
            spare_count=settings.sandbox_spare_count,
        )
        if backend is not None
        else None
    )
    app.state.sandbox = sandbox_manager
    if sandbox_manager is not None:
        # Logs its own code-execution + preview boot status and warms the image.
        await lifecycle.start("sandbox", start=sandbox_manager.start, stop=sandbox_manager.stop)
    else:
        logger.info("sandbox: code execution disabled (no container runtime)")
        logger.info("preview: disabled (no container runtime)")

    # Transitional: capabilities still hand-wired above register on the container so
    # converted manifests can resolve them. Each of these lines moves into its own
    # feature's manifest (its `services` return) as that feature converts.
    for handle in (
        app.state.auth_manager,
        run_terminal,
        app.state.runs,
        app.state.models,
        embedder,
        app.state.conversations,
        app.state.credentials,
        app.state.settings_store,
        app.state.approval_grants,
        app.state.api_tokens,
    ):
        container.add(handle)
    if sandbox_manager is not None:
        container.add(sandbox_manager)
        agent_capabilities.add(sandbox_manager)
    # The core-owned agent-facing handles: the engine consults grants at the deferred
    # split, and the sandbox backs code execution. Everything else reaches the bag
    # through its own manifest's `capabilities` export.
    agent_capabilities.add(app.state.approval_grants)
    # Delegation resolves the `utility` model for its sub-agents through the same
    # `resolve_background` rule titling and verification use, so a delegate is cheap by
    # construction rather than by a second policy.
    agent_capabilities.add(app.state.models)
    # The agent's task list: core-owned like the sandbox, because the `plan` category is a
    # core category rather than a feature manifest's.
    app.state.conversation_plans = ConversationPlans(engine, vault)
    container.add(app.state.conversation_plans)
    agent_capabilities.add(app.state.conversation_plans)

    # Feature manifests build last, in dependency (`after`) order — everything
    # hand-wired above is the core they resolve from the container. What a build
    # hands back wires in here: services for later manifests (and the agent's
    # tools), transitional `app.state` names for `routes/deps.py`, and run-terminal
    # hooks. Their routers were registered at app assembly (`create_app`).
    ctx = HarnessContext(
        settings=settings,
        engine=engine,
        vault=vault,
        lifecycle=lifecycle,
        services=container,
        capabilities=agent_capabilities,
        tool_categories=app.state.tool_categories,
        instruction_providers=app.state.instruction_providers,
        prompt_context_providers=app.state.prompt_context_providers,
        network_tools=app.state.network_tools,
    )
    for manifest in app.state.feature_manifests:
        if manifest.enabled is not None and not manifest.enabled(settings):
            continue
        if manifest.build is None:
            continue
        runtime = await manifest.build(ctx)
        for service in runtime.services:
            container.add(service)
        for capability in runtime.capabilities:
            # A bare instance keys by its own type; an `(instance, as_type)` pair keys
            # by an abstraction, so a capability living above `tools/` stays reachable
            # from one. See `FeatureRuntime.capabilities`.
            if isinstance(capability, tuple):
                instance, as_type = capability
                agent_capabilities.add(instance, as_type=as_type)
            else:
                agent_capabilities.add(capability)
        for name, value in runtime.state.items():
            setattr(app.state, name, value)
        for sync_hook in runtime.run_terminal_sync:
            run_terminal.add_sync(sync_hook)
        for hook in runtime.run_terminal:
            run_terminal.add(hook)

    # Registered last so it stops first (reverse registration order): live runs write
    # through the stores and the sandbox brought up above, so they have to be cancelled
    # — and given their own pre-cancel flush — while those are still running. Without
    # this a turn in flight at shutdown submits onto an already-stopped write-behind
    # drainer, which discards it with no error.
    lifecycle.on_stop("runs", app.state.runs.shutdown)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Odysseus", version=settings.version, lifespan=lifespan)
    app.state.settings = settings  # the lifespan reads this (tests inject it)
    # Discovered once per app: routers register below (before the lifespan runs);
    # the lifespan runs each enabled manifest's build in the same order.
    app.state.feature_manifests = discover_manifests()
    enabled_manifests = [
        m
        for m in app.state.feature_manifests
        if m.enabled is None or m.enabled(settings)
    ]

    # The inbound-token scope table: core's own claims plus every enabled feature's.
    # A surface nothing claims stays token-unreachable (deny-by-default), and the
    # auth-exempt prefixes are likewise the core set plus each feature's declared own.
    scope_table = ScopeTable(
        [*CORE_CLAIMS, *(claim for m in enabled_manifests for claim in m.api_scopes)]
    )
    app.state.api_scope_table = scope_table
    public_prefixes = tuple(
        prefix for m in enabled_manifests for prefix in m.public_prefixes
    )

    # The agent's tool catalog: the core categories plus every enabled manifest's
    # `toolsets` export, plus the union of their conditionally-gated names and their
    # dynamic instruction providers. Assembled once — chat turns, scheduled tasks,
    # and the operator-facing catalog routes all read these same objects, so the
    # listing and the agent's own stack cannot diverge.
    tool_categories = core_categories()
    # The core categories have no manifest to declare their conditionally-gated names,
    # so they seed the set here. `shell` matters: it raises `ApprovalRequired` from
    # inside the call, which parks the run either way — but a name missing from this
    # union is missing from the *scope vocabulary*, so the operator could never grant
    # it for the conversation and would be asked again on every single command.
    gated_tools: set[str] = set(CORE_GATED_TOOLS)
    # Which tools can't work without internet — each feature declares its own, and offline
    # mode enforces the union. The feature that suspends them is not the feature that
    # ships them, so the declaration travels rather than being restated at the gate.
    network_tools: set[str] = set()
    # The delegate listing is core, not a manifest's, for the same reason the plan
    # reminder below is: the `agents` category ships with the harness core categories.
    # It is small and static, so the prompt *head* is the right home — it stays in the
    # cached prefix rather than churning per turn.
    # `repo_instructions` joins it for the same reason and returns "" outside coding
    # mode, so a chat thread pays nothing for it.
    instruction_providers: list[InstructionProvider] = [
        delegate_instructions,
        repo_instructions,
    ]
    # The plan reminder is core, not a manifest's: the `plan` category ships with the
    # harness core categories, so its tail context has to be seeded here alongside them.
    prompt_context_providers: list[PromptContextProvider] = [plan_context]
    for manifest in enabled_manifests:
        for category, factory in manifest.toolsets:
            if category in tool_categories:
                raise RuntimeError(
                    f"tool category {category!r} declared twice "
                    f"(second claim by manifest {manifest.name!r})"
                )
            tool_categories[category] = factory()
        gated_tools |= manifest.gated_tools
        network_tools |= manifest.network_tools
        instruction_providers.extend(manifest.instructions)
        prompt_context_providers.extend(manifest.prompt_context)
    app.state.tool_categories = tool_categories
    app.state.gated_tools = frozenset(gated_tools)
    app.state.network_tools = frozenset(network_tools)
    app.state.instruction_providers = tuple(instruction_providers)
    app.state.prompt_context_providers = tuple(prompt_context_providers)

    # Domain errors answered at the transport boundary, per `core.http_errors`. This is
    # what `core.exceptions` has always said happens here: a route that doesn't catch a
    # `NotFoundError` now returns a 404 rather than a 500.
    install_error_handlers(app)

    # The auth gate runs inside CORS (added first ⇒ inner), so CORS can answer
    # preflight and decorate even a 401 with the right headers.
    app.add_middleware(
        AuthMiddleware, scope_table=scope_table, extra_public_prefixes=public_prefixes
    )

    # Origin-agnostic API: the backend makes no assumption about who serves the
    # frontend. CORS is configurable; bearer auth works same- or split-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(runs.router)
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(overview.router)
    app.include_router(models.router)
    app.include_router(api_tokens.router)
    app.include_router(tools.router)
    app.include_router(tokens.router)
    # Every feature surface registers through its manifest; a manifest whose
    # `enabled` gate is off contributes nothing — its routes are simply 404.
    for manifest in enabled_manifests:
        for router in manifest.routers:
            app.include_router(router)
    return app


app = create_app()
