"""Shared accessors for the singletons hung on ``app.state``.

One place to resolve a capability from a request, so every router reaches them
the same way and the wiring has a single point to change (or to grow into
FastAPI ``Depends`` later).
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import Engine

from core.auth import AuthManager
from core.ratelimit import RateLimiter
from core.vault import Vault
from runs import ConversationBusyError, RunRegistry
from services.approval_grants import ApprovalGrantStore
from services.artifacts import ArtifactStore
from services.conversation_search import ConversationSearch
from services.conversations import ConversationStore
from services.cookbook import CookbookService
from services.corpus import CorpusIndex
from services.credential_store import CredentialStore
from services.documents import DocumentStore
from services.gallery import GalleryService
from services.memory import MemoryStore
from services.notifications import NotificationService
from services.offline import OfflineModeService
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.sandbox import SandboxSessionManager
from services.scheduler import SchedulerService
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.serving import ServingService
from services.settings_store import SettingsStore
from services.uploads import UploadStore
from services.webfetch import BrowserFetcher, ManagedBrowser
from services.workspace_history import WorkspaceHistoryStore

# Single operator: every record is attributed to this owner until a second human
# exists (the ownership seam). One constant so routes don't each redefine it.
OPERATOR_ID = "operator"


def registry(request: Request) -> RunRegistry:
    return request.app.state.runs


_CONVERSATION_BUSY_DETAIL = "A response is already in progress in this conversation"


def claim_conversation(request: Request, conversation_id: str) -> None:
    """Claim ``conversation_id`` for a request that will reposition the active leaf
    (regenerate/edit/rewind/switch-version/a purging delete) or submit a new run, with
    further ``await``s of its own still ahead of it — call this **before** the first of
    those ``await``s, so a second near-simultaneous request can never slip past a check
    the first request has already passed but not yet acted on.

    Raises HTTP 409 when a live run already drives this conversation, or another
    in-flight request already holds the claim. The caller **must** pair this with
    `release_conversation` in a ``finally`` covering every exit path (a failed model
    resolve, a 404 message id, a successful submit) — see ``RunRegistry.claim``.
    """
    try:
        registry(request).claim(conversation_id, OPERATOR_ID)
    except ConversationBusyError as exc:
        raise HTTPException(status_code=409, detail=_CONVERSATION_BUSY_DETAIL) from exc


def release_conversation(request: Request, conversation_id: str) -> None:
    """Release a claim taken by `claim_conversation`. Idempotent."""
    registry(request).release(conversation_id, OPERATOR_ID)


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


def notifications(request: Request) -> NotificationService:
    return request.app.state.notifications


def approval_grants(request: Request) -> ApprovalGrantStore:
    return request.app.state.approval_grants


def documents(request: Request) -> DocumentStore:
    return request.app.state.documents


def uploads(request: Request) -> UploadStore:
    return request.app.state.uploads


def gallery(request: Request) -> GalleryService:
    return request.app.state.gallery


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


def offline(request: Request) -> OfflineModeService:
    return request.app.state.offline


def artifacts(request: Request) -> ArtifactStore:
    return request.app.state.artifacts


def workspace_history(request: Request) -> WorkspaceHistoryStore:
    return request.app.state.workspace_history


def sandbox_sessions(request: Request) -> SandboxSessionManager | None:
    """The per-conversation sandbox manager, or None when no runtime is available
    (fail closed)."""
    return request.app.state.sandbox


def cookbook(request: Request) -> CookbookService:
    return request.app.state.cookbook


def serving(request: Request) -> ServingService:
    return request.app.state.serving


def settings_store(request: Request) -> SettingsStore:
    return request.app.state.settings_store


def credentials(request: Request) -> CredentialStore:
    return request.app.state.credentials


def vault(request: Request) -> Vault:
    return request.app.state.vault


def auth_manager(request: Request) -> AuthManager:
    return request.app.state.auth_manager


def db_engine(request: Request) -> Engine:
    """The raw DB engine — for the surfaces (like `routes/tasks.py`) that don't yet
    have a dedicated service and read/write their own SQLModel rows directly."""
    return request.app.state.db_engine


def scheduler(request: Request) -> SchedulerService:
    return request.app.state.scheduler
