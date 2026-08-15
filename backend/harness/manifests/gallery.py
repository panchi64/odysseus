"""The gallery — a presentation lens over the image uploads plus the operator's
custom albums. Owns no image bytes: it reads the uploads store (for the images) and
the conversation store (for chat-vs-imported provenance), and curates albums."""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from routes import gallery as gallery_routes
from services.conversations import ConversationStore
from services.gallery import GalleryService
from services.uploads import UploadStore


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    gallery = GalleryService(
        ctx.engine,
        ctx.vault,
        ctx.services.get(ConversationStore),
        ctx.services.get(UploadStore),
    )
    return FeatureRuntime(services=(gallery,), state={"gallery": gallery})


MANIFEST = FeatureManifest(
    name="gallery",
    after=("uploads",),
    routers=(gallery_routes.router,),
    build=_build,
)
