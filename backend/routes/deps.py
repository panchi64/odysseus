"""Shared accessors for the singletons hung on ``app.state``.

One place to resolve a capability from a request, so every router reaches them
the same way and the wiring has a single point to change (or to grow into
FastAPI ``Depends`` later).
"""

from __future__ import annotations

from fastapi import Request

from core.auth import AuthManager
from core.ratelimit import RateLimiter
from core.vault import Vault
from runs import RunRegistry
from services.approval_grants import ApprovalGrantStore
from services.artifacts import ArtifactStore
from services.conversation_search import ConversationSearch
from services.conversations import ConversationStore
from services.cookbook import CookbookService
from services.corpus import CorpusIndex
from services.credential_store import CredentialStore
from services.documents import DocumentStore
from services.memory import MemoryStore
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.sandbox import SandboxSessionManager
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.serving import ServingService
from services.uploads import UploadStore
from services.webfetch import BrowserFetcher, ManagedBrowser

# Single operator: every record is attributed to this owner until a second human
# exists (the ownership seam). One constant so routes don't each redefine it.
OPERATOR_ID = "operator"


def registry(request: Request) -> RunRegistry:
    return request.app.state.runs


def store(request: Request) -> ConversationStore:
    return request.app.state.conversations


def conversation_search(request: Request) -> ConversationSearch:
    return request.app.state.conversation_search


def corpus(request: Request) -> CorpusIndex:
    return request.app.state.corpus


def models(request: Request) -> ModelRegistry:
    return request.app.state.models


def memory(request: Request) -> MemoryStore:
    return request.app.state.memory


def approval_grants(request: Request) -> ApprovalGrantStore:
    return request.app.state.approval_grants


def documents(request: Request) -> DocumentStore:
    return request.app.state.documents


def uploads(request: Request) -> UploadStore:
    return request.app.state.uploads


def upload_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.upload_rate_limiter


def embedding_reindexer(request: Request) -> EmbeddingReindexer:
    return request.app.state.embedding_reindexer


def search(request: Request) -> SearchService:
    return request.app.state.search


def fetcher(request: Request) -> BrowserFetcher:
    return request.app.state.fetcher


def browser(request: Request) -> ManagedBrowser:
    return request.app.state.browser


def searxng(request: Request) -> ManagedSearxng:
    return request.app.state.searxng


def artifacts(request: Request) -> ArtifactStore:
    return request.app.state.artifacts


def sandbox_sessions(request: Request) -> SandboxSessionManager | None:
    """The per-conversation sandbox manager, or None when no runtime is available
    (fail closed)."""
    return request.app.state.sandbox


def cookbook(request: Request) -> CookbookService:
    return request.app.state.cookbook


def serving(request: Request) -> ServingService:
    return request.app.state.serving


def credentials(request: Request) -> CredentialStore:
    return request.app.state.credentials


def vault(request: Request) -> Vault:
    return request.app.state.vault


def auth_manager(request: Request) -> AuthManager:
    return request.app.state.auth_manager
