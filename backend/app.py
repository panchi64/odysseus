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

from core.auth import AuthManager, AuthMiddleware
from core.config import Settings, get_settings
from core.db import init_db, make_engine
from core.vault import Vault
from routes import (
    api_tokens,
    artifacts,
    auth,
    chat,
    conversations,
    cookbook,
    corpus,
    health,
    memory,
    models,
    overview,
    previews,
    runs,
    search,
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
from services.credential_store import CredentialStore
from services.embeddings import RegistryEmbedder
from services.memory import MemoryStore
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.sandbox import SandboxSessionManager, detect_sandbox
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.settings_store import SettingsStore

logger = logging.getLogger(__name__)


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
    # Outbound service credentials — the operator's API keys for third-party services
    # (the Cookbook's quality benchmarks + its HuggingFace token), sealed with the vault.
    app.state.credentials = CredentialStore(engine, vault)
    # Small persisted operator preferences (e.g. the Cookbook's active quality source).
    app.state.settings_store = SettingsStore(engine)
    # The Cookbook — host hardware detection + a live, cached model catalog (HuggingFace
    # specs + OpenRouter capability flags). Reuses the redirect-following discovery client
    # for its outbound calls. Hardware + catalog are warmed in the background so a slow
    # `system_profiler` or the first catalog pull never blocks boot; first request falls
    # back to lazy-detect if the warm-up hasn't finished. Quality-source keys resolve from
    # the credential store at build time (env as fallback).
    app.state.cookbook = CookbookService(
        discovery_client,
        credentials=app.state.credentials,
        settings=app.state.settings_store,
        owner_id=OPERATOR_ID,
        hf_token=settings.hf_token,
        catalog_ttl_s=settings.cookbook_catalog_ttl_s,
        catalog_list_limit=settings.cookbook_catalog_list_limit,
        catalog_max_models=settings.cookbook_catalog_max_models,
        quality_source=settings.cookbook_quality_source,
        aa_api_key=settings.artificial_analysis_api_key,
        llm_stats_api_key=settings.llm_stats_api_key,
    )
    # A credential change rebuilds the catalog on next request, so a newly-pasted key
    # applies without a restart.
    app.state.credentials.on_change(app.state.cookbook.invalidate_catalog)
    logger.info("cookbook: hardware + model catalog (warming in background)")
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
    corpus_index = CorpusIndex(embedder, registry, chunk_store, folder_adapter)
    corpus_index.register(folder_adapter)
    corpus_index.register(MemoryAdapter(app.state.memory))
    corpus_index.register(ConversationAdapter(app.state.conversation_search))
    for stub in default_surface_stubs():
        corpus_index.register(stub)
    app.state.corpus = corpus_index
    app.state.corpus_folder = folder_adapter
    await folder_adapter.start()
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
    # The web capability — search via the managed SearXNG (or an operator-configured
    # provider) + a guarded direct fetch. Its own outbound client does NOT follow
    # redirects: fetch follows them by hand so it can re-run the SSRF guard on every hop.
    web_client = httpx.AsyncClient(follow_redirects=False)
    app.state.web_client = web_client
    app.state.search = SearchService(
        engine,
        vault,
        http_client=web_client,
        managed_url=lambda: searxng.base_url,
        timeout_s=settings.web_fetch_timeout_s,
        max_bytes=settings.web_fetch_max_bytes,
        max_redirects=settings.web_fetch_max_redirects,
        result_limit=settings.web_search_result_limit,
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
        await searxng.stop()
        if sandbox_manager is not None:
            await sandbox_manager.stop()
        await folder_adapter.stop()
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
    app.include_router(corpus.router)
    app.include_router(artifacts.router)
    app.include_router(previews.router)
    app.include_router(search.router)
    app.include_router(api_tokens.router)
    return app


app = create_app()
