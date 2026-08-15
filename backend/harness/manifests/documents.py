"""The document library (`DOC-*`) — CRUD + versioning over a sealed store, indexed
into the corpus.

The store owns the rows and calls the adapter to (re)index after each write; the
adapter owns chunking/sealing/embedding on its own lock-aware worker.
"""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import documents as documents_routes
from services.corpus import CorpusChunkStore, CorpusIndex
from services.corpus.documents import DocumentsAdapter
from services.documents import DocumentStore


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    adapter = DocumentsAdapter(
        ctx.engine, ctx.services.get(CorpusChunkStore), ctx.vault.unlocked_event
    )
    documents = DocumentStore(ctx.engine, ctx.vault, adapter)
    ctx.services.get(CorpusIndex).register(adapter)
    await ctx.lifecycle.start("corpus-documents", start=adapter.start, stop=adapter.stop)
    return FeatureRuntime(
        services=(documents, adapter),
        state={"documents": documents, "corpus_documents": adapter},
    )


MANIFEST = FeatureManifest(
    name="documents",
    after=("corpus",),
    routers=(documents_routes.router,),
    build=_build,
)
