"""Shared accessors for the singletons hung on ``app.state``.

One place to resolve a capability from a request, so every router reaches them
the same way and the wiring has a single point to change (or to grow into
FastAPI ``Depends`` later).
"""

from __future__ import annotations

from fastapi import Request

from core.auth import AuthManager
from core.vault import Vault
from runs import RunRegistry
from services.artifacts import ArtifactStore
from services.conversations import ConversationStore
from services.memory import MemoryStore
from services.registry import ModelRegistry
from services.sandbox import SandboxSessionManager
from services.search import SearchService

# Single operator: every record is attributed to this owner until a second human
# exists (the ownership seam). One constant so routes don't each redefine it.
OPERATOR_ID = "operator"


def registry(request: Request) -> RunRegistry:
    return request.app.state.runs


def store(request: Request) -> ConversationStore:
    return request.app.state.conversations


def models(request: Request) -> ModelRegistry:
    return request.app.state.models


def memory(request: Request) -> MemoryStore:
    return request.app.state.memory


def search(request: Request) -> SearchService:
    return request.app.state.search


def artifacts(request: Request) -> ArtifactStore:
    return request.app.state.artifacts


def sandbox_sessions(request: Request) -> SandboxSessionManager | None:
    """The per-conversation sandbox manager, or None when no runtime is available
    (fail closed)."""
    return request.app.state.sandbox


def vault(request: Request) -> Vault:
    return request.app.state.vault


def auth_manager(request: Request) -> AuthManager:
    return request.app.state.auth_manager
