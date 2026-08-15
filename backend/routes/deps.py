"""Shared accessors for the singletons hung on ``app.state``.

One place to resolve a capability from a request, so every router reaches them
the same way and the wiring has a single point to change (or to grow into
FastAPI ``Depends`` later).
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request
from sqlalchemy import Engine

from core.auth import AuthManager
from core.container import ServiceContainer
from core.ratelimit import RateLimiter
from core.vault import Vault
from runs import ConversationBusyError, Run, RunRegistry
from services.api_token_store import ApiTokenStore
from services.approval_grants import ApprovalGrantStore
from services.artifacts import ArtifactStore
from services.backup import BackupService
from services.calendar import CalendarService
from services.conversation_search import ConversationSearch
from services.conversations import ConversationStore
from services.cookbook import CookbookService
from services.corpus import CorpusIndex
from services.credential_store import CredentialStore
from services.documents import DocumentStore
from services.external_tools import ExternalTools
from services.gallery import GalleryService
from services.host_shell import ShellService
from services.integrations import IntegrationService
from services.mail import MailService
from services.mcp import McpRegistry
from services.memory import MemoryStore
from services.notifications import NotificationService
from services.offline import OfflineModeService
from services.registry import ModelRegistry
from services.reindex import EmbeddingReindexer
from services.sandbox import SandboxSessionManager
from services.scheduler import SchedulerService
from services.search import SearchService
from services.searxng import ManagedSearxng
from services.secret_vault import SecretVaultService
from services.serving import ServingService
from services.settings_store import SettingsStore
from services.skills import SkillStore
from services.tool_policy import effective_disabled_tools
from services.uploads import UploadStore
from services.webfetch import BrowserFetcher, ManagedBrowser
from services.workspace_history import WorkspaceHistoryStore

# Single operator: every record is attributed to this owner until a second human
# exists (the ownership seam). One constant so routes don't each redefine it.
OPERATOR_ID = "operator"


def registry(request: Request) -> RunRegistry:
    return request.app.state.runs


def capabilities(request: Request) -> ServiceContainer:
    """The app's one agent-facing capability bag (`RunDeps.caps`) — assembled at
    startup from every feature manifest's `capabilities` export. Every run path
    (live chat, approval resume, the scheduler's executor) hands this same bag to
    the engine, so the capability set can never diverge between them."""
    return request.app.state.capabilities


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


def skills(request: Request) -> SkillStore:
    return request.app.state.skills


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


async def disabled_tools(request: Request) -> frozenset[str]:
    """Everything withheld from the agent on this run — the operator's own disabled set
    (`AE-3.3`) unioned with offline mode's automatic web suspension. Every route that
    fills ``RunDeps.disabled_tools`` resolves it here, so a run path can't apply one
    source and drop the other; ``app.py``'s task executor calls the service directly
    (it has no ``Request``)."""
    return await effective_disabled_tools(
        settings_store(request), offline(request), OPERATOR_ID
    )


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


def shell(request: Request) -> ShellService:
    return request.app.state.shell


def shell_auth_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.shell_auth_rate_limiter


def research_run_waiters(request: Request) -> dict[str, asyncio.Future[Run]]:
    """Keyed by run id, resolved by ``app.py``'s ``_on_run_terminal`` hook the moment a
    research run reaches a genuinely terminal state — the research route awaits one of
    these to learn the outcome once the underlying Run settles, the same shape the
    scheduler's agent-task executor uses (`app.state.task_run_waiters`), kept as its own
    dict rather than shared so the two features' bookkeeping stays independent."""
    return request.app.state.research_run_waiters


def mail(request: Request) -> MailService:
    """The mail capability (`EMAIL-1..5`) — accounts, the sync loop, the inbox cache,
    triage and drafts. Its background worker is started and stopped with the app."""
    return request.app.state.mail


def calendar(request: Request) -> CalendarService:
    """The calendar capability (`CAL-1..3`), including natural-language entry as `.nl`."""
    return request.app.state.calendar


def external(request: Request) -> ExternalTools:
    """The whole external-tools capability — registered MCP servers (`MCP-*`), configured
    connectors (`INTEG-*`) and the per-tool trust policy they share (`AE-3.6`).

    One object rather than two capability handles, because the agent sees one `external`
    category and shouldn't have to know which source a tool came from. One instance for
    both the REST surfaces and the agent, which is what makes a server registered a moment
    ago visible to the very next run.
    """
    return request.app.state.external


def mcp(request: Request) -> McpRegistry:
    """The registry of external MCP tool servers (`MCP-*`), backing the `/mcp` surface."""
    return external(request).mcp


def integrations(request: Request) -> IntegrationService:
    """Third-party connectors configured from presets (`INTEG-*`), backing `/integrations`."""
    return external(request).integrations


def secret_vault(request: Request) -> SecretVaultService:
    """The operator's secrets manager (`VAULT-*`). Distinct from `vault()` above, which is
    the at-rest key custody. One instance per process — its whole point is holding a single
    in-memory unlock state, which a per-request instance would throw away."""
    return request.app.state.secret_vault


def backup(request: Request) -> BackupService:
    """Encrypted export/import (`BACKUP-*`)."""
    return request.app.state.backup


def api_tokens(request: Request) -> ApiTokenStore:
    """Inbound scoped API tokens (`AUTH-4`). Distinct from `credentials()` above, which
    holds the outbound service keys.

    The auth gate in `core.auth` reads this same instance straight off ``app.state`` —
    it has to, since it runs before any route reaches this module — so a revoke through
    the route invalidates exactly what the gate trusts, rather than the two keeping
    separate verification caches."""
    return request.app.state.api_tokens


def run_terminal_tasks(request: Request) -> set[asyncio.Task[None]]:
    """The shared bucket of in-flight terminal-transition background tasks — a route
    that spawns one (research's finalize-on-terminal task) adds it here so shutdown can
    drain it alongside the notification surface's own, rather than tearing the DB
    engine/vault down from under it."""
    return request.app.state.run_terminal_tasks
