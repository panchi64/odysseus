"""Local model serving + the Cookbook + embedding-space healing.

Serving downloads a HuggingFace model and supervises an inference engine
(llama.cpp universal baseline; MLX on Apple Silicon) as a subprocess that registers
as a loopback endpoint — local models flow through the same registry resolve path
as external ones. The Cookbook is host hardware detection feeding its
recommendations. The reindexer + backfill heal semantic recall when the embedding
model changes or content predates one (`EMB-2`) — they live beside serving because
binding a freshly served embedding model is what most often triggers the heal.
"""

from __future__ import annotations

import logging

from core.vault import Vault
from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import cookbook as cookbook_routes
from routes import serving as serving_routes
from routes.deps import OPERATOR_ID
from services.conversations import ConversationStore
from services.cookbook import CookbookService
from services.corpus import CorpusChunkStore
from services.credential_store import CredentialStore
from services.memory import MemoryStore
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.serving import ServingPaths, ServingService
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
    content. Runs in the background, waits for unlock so it never touches sealed
    data, and degrades to a no-op when no embedder is configured. Every store is
    lifted symmetrically."""
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


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    registry = ctx.services.get(ModelRegistry)
    conversations = ctx.services.get(ConversationStore)
    memory = ctx.services.get(MemoryStore)
    chunk_store = ctx.services.get(CorpusChunkStore)
    # The Cookbook — host hardware detection. The probe is warmed in the background
    # so a slow `system_profiler` never blocks boot; the first request falls back to
    # lazy-detect if the warm-up hasn't finished.
    cookbook = CookbookService()
    logger.info("cookbook: hardware detection (warming in background)")
    ctx.lifecycle.track("cookbook-warmup", cookbook.warmup())
    # Heals semantic recall after the operator changes the embedding model: EMB-2
    # segregates vectors by model, so a swap strands every existing vector until
    # it's re-embedded. Runs the reindex in the background and exposes progress.
    reindexer = EmbeddingReindexer(registry, memory, conversations, chunk_store)
    # Engines from a prior process can't be adopted across a restart, so reconcile
    # clean-slates any mid-flight rows (best-effort, never blocks startup);
    # shutdown stops them gracefully.
    serving = ServingService(
        ctx.engine,
        ctx.vault,
        registry,
        cookbook,
        ServingPaths(ctx.settings.data_dir),
        reindexer=reindexer,
        settings=ctx.services.get(SettingsStore),
        credentials=ctx.services.get(CredentialStore),
    )
    await ctx.lifecycle.start(
        "serving", start=serving.reconcile_on_startup, stop=serving.shutdown
    )
    # Registered after serving so it stops first: an engine going down during
    # shutdown must not be able to kick off a doomed reindex.
    ctx.lifecycle.on_stop("embedding-reindexer", reindexer.shutdown)
    # Lift any pre-existing backlog (messages + memories + corpus chunks) into the
    # semantic index once unlocked — off the critical path; new content is already
    # embedded as it persists.
    ctx.lifecycle.track(
        "embedding-backfill",
        _backfill_embeddings(conversations, memory, chunk_store, ctx.vault),
    )
    return FeatureRuntime(
        services=(cookbook, reindexer, serving),
        state={
            "cookbook": cookbook,
            "embedding_reindexer": reindexer,
            "serving": serving,
        },
    )


MANIFEST = FeatureManifest(
    name="serving",
    after=("corpus", "memory"),
    routers=(serving_routes.router, cookbook_routes.router),
    build=_build,
)
