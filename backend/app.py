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
from routes import (
    api_tokens,
    artifacts,
    auth,
    chat,
    conversations,
    cookbook,
    corpus,
    documents,
    health,
    memory,
    models,
    overview,
    previews,
    runs,
    search,
    uploads,
)
from routes.deps import OPERATOR_ID
from runs import RunRegistry
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
from services.memory import MemoryStore
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.sandbox import SandboxSessionManager, detect_sandbox
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.upload_extraction import BasicExtractor, FallbackExtractor, UploadExtractor
from services.upload_mineru import MinerUExtractor
from services.uploads import UploadStore
from services.webfetch import BrowserFetcher, ManagedBrowser

logger = logging.getLogger(__name__)


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
    app.state.runs = RunRegistry(
        max_concurrency=settings.run_max_concurrency,
        wall_clock_timeout_s=settings.run_wall_clock_timeout_s,
        inactivity_timeout_s=settings.run_inactivity_timeout_s,
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
    # Published previews — the agent captures a sandbox file here, the frontend
    # fetches and renders it. Encrypted at rest like the rest of the operator's data.
    app.state.artifacts = ArtifactStore(engine, vault)
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
    await searxng.start()
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
        timeout_s=settings.web_fetch_timeout_s,
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
    await browser.start()
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
    )
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
    try:
        yield
    finally:
        warmup = app.state.cookbook_warmup
        if not warmup.done():
            warmup.cancel()
        backfill = app.state.embedding_backfill
        if not backfill.done():
            backfill.cancel()
        app.state.embedding_reindexer.shutdown()
        await preview_client.aclose()
        await discovery_client.aclose()
        await web_client.aclose()
        await browser.stop()
        await searxng.stop()
        if sandbox_manager is not None:
            await sandbox_manager.stop()
        await folder_adapter.stop()
        await documents_adapter.stop()
        await uploads_adapter.stop()
        await app.state.uploads.stop()
        await app.state.conversations.stop()


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
    app.include_router(memory.router)
    app.include_router(documents.router)
    app.include_router(uploads.router)
    app.include_router(corpus.router)
    app.include_router(artifacts.router)
    app.include_router(previews.router)
    app.include_router(search.router)
    app.include_router(api_tokens.router)
    return app


app = create_app()
