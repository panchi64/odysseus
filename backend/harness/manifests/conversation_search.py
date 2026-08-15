"""Cross-chat search — hybrid recall over the operator's other conversations plus a
transcript read, reusing the conversation store's active-path projection."""

from __future__ import annotations

from harness.manifest import FeatureManifest, FeatureRuntime, HarnessContext
from services.conversation_search import ConversationSearch
from services.conversations import ConversationStore
from services.embeddings import RegistryEmbedder
from tools.conversations import conversations_toolset


async def _build(ctx: HarnessContext) -> FeatureRuntime:
    search = ConversationSearch(
        ctx.engine,
        ctx.vault,
        ctx.services.get(RegistryEmbedder),
        ctx.services.get(ConversationStore),
    )
    return FeatureRuntime(
        services=(search,), capabilities=(search,), state={"conversation_search": search}
    )


MANIFEST = FeatureManifest(
    name="conversation-search",
    toolsets=(("conversations", conversations_toolset),),
    # Global relevance-ranked search is approval-gated at call time (the recall gate),
    # so the scope vocabulary must carry the name explicitly.
    gated_tools=frozenset({"conversations_search"}),
    build=_build,
)
