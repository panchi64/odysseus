"""FastAPI application assembly — the slim orchestrator.

Build the app, install middleware, wire auth, register routers, and hang shared
singletons (the run registry, capability handles) on ``app.state``. Business
logic lives below this layer; this file delegates. Pydantic AI is the engine,
this is the chassis — see ``docs/architecture/README.md``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from core.auth import AuthManager, AuthMiddleware
from core.config import Settings, get_settings
from core.db import init_db, make_engine
from core.ratelimit import RateLimiter
from core.vault import Vault
from harness import LifecycleRegistry
from harness.discovery import discover_manifests
from harness.manifest import HarnessContext, ServiceContainer
from harness.run_terminal import RunTerminalDispatcher
from models.conversation import Conversation
from models.corpus import CorpusSource
from routes import (
    api_tokens,
    auth,
    backup,
    calendar,
    chat,
    conversations,
    health,
    integrations,
    mail,
    mcp,
    models,
    notifications,
    overview,
    runs,
    secret_vault,
    shell,
    tokens,
    tools,
)
from routes.deps import OPERATOR_ID
from runs import Run, RunRegistry, RunStatus
from services.api_token_store import ApiTokenStore
from services.approval_grants import ApprovalGrantStore
from services.backup import BackupService
from services.calendar import CalendarService
from services.calendar.nl import CalendarNaturalLanguage
from services.conversations import ConversationStore
from services.credential_store import CredentialStore
from services.embeddings import RegistryEmbedder
from services.external_tools import build_external_tools
from services.host_shell import ShellService
from services.mail import MailService
from services.notification_channels import default_channels
from services.notifications import NotificationService
from services.registry import ModelRegistry
from services.sandbox import SandboxSessionManager, detect_sandbox
from services.sealing import seal_legacy_column
from services.secret_vault import SecretVaultService
from services.settings_store import SettingsStore

logger = logging.getLogger(__name__)


async def _backfill_sealed_columns(engine: Engine, vault: Vault) -> None:
    """Once the vault is unlocked, seal the columns that were stored in the clear before
    they were sealed — the conversation title and the corpus source's host path — and drop
    the cleartext behind them (`XC-SEC-3`).

    A migration can't do this: schema upgrades run at startup with the vault locked, so
    there is no key. This waits for unlock like ``_backfill_embeddings``, is idempotent (a
    healed row no longer matches), and is best-effort per column — one table failing must
    not stop the other from being healed, and neither must take the boot down."""
    await vault.unlocked_event.wait()
    for model_cls, legacy, sealed in (
        (Conversation, "title", "title_enc"),
        (CorpusSource, "path", "path_enc"),
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
    # Typed capability handles. Core wiring adds what it builds; each feature
    # manifest's build resolves its cross-feature dependencies here and adds what
    # it hands back — never by importing another feature's wiring.
    container = ServiceContainer()
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

    async def _resolve_dangling_approvals(run: Run, watched: bool) -> None:
        """The backstop: a cancel-while-parked never reaches the approve route, and
        even a normal completion may still carry a dangling approval_needed if the
        operator never decided it. `app.state.notifications` is read lazily — a run
        can't reach terminal before it exists, so the forward reference is safe
        despite the registry being built before that singleton."""
        try:
            await app.state.notifications.resolve_for_run(OPERATOR_ID, run.id)
        except Exception:
            logger.exception("notifications: failed to resolve run %s at terminal", run.id)

    async def _notify_conversation_terminal(run: Run, watched: bool) -> None:
        """Only conversation-linked runs notify (a stateless/detached run — research
        included — has no thread to deep-link to); cancelled and blocked outcomes
        stay silent — the operator asked for the cancel, and a bound/limit stop
        isn't a noteworthy failure."""
        if run.conversation_id is None or run.status in (RunStatus.cancelled, RunStatus.blocked):
            return
        notifications = app.state.notifications
        try:
            summary = await app.state.conversations.get_summary(run.conversation_id, OPERATOR_ID)
            title = summary.title if summary is not None and summary.title else "this conversation"
            if run.status is RunStatus.error:
                await notifications.notify(
                    OPERATOR_ID,
                    "run_failed",
                    f'"{title}" hit an error',
                    body=run.error,
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                )
            elif run.status is RunStatus.done and not watched:
                # Only notify a plain completion when nobody was watching — a
                # subscriber attached to the run's own stream already saw it finish.
                await notifications.notify(
                    OPERATOR_ID,
                    "run_completed",
                    f'"{title}" finished',
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                )
        except Exception:
            logger.exception("notifications: failed to notify run %s at terminal", run.id)

    run_terminal.add(_resolve_dangling_approvals)
    run_terminal.add(_notify_conversation_terminal)

    app.state.runs = RunRegistry(
        max_concurrency=settings.run_max_concurrency,
        wall_clock_timeout_s=settings.run_wall_clock_timeout_s,
        inactivity_timeout_s=settings.run_inactivity_timeout_s,
        on_terminal=run_terminal,
    )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    url = settings.db_url or f"sqlite:///{settings.data_dir / 'app.db'}"
    engine = make_engine(url)
    init_db(engine)
    app.state.db_engine = engine
    # The one instance both the auth gate and the `/tokens` routes use — a token revoked
    # through the route has to invalidate exactly what the gate trusts, which two stores
    # with two verification caches wouldn't do.
    app.state.api_tokens = ApiTokenStore(engine)

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

    # The Operator Shell — a host PTY streamed to the browser, agent-unreachable by
    # construction (`services/host_shell.py`). Its own rate limiter throttles
    # password attempts against the host-mode grant endpoint like uploads throttle
    # theirs; killing every live session the instant the vault locks is wired via
    # the vault's on-lock callback registry rather than the auth route knowing the
    # shell exists. `shell_enabled` is the kill-switch: when off, its router isn't
    # even registered (see `create_app`), so nothing here needs to exist either.
    if settings.shell_enabled:
        app.state.shell_auth_rate_limiter = RateLimiter(
            rate_per_second=settings.shell_auth_rate_per_minute / 60.0,
            burst=settings.shell_auth_rate_burst,
        )
        app.state.shell = ShellService(
            settings=settings, vault=vault, auth_manager=app.state.auth_manager
        )
        vault.register_on_lock(app.state.shell.kill_all)
        lifecycle.on_stop("shell", app.state.shell.stop)
    else:
        app.state.shell = None

    # Pooled outbound client for provider model discovery (the chat model picker).
    # Connection-reused across endpoints; follows redirects (some providers 30x).
    discovery_client = httpx.AsyncClient(follow_redirects=True)
    app.state.discovery_client = discovery_client
    lifecycle.on_stop("discovery-client", discovery_client.aclose)
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
    # The attention surface — a durable notification record + its own live stream,
    # separate from the frozen per-run event stream. Just the substrate here (record +
    # stream); the emit policy (which run outcomes are noteworthy) wires in where those
    # events happen (approval parking, run terminal transitions, approve/deny routes).
    #
    # Its out-of-band channels (`AE-3.2`, `TASK-6`) are composed in here. The email
    # channel takes the mail service as a *callable* rather than a value because the
    # dependency runs both ways — mail raises triage alerts through this surface, and this
    # surface sends through mail. Resolving late is what breaks the cycle; the channel is
    # only ever called long after both exist.
    app.state.notifications = NotificationService(
        engine,
        vault,
        channels=default_channels(
            lambda: app.state.mail, app.state.settings_store, vault
        ),
    )
    await lifecycle.start(
        "notifications",
        start=app.state.notifications.start,
        stop=app.state.notifications.stop,
    )
    # Email (`EMAIL-1..5`) — accounts, the sync loop, the inbox cache, triage and drafts.
    # Built immediately after the attention surface (the other half of the cycle above) so
    # a triage alert has somewhere to land. Its sync worker seals message content, so it
    # parks while the vault is locked rather than failing.
    app.state.mail = MailService(
        engine,
        vault,
        app.state.credentials,
        registry,
        notifications=app.state.notifications,
    )
    # Mail stops before the attention surface it notifies through (registered after ⇒
    # stops earlier): the sync loop can raise a triage alert on its way down, and a
    # channel delivery may still be draining.
    await lifecycle.start("mail", start=app.state.mail.start, stop=app.state.mail.stop)
    # The calendar (`CAL-1..3`). Nothing to start or stop: no worker, no held connections
    # — CalDAV sync runs per request. Its natural-language parser resolves the background
    # model per call (the `services/webfetch/distill.py` seam), so a role rebound at
    # runtime takes effect without rebuilding anything.
    async def _resolve_calendar_model():
        resolved = await registry.resolve_background(owner_id=OPERATOR_ID)
        return resolved.model, resolved.reasoning_off

    app.state.calendar = CalendarService(
        engine, vault, nl=CalendarNaturalLanguage(resolve_model=_resolve_calendar_model)
    )
    # External tools — registered MCP servers (`MCP-*`), configured connectors
    # (`INTEG-*`) and the per-tool trust policy they share (`AE-3.6`), as one handle. The
    # factory is the only way to build it, so both sources are guaranteed the *same*
    # policy store. MCP connections are opened per run, not held here.
    app.state.external = build_external_tools(engine, vault)
    # The operator's secrets manager (`VAULT-*`) — distinct from `vault` above, which is
    # at-rest key custody. Constructing it *is* registering its lock hook (it calls
    # `vault.register_on_lock` itself), so an app lock ends every secret session too and
    # there is deliberately nothing more to wire here.
    app.state.secret_vault = SecretVaultService(engine, vault)
    # Encrypted export/import (`BACKUP-*`), under its own operator secret and its own KDF.
    app.state.backup = BackupService(engine, vault, app.state.settings_store)
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

    # Drain in-flight run-terminal tasks before the stores they read (notifications,
    # conversations) stop. Registered late so it runs early.
    lifecycle.on_stop("run-terminal-notifies", run_terminal.drain)

    # Transitional: capabilities still hand-wired above register on the container so
    # converted manifests can resolve them. Each of these lines moves into its own
    # feature's manifest (its `services` return) as that feature converts.
    for handle in (
        app.state.runs,
        app.state.models,
        embedder,
        app.state.conversations,
        app.state.credentials,
        app.state.settings_store,
        app.state.notifications,
        app.state.mail,
        app.state.calendar,
        app.state.external,
        app.state.secret_vault,
        app.state.backup,
        app.state.approval_grants,
        app.state.api_tokens,
    ):
        container.add(handle)
    if sandbox_manager is not None:
        container.add(sandbox_manager)

    # Feature manifests build last, in dependency (`after`) order — everything
    # hand-wired above is the core they resolve from the container. What a build
    # hands back wires in here: services for later manifests (and the agent's
    # tools), transitional `app.state` names for `routes/deps.py`, and run-terminal
    # hooks. Their routers were registered at app assembly (`create_app`).
    ctx = HarnessContext(
        settings=settings, engine=engine, vault=vault, lifecycle=lifecycle, services=container
    )
    for manifest in app.state.feature_manifests:
        if manifest.enabled is not None and not manifest.enabled(settings):
            continue
        if manifest.build is None:
            continue
        runtime = await manifest.build(ctx)
        for service in runtime.services:
            container.add(service)
        for name, value in runtime.state.items():
            setattr(app.state, name, value)
        for sync_hook in runtime.run_terminal_sync:
            run_terminal.add_sync(sync_hook)
        for hook in runtime.run_terminal:
            run_terminal.add(hook)
    try:
        yield
    finally:
        await lifecycle.stop_all()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Odysseus", version=settings.version, lifespan=lifespan)
    app.state.settings = settings  # the lifespan reads this (tests inject it)
    # Discovered once per app: routers register below (before the lifespan runs);
    # the lifespan runs each enabled manifest's build in the same order.
    app.state.feature_manifests = discover_manifests()

    # The auth gate runs inside CORS (added first ⇒ inner), so CORS can answer
    # preflight and decorate even a 401 with the right headers.
    app.add_middleware(AuthMiddleware)

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
    app.include_router(notifications.router)
    # Reserved sprint surfaces — registered here up front so the parallel feature
    # tracks each fill in only their own `routes/` module and never contend for this
    # block. Each is an empty router until its track lands.
    app.include_router(mail.router)
    app.include_router(calendar.router)
    app.include_router(mcp.router)
    app.include_router(integrations.router)
    app.include_router(secret_vault.router)
    app.include_router(backup.router)
    app.include_router(tokens.router)
    # `shell_enabled` is the on/off switch (`core/config.py`): disabled ⇒ the
    # router is never registered at all, so `/shell/host-mode` and `/shell/ws`
    # are simply 404 — the natural kill-switch.
    if settings.shell_enabled:
        app.include_router(shell.router)
    for manifest in app.state.feature_manifests:
        if manifest.enabled is not None and not manifest.enabled(settings):
            continue
        for router in manifest.routers:
            app.include_router(router)
    return app


app = create_app()
