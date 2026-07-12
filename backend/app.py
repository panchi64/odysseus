"""FastAPI application assembly — the slim orchestrator.

Build the app, install middleware, wire auth, register routers, and hang shared
singletons (the run registry, capability handles) on ``app.state``. Business
logic lives below this layer; this file delegates. Pydantic AI is the engine,
this is the chassis — see ``docs/architecture/README.md``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.vision import VisionTranscriber
from core.auth import AuthManager, AuthMiddleware
from core.config import Settings, get_settings
from core.db import init_db, make_engine
from core.ratelimit import RateLimiter
from core.vault import Vault
from models.task import TaskOutcome, TaskOutput
from prompts.utility import DISTILL_INSTRUCTIONS
from routes import (
    api_tokens,
    auth,
    chat,
    conversations,
    cookbook,
    corpus,
    documents,
    gallery,
    health,
    memory,
    models,
    notifications,
    offline,
    overview,
    previews,
    research,
    runs,
    search,
    serving,
    tasks,
    uploads,
    views,
)
from routes.chat import compose_turn, resolve_turn_models
from routes.deps import OPERATOR_ID
from runs import Run, RunRegistry, RunStatus
from services.approval_grants import ApprovalGrantStore
from services.artifacts import ArtifactStore
from services.conversation_search import ConversationSearch
from services.conversations import ConversationStore
from services.cookbook import CookbookService
from services.corpus import (
    ConversationAdapter,
    CorpusChunkStore,
    CorpusIndex,
    FolderAdapter,
    MemoryAdapter,
    default_surface_stubs,
)
from services.corpus.documents import DocumentsAdapter
from services.corpus.uploads import UploadsAdapter
from services.credential_store import CredentialStore
from services.documents import DocumentStore
from services.embeddings import RegistryEmbedder
from services.gallery import GalleryService
from services.memory import MemoryStore
from services.notifications import NotificationService
from services.offline import OfflineModeService
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.sandbox import SandboxSessionManager, detect_sandbox
from services.scheduler import ScheduledTaskView, SchedulerService, TaskRunResult
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.serving import ServingPaths, ServingService
from services.settings_store import SettingsStore
from services.upload_extraction import BasicExtractor, FallbackExtractor, UploadExtractor
from services.upload_mineru import MinerUExtractor
from services.uploads import UploadStore
from services.webfetch import BrowserFetcher, ManagedBrowser, WebDistiller
from services.workspace_history import WorkspaceHistoryStore
from tools import Capabilities

logger = logging.getLogger(__name__)

# A scheduled task's outcome summary is a short factual line, not a transcript —
# just enough for the operator to judge at a glance whether to open the conversation.
_TASK_SUMMARY_MAX_CHARS = 280

# `TaskRun.outcome` from the Run status it settled at — the three failure-shaped
# statuses map onto the matching `TaskOutcome` verbatim; `cancelled` covers both an
# operator-cancelled run and one still parked (never approved/denied) at shutdown.
_TASK_OUTCOME_BY_RUN_STATUS = {
    RunStatus.done: TaskOutcome.OK.value,
    RunStatus.error: TaskOutcome.ERROR.value,
    RunStatus.blocked: TaskOutcome.BLOCKED.value,
    RunStatus.cancelled: TaskOutcome.CANCELLED.value,
}


def _build_upload_extractor(
    registry: ModelRegistry, settings: Settings
) -> UploadExtractor:
    """Pick the upload extraction engine. The built-in (pypdfium2 text + vision OCR) is
    always available; when MinerU is pinned or detected on the host it goes in front,
    with the built-in as the fallback so a missing/broken/out-of-resources MinerU
    degrades to a working extraction instead of an error. The original bytes are kept
    sealed regardless, so a built-in extraction can be re-run through MinerU later."""
    basic = BasicExtractor(
        VisionTranscriber(registry, timeout_s=settings.upload_ocr_timeout_s),
        max_pages=settings.upload_extract_max_pages,
    )
    if settings.upload_extractor == "basic":
        return basic
    if settings.upload_extractor == "mineru" or MinerUExtractor.is_available():
        logger.info("uploads: MinerU extraction enabled (high-fidelity, degrades to built-in)")
        return FallbackExtractor(
            MinerUExtractor(timeout_s=settings.upload_mineru_timeout_s), basic
        )
    logger.info("uploads: built-in extraction (MinerU not detected on host)")
    return basic


async def _backfill_embeddings(
    conversations: ConversationStore,
    memory: MemoryStore,
    chunk_store: CorpusChunkStore,
    vault: Vault,
) -> None:
    """Best-effort: once the vault is unlocked, embed any conversation messages,
    memories, AND corpus chunks that have no vector yet (e.g. persisted before an
    embedding endpoint existed) so semantic recall covers the backlog, not just new
    content. Runs in the background, waits for unlock so it never touches sealed data,
    and degrades to a no-op when no embedder is configured. Every store is lifted
    symmetrically."""
    await vault.unlocked_event.wait()
    try:
        count = await conversations.backfill_embeddings(OPERATOR_ID)
        if count:
            logger.info("conversation search: backfilled %d message embeddings", count)
    except Exception:
        logger.exception("conversation search: embedding backfill failed")
    try:
        count = await memory.reembed(OPERATOR_ID)
        if count:
            logger.info("memory: backfilled %d memory embeddings", count)
    except Exception:
        logger.exception("memory: embedding backfill failed")
    try:
        count = await chunk_store.reembed(OPERATOR_ID)
        if count:
            logger.info("corpus: backfilled %d chunk embeddings", count)
    except Exception:
        logger.exception("corpus: embedding backfill failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Process-lifetime startup/shutdown.

    Brings up the run registry and the persistence store (DB engine + schema +
    write-behind drainer). Shutdown flushes pending writes. Capability handles
    (``services/``) wire in here as they land.
    """
    settings: Settings = app.state.settings
    app.state.auth_manager = AuthManager()

    # Tracks each terminal-transition notify task while it's in flight — lets shutdown
    # drain them cleanly (rather than tearing down the DB engine/vault out from under
    # one) and lets a test await "every pending notify has settled" deterministically.
    app.state.run_terminal_tasks: set[asyncio.Task[None]] = set()

    # Keyed by run id — the scheduler's agent-task executor (below) awaits one of
    # these futures to learn when its Run reaches a genuinely terminal state, which
    # may be long after an approval park + operator resume round-trip (`AE-3.2`/
    # `AE-3.5`). Resolved synchronously inside `_on_run_terminal`, the same one-shot
    # hook the attention surface's own notify composes over — so a task execution's
    # eventual settle is observed the same way anything else observes a run's
    # outcome, with no separate polling loop.
    app.state.task_run_waiters: dict[str, asyncio.Future[Run]] = {}

    # Same shape as the above, kept separate: `routes/research.py`'s `start` route
    # registers one of these per research Run it submits, and its own background
    # finalize task awaits it to learn the outcome to persist (report/stats/status) —
    # independent bookkeeping from the scheduler's so the two features never collide
    # on a run id.
    app.state.research_run_waiters: dict[str, asyncio.Future[Run]] = {}

    def _on_run_terminal(run: Run) -> None:
        """The registry's injected terminal-transition hook — composes the attention
        surface's emit policy over the run substrate without `runs/` importing
        `services/` (it only knows it holds an optional callback). The subscriber
        count is captured *here*, synchronously, before the registry closes the
        stream (see `RunStream.subscriber_count`'s docstring for why reading it later,
        from the scheduled task below, would race the stream's own subscriber
        cleanup). `app.state.notifications`/`app.state.conversations` are read lazily
        inside the scheduled task, not here — a run can't reach terminal before both
        exist, so the forward reference is safe despite the registry being built
        before either singleton below."""
        waiter = app.state.task_run_waiters.pop(run.id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(run)
        research_waiter = app.state.research_run_waiters.pop(run.id, None)
        if research_waiter is not None and not research_waiter.done():
            research_waiter.set_result(run)
        watched = run.stream.subscriber_count > 0
        task = asyncio.create_task(_notify_run_terminal(run, watched=watched))
        app.state.run_terminal_tasks.add(task)
        task.add_done_callback(app.state.run_terminal_tasks.discard)

    async def _notify_run_terminal(run: Run, *, watched: bool) -> None:
        notifications = app.state.notifications
        try:
            # Always resolve first: a cancel-while-parked never reaches the approve
            # route, and even a normal completion may still carry a dangling
            # approval_needed if the operator never decided it — this is the backstop.
            await notifications.resolve_for_run(OPERATOR_ID, run.id)
        except Exception:
            logger.exception("notifications: failed to resolve run %s at terminal", run.id)
        # Research runs are conversation-less (no thread to deep-link to) but are their
        # own noteworthy surface: unlike a chat turn, finishing is worth a notification
        # even if the operator's tab was open and watching the live progress the whole
        # time (they may well have navigated away for the several minutes a run takes).
        # Cancelled stays silent (the operator asked for it); blocked never happens here
        # (the pipeline never calls `run.block()`) but would fall through to silence too.
        if run.kind == "research":
            if run.status not in (RunStatus.done, RunStatus.error):
                return
            try:
                research_row = await research.find_by_run(app.state.db_engine, run.id)
            except Exception:
                logger.exception(
                    "notifications: failed to resolve research run %s at terminal", run.id
                )
                return
            if research_row is None:
                return
            question = app.state.vault.decrypt_str(research_row.question_enc)
            title = question if len(question) <= 80 else question[:79] + "…"
            if run.status is RunStatus.error:
                await notifications.notify(
                    OPERATOR_ID,
                    "run_failed",
                    f'Research on "{title}" failed',
                    body=run.error,
                    run_id=run.id,
                    research_id=research_row.id,
                )
            else:
                await notifications.notify(
                    OPERATOR_ID,
                    "run_completed",
                    f'Research on "{title}" is ready',
                    run_id=run.id,
                    research_id=research_row.id,
                )
            return
        # Only conversation-linked runs notify (a stateless/detached run has no thread
        # to deep-link to); cancelled and blocked outcomes stay silent — the operator
        # asked for the cancel, and a bound/limit stop isn't a noteworthy failure.
        if run.conversation_id is None or run.status in (RunStatus.cancelled, RunStatus.blocked):
            return
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

    app.state.runs = RunRegistry(
        max_concurrency=settings.run_max_concurrency,
        wall_clock_timeout_s=settings.run_wall_clock_timeout_s,
        inactivity_timeout_s=settings.run_inactivity_timeout_s,
        on_terminal=_on_run_terminal,
    )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    url = settings.db_url or f"sqlite:///{settings.data_dir / 'app.db'}"
    engine = make_engine(url)
    init_db(engine)
    app.state.db_engine = engine

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
    await app.state.conversations.start()
    # Cross-chat search — hybrid recall over the operator's other conversations plus
    # a transcript read, reusing the store's active-path projection.
    app.state.conversation_search = ConversationSearch(
        engine, vault, embedder, app.state.conversations
    )
    # Outbound service credentials — the operator's API keys for third-party services,
    # sealed with the vault.
    app.state.credentials = CredentialStore(engine, vault)
    # The attention surface — a durable notification record + its own live stream,
    # separate from the frozen per-run event stream. Just the substrate here (record +
    # stream); the emit policy (which run outcomes are noteworthy) wires in where those
    # events happen (approval parking, run terminal transitions, approve/deny routes).
    app.state.notifications = NotificationService(engine, vault)
    await app.state.notifications.start()
    # The Cookbook — host hardware detection. The probe is warmed in the background so a
    # slow `system_profiler` never blocks boot; the first request falls back to
    # lazy-detect if the warm-up hasn't finished.
    app.state.cookbook = CookbookService()
    logger.info("cookbook: hardware detection (warming in background)")
    app.state.cookbook_warmup = asyncio.create_task(app.state.cookbook.warmup())
    # Long-term memory — embeds via the shared embedder; degrades to keyword recall
    # when no embedding endpoint is configured.
    app.state.memory = MemoryStore(engine, vault, embedder)
    # The knowledge corpus — one retrieval index fed by many source adapters. The
    # rich stores (memory, cross-chat search) plug in untouched; chunked content
    # (folders now) lands in the generic chunk store. The folder adapter's indexer is
    # lock-aware (parks while the vault is locked). Surfaces not yet built enroll as
    # stub adapters so the /rag list shows every planned source from day one. Built
    # before the reindexer so the corpus shares the EMB-2 heal path below.
    chunk_store = CorpusChunkStore(engine, vault, embedder)
    app.state.corpus_chunk_store = chunk_store
    # Heals semantic recall after the operator changes the embedding model: EMB-2
    # segregates vectors by model, so a swap strands every existing vector until it's
    # re-embedded. This coordinator runs that reindex in the background (memory, the
    # cross-chat index, and the corpus chunk store) and exposes its progress.
    app.state.embedding_reindexer = EmbeddingReindexer(
        registry, app.state.memory, app.state.conversations, chunk_store
    )
    # Local model serving — download a HuggingFace model and supervise an inference
    # engine (llama.cpp universal baseline; MLX on Apple Silicon) as a subprocess that
    # registers as a 127.0.0.1 endpoint. Binding a freshly-served embedding model heals
    # the corpus via the reindexer (built just above). Engines from a prior process can't
    # be adopted across a restart, so reconcile clean-slates any mid-flight rows
    # (best-effort, never blocks startup); shutdown stops them gracefully in `finally`.
    app.state.settings_store = SettingsStore(engine)
    app.state.approval_grants = ApprovalGrantStore(engine, settings.approval_grant_ttl_s)
    app.state.serving = ServingService(
        engine,
        vault,
        registry,
        app.state.cookbook,
        ServingPaths(settings.data_dir),
        reindexer=app.state.embedding_reindexer,
        settings=app.state.settings_store,
        credentials=app.state.credentials,
    )
    await app.state.serving.reconcile_on_startup()
    folder_adapter = FolderAdapter(engine, chunk_store, vault.unlocked_event)
    # The documents surface: an in-app source whose bodies are chunked into the same
    # corpus_chunk store as folders. The DocumentStore owns the rows and calls the
    # adapter to (re)index after each write; the adapter owns chunking/sealing/embedding
    # on its own lock-aware worker.
    documents_adapter = DocumentsAdapter(engine, chunk_store, vault.unlocked_event)
    app.state.documents = DocumentStore(engine, vault, documents_adapter)
    # The uploads surface: a file's bytes are stored sealed; its extracted text (native
    # PDF text + vision OCR for scanned pages) is chunked into the same corpus_chunk
    # store. The UploadStore owns the rows and drains extraction off the request path on
    # its own lock-aware worker; the adapter indexes the extracted text after each run.
    # Vision OCR runs a model, so it lives in the engine layer (VisionTranscriber) and is
    # injected into the services-layer extractor through a narrow seam.
    uploads_adapter = UploadsAdapter(engine, chunk_store, vault.unlocked_event)
    upload_extractor = _build_upload_extractor(registry, settings)
    app.state.uploads = UploadStore(engine, vault, uploads_adapter, upload_extractor)
    app.state.upload_rate_limiter = RateLimiter(
        rate_per_second=settings.upload_rate_per_minute / 60.0,
        burst=settings.upload_rate_burst,
    )
    # The gallery — a presentation lens over the image uploads plus the operator's custom
    # albums. Owns no image bytes: it reads the uploads store (for the images) and the
    # conversation store (for chat-vs-imported provenance), and curates albums of its own.
    app.state.gallery = GalleryService(
        engine, vault, app.state.conversations, app.state.uploads
    )
    corpus_index = CorpusIndex(embedder, registry, chunk_store, folder_adapter)
    corpus_index.register(folder_adapter)
    corpus_index.register(MemoryAdapter(app.state.memory))
    corpus_index.register(ConversationAdapter(app.state.conversation_search))
    corpus_index.register(documents_adapter)
    corpus_index.register(uploads_adapter)
    for stub in default_surface_stubs():
        corpus_index.register(stub)
    app.state.corpus = corpus_index
    app.state.corpus_folder = folder_adapter
    app.state.corpus_documents = documents_adapter
    app.state.corpus_uploads = uploads_adapter
    await folder_adapter.start()
    await documents_adapter.start()
    await uploads_adapter.start()
    await app.state.uploads.start()
    # Lift any pre-existing backlog (messages + memories + corpus chunks) into the
    # semantic index once unlocked — off the critical path; new content is already
    # embedded as it persists.
    app.state.embedding_backfill = asyncio.create_task(
        _backfill_embeddings(app.state.conversations, app.state.memory, chunk_store, vault)
    )
    # The View's static versions — the agent captures a sandbox file here, the
    # frontend fetches and renders it on the View canvas. Encrypted at rest like the
    # rest of the operator's data. (The View's live head rides the sandbox + the
    # /previews proxy; this store is the snapshot/version history.)
    app.state.artifacts = ArtifactStore(engine, vault)
    # The View's git-style history — after a file-changing turn the sandbox
    # workspace is captured as a content-addressed, encrypted snapshot; the frontend
    # browses each version's code and diffs it against the previous one.
    app.state.workspace_history = WorkspaceHistoryStore(engine, vault)
    # Managed web search — the backend runs its own SearXNG (same container runtime
    # as the sandbox) so search works with zero operator setup. Bring-up is
    # best-effort in the background; until it's ready (or if no runtime exists) the
    # search service degrades. An operator-configured provider overrides it.
    searxng = ManagedSearxng(
        enabled=settings.searxng_enabled,
        image=settings.searxng_image,
        data_dir=settings.data_dir,
        startup_timeout_s=settings.searxng_startup_timeout_s,
        external_base_url=settings.searxng_base_url,
        runtime_pref=settings.sandbox_runtime,
    )
    app.state.searxng = searxng
    # The container is not started here: the offline-mode service (built below, once
    # the browser exists too) owns bringing both web containers up — probe-first, so a
    # host that boots offline never launches them.
    # Web search — query the managed SearXNG (or an operator-configured provider). Its own
    # outbound client does NOT follow redirects: an unguarded redirect off the JSON API
    # would be an SSRF hole, so the search path simply refuses to follow one.
    web_client = httpx.AsyncClient(follow_redirects=False)
    app.state.web_client = web_client
    app.state.search = SearchService(
        engine,
        vault,
        http_client=web_client,
        managed_url=lambda: searxng.base_url,
        timeout_s=settings.web_search_timeout_s,
        result_limit=settings.web_search_result_limit,
    )
    # Web fetch — a containerized headless Chromium (same runtime as the sandbox/SearXNG)
    # + the render-and-extract fetcher. The open web is treated as always-dynamic, so every
    # fetch loads the page in the browser (its JS runs) and extracts the rendered DOM to
    # Markdown. Bring-up is best-effort in the background: no runtime / a failed pull leaves
    # the browser unavailable and web fetch degrades, like managed search.
    browser = ManagedBrowser(
        enabled=settings.web_fetch_enabled,
        image=settings.web_fetch_image,
        startup_timeout_s=settings.web_fetch_startup_timeout_s,
        concurrency=settings.web_fetch_concurrency,
        user_agent=settings.web_fetch_user_agent,
        locale=settings.web_fetch_locale,
        timezone_id=settings.web_fetch_timezone,
        cookie_ttl_s=settings.web_fetch_cookie_ttl_s,
        cookie_max=settings.web_fetch_cookie_max,
        proxy_image=settings.web_fetch_proxy_image,
        runtime_pref=settings.sandbox_runtime,
    )
    app.state.browser = browser
    # Goal-aware distillation of oversized pages: a closure resolves the utility model
    # (the background-work rule — utility, degrade to main, reasoning off) fresh per call,
    # so it respects registry changes and keeps the engine layer out of services/webfetch.
    distiller: WebDistiller | None = None
    if settings.web_fetch_distill_enabled:

        async def _resolve_distill_model():
            resolved = await registry.resolve_background(owner_id=OPERATOR_ID)
            return resolved.model, resolved.reasoning_off

        distiller = WebDistiller(
            resolve_model=_resolve_distill_model,
            instructions=DISTILL_INSTRUCTIONS,
            window_tokens=settings.web_fetch_distill_window_tokens,
            max_windows=settings.web_fetch_distill_max_windows,
            timeout_s=settings.web_fetch_distill_timeout_s,
        )
    # Like SearXNG above, the browser is started by the offline-mode service, not here.
    app.state.fetcher = BrowserFetcher(
        browser=browser,
        timeout_s=settings.web_fetch_timeout_s,
        wait_until=settings.web_fetch_wait_until,
        render_wait_ms=settings.web_fetch_render_wait_ms,
        max_bytes=settings.web_fetch_max_bytes,
        min_chars=settings.web_fetch_min_chars,
        min_interval_s=settings.web_fetch_min_interval_s,
        challenge_waits=settings.web_fetch_challenge_waits,
        challenge_wait_ms=settings.web_fetch_challenge_wait_ms,
        output_max_tokens=settings.web_fetch_output_max_tokens,
        pdf_max_bytes=settings.web_fetch_pdf_max_bytes,
        pdf_max_pages=settings.web_fetch_pdf_max_pages,
        http_client=web_client,
        settle_checks=settings.web_fetch_settle_checks,
        settle_wait_ms=settings.web_fetch_settle_wait_ms,
        settle_min_chars=settings.web_fetch_settle_min_chars,
        distiller=distiller,
    )
    # Offline mode — owns both web containers' lifecycle. Probe-first at boot: it runs
    # one connectivity check and only brings SearXNG + the browser up if the host is
    # online (a host that boots offline never spins up the heavy browser), then watches
    # the link and suspends/resumes them as connectivity comes and goes. The operator
    # can also force offline manually; both switches persist via the settings store.
    async def _assume_online() -> bool:
        return True

    app.state.offline = OfflineModeService(
        searxng=searxng,
        browser=browser,
        settings_store=app.state.settings_store,
        owner_id=OPERATOR_ID,
        anchors=settings.offline_anchors,
        interval_s=settings.offline_check_interval_s,
        timeout_s=settings.offline_check_timeout_s,
        fail_threshold=settings.offline_fail_threshold,
        recover_threshold=settings.offline_recover_threshold,
        auto_default=settings.offline_auto_default,
        # Probing off ⇒ assume online (no network); only the manual switch acts.
        probe=None if settings.offline_check_enabled else _assume_online,
    )
    await app.state.offline.start()
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
        await sandbox_manager.start()
    else:
        logger.info("sandbox: code execution disabled (no container runtime)")
        logger.info("preview: disabled (no container runtime)")
    # Reused by the preview reverse proxy to forward HTTP to a sandbox server. No
    # redirect following — the proxy rewrites Location and returns it to the browser.
    preview_client = httpx.AsyncClient(follow_redirects=False)
    app.state.preview_client = preview_client

    async def _task_run_summary(run: Run, conversation_id: str) -> str | None:
        """A short, plain factual line about how the run settled — no extra model
        call. An error/blocked/cancelled run already carries its own operator-legible
        reason; a `done` run's summary is the start of its final answer."""
        if run.status is RunStatus.error:
            return run.error
        if run.status is RunStatus.blocked:
            return run.detail
        if run.status is RunStatus.cancelled:
            return run.detail or "cancelled"
        if run.status is RunStatus.done:
            turns = await app.state.conversations.messages_view(conversation_id)
            for turn in reversed(turns):
                if turn.role == "assistant" and turn.content:
                    return turn.content[:_TASK_SUMMARY_MAX_CHARS]
            return None
        return None

    async def _task_executor(view: ScheduledTaskView) -> TaskRunResult:
        """An agent task's fire — an ordinary Run in a fresh conversation (titled from
        the task), seeded with the task's own pre-authorization as a conversation
        grant (`AE-3.5`) so its unattended sensitive actions within that scope don't
        pause; anything outside it still parks + notifies exactly like an
        interactive run. Reuses `routes.chat`'s own turn composition
        (`resolve_turn_models`/`compose_turn`) so a task's run is submitted through
        the identical path a live chat turn is — no forked run-submission logic."""
        conversations = app.state.conversations
        models = await resolve_turn_models(
            app.state.models, None, None, owner_id=view.owner_id
        )
        conversation_id = await conversations.create_conversation(
            view.owner_id, title=view.title
        )
        for tool_name in view.pre_authorized:
            await app.state.approval_grants.grant(view.owner_id, conversation_id, tool_name)

        waiter: asyncio.Future[Run] = asyncio.get_running_loop().create_future()
        created = compose_turn(
            prompt=view.prompt,
            conversation_id=conversation_id,
            models=models,
            capabilities=Capabilities(
                memory=app.state.memory,
                sandbox_sessions=app.state.sandbox,
                artifacts=app.state.artifacts,
                search=app.state.search,
                fetcher=app.state.fetcher,
                conversation_search=app.state.conversation_search,
                corpus=app.state.corpus,
                uploads=app.state.uploads,
                grants=app.state.approval_grants,
                workspace_history=app.state.workspace_history,
                documents=app.state.documents,
                notifications=app.state.notifications,
            ),
            registry=app.state.runs,
            store=conversations,
            uploads=app.state.uploads,
            disabled_tools=app.state.offline.web_tools_disabled(),
            owner_id=view.owner_id,
        )
        # Registered before the very first `await` below — the newly submitted Run's
        # task hasn't had a chance to run yet (`RunRegistry.submit` only schedules
        # it), so there is no window for it to reach terminal and fire
        # `_on_run_terminal` before this waiter exists.
        app.state.task_run_waiters[created.run_id] = waiter
        run = await waiter

        outcome = _TASK_OUTCOME_BY_RUN_STATUS.get(run.status, TaskOutcome.ERROR.value)
        summary = await _task_run_summary(run, conversation_id)
        if view.output == TaskOutput.NOTIFICATION.value:
            await app.state.notifications.notify(
                view.owner_id,
                "task_outcome",
                view.title,
                body=summary,
                conversation_id=conversation_id,
                task_id=view.id,
            )
        return TaskRunResult(
            outcome=outcome,
            run_id=run.id,
            conversation_id=conversation_id,
            summary=summary,
        )

    async def _task_notify(view: ScheduledTaskView) -> None:
        """A reminder task's fire — its prompt delivered verbatim as the notification
        body (no AI phrasing in v1); title = the task's own title."""
        await app.state.notifications.notify(
            view.owner_id,
            "reminder",
            view.title,
            body=view.prompt,
            task_id=view.id,
        )

    # The task scheduler — single-instance, in-process. Lock-aware like the
    # write-behind drainers above (task prompts are encrypted): it parks its tick
    # loop while the vault is locked and resumes on unlock.
    app.state.scheduler = SchedulerService(
        engine,
        vault,
        executor=_task_executor,
        notify=_task_notify,
    )
    await app.state.scheduler.start()
    try:
        yield
    finally:
        await app.state.scheduler.stop()
        warmup = app.state.cookbook_warmup
        if not warmup.done():
            warmup.cancel()
        backfill = app.state.embedding_backfill
        if not backfill.done():
            backfill.cancel()
        # Drain any in-flight run-terminal notify tasks before tearing down the DB
        # engine/vault they read — a run finishing right at shutdown must not leave a
        # task reading a closed engine, and must not warn as "destroyed while pending".
        pending_notifies = list(app.state.run_terminal_tasks)
        for task in pending_notifies:
            task.cancel()
        if pending_notifies:
            await asyncio.gather(*pending_notifies, return_exceptions=True)
        app.state.embedding_reindexer.shutdown()
        await app.state.serving.shutdown()
        await preview_client.aclose()
        await discovery_client.aclose()
        await web_client.aclose()
        await app.state.offline.stop()  # stop the monitor before tearing the containers down
        await browser.stop()
        await searxng.stop()
        if sandbox_manager is not None:
            await sandbox_manager.stop()
        await folder_adapter.stop()
        await documents_adapter.stop()
        await uploads_adapter.stop()
        await app.state.uploads.stop()
        await app.state.conversations.stop()
        await app.state.notifications.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Odysseus", version=settings.version, lifespan=lifespan)
    app.state.settings = settings  # the lifespan reads this (tests inject it)

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
    app.include_router(cookbook.router)
    app.include_router(serving.router)
    app.include_router(memory.router)
    app.include_router(documents.router)
    app.include_router(uploads.router)
    app.include_router(gallery.router)
    app.include_router(corpus.router)
    app.include_router(views.router)
    app.include_router(previews.router)
    app.include_router(search.router)
    app.include_router(api_tokens.router)
    app.include_router(offline.router)
    app.include_router(notifications.router)
    app.include_router(tasks.router)
    app.include_router(research.router)
    return app


app = create_app()
