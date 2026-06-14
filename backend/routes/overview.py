"""Home overview — a read-only aggregate of real chassis status.

The home page is presentation-only; this endpoint is the single source of truth
it renders. It reports what the backend actually knows: the build version, which
model roles are configured, whether the execution sandbox is present, and counts
of the operator's conversations, memories, and configured endpoints — plus the
capability health derived from those facts (the policy lives here, not in the
frontend). Telemetry and external services that don't exist yet are simply
absent rather than fabricated; they grow rows here as their capabilities land.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.config import get_settings
from routes import deps
from routes.deps import OPERATOR_ID

router = APIRouter(prefix="/overview", tags=["overview"])


class Capability(BaseModel):
    """A capability the workspace exposes, with backend-decided health.

    ``status``/``detail`` are rendered verbatim — the frontend does not decide
    what counts as nominal/degraded/down. ``critical`` marks a capability the
    workspace cannot function without (drives the overall-status flag)."""

    key: str  # stable id: "main_model" | "embeddings" | "sandbox"
    label: str
    status: str  # "nominal" | "warn" | "alert"
    detail: str
    critical: bool = False
    remediation_href: str | None = None
    remediation_label: str | None = None


class Overview(BaseModel):
    version: str
    endpoint_count: int
    conversation_count: int
    memory_count: int
    active_run_count: int
    capabilities: list[Capability]


@router.get("", response_model=Overview)
async def get_overview(request: Request) -> Overview:
    models = deps.models(request)
    roles = await models.list_roles(OPERATOR_ID)
    endpoints = await models.list_endpoints(OPERATOR_ID)

    # The chat (`main`) model is chosen live from the top-bar picker, not bound
    # here — so the precondition the workspace can't function without is simply
    # that a usable chat endpoint exists. `main` requires native tool-calling
    # (enforced at resolve), so only such endpoints count.
    usable_chat_endpoints = [e for e in endpoints if e.native_tools]
    embedding_configured = bool(roles.get("embedding"))
    sandbox_present = deps.sandbox_sessions(request) is not None
    search_providers = await deps.search(request).list_providers(OPERATOR_ID)
    provider_enabled = any(p.enabled for p in search_providers)
    managed_search_ready = deps.searxng(request).base_url is not None
    web_search_configured = provider_enabled or managed_search_ready

    conversation_count = await deps.store(request).count_conversations(OPERATOR_ID)
    memory_count = await deps.memory(request).count(OPERATOR_ID)
    active_runs = [r for r in deps.registry(request).list(OPERATOR_ID) if not r.is_terminal]

    capabilities: list[Capability] = []
    # Chat model — the one capability the workspace can't function without. The
    # operator chooses the live model from the top-bar picker; what the backend
    # asserts here is the precondition for that to be possible at all: at least
    # one native-tool-calling endpoint to chat against.
    if usable_chat_endpoints:
        capabilities.append(
            Capability(
                key="chat_model",
                label="CHAT MODEL",
                status="nominal",
                detail=f"{len(usable_chat_endpoints)} endpoint"
                + ("s" if len(usable_chat_endpoints) != 1 else ""),
                critical=True,
            )
        )
    else:
        capabilities.append(
            Capability(
                key="chat_model",
                label="CHAT MODEL",
                status="alert",
                detail="no tool-calling endpoint" if endpoints else "no provider configured",
                critical=True,
                remediation_href="/models/cookbook",
                remediation_label="CONFIGURE",
            )
        )
    # Embeddings — present ⇒ hybrid recall; absent ⇒ keyword-only (degraded, not down).
    capabilities.append(
        Capability(
            key="embeddings",
            label="EMBEDDINGS",
            status="nominal" if embedding_configured else "warn",
            detail="hybrid recall" if embedding_configured else "keyword-only recall",
            remediation_href=None if embedding_configured else "/models/embedding",
            remediation_label=None if embedding_configured else "CONFIGURE",
        )
    )
    # Execution sandbox — present ⇒ code execution available; absent ⇒ disabled (no host fallback).
    capabilities.append(
        Capability(
            key="sandbox",
            label="CODE SANDBOX",
            status="nominal" if sandbox_present else "warn",
            detail="container runtime" if sandbox_present else "no runtime — disabled",
        )
    )
    # Web search — the backend's managed SearXNG (or an operator-configured
    # provider that overrides it) ⇒ search/fetch available; neither ⇒ disabled
    # (degraded, not down — e.g. no container runtime, or the instance still booting).
    if provider_enabled:
        search_detail = "SearXNG configured"
    elif managed_search_ready:
        search_detail = "SearXNG (managed)"
    else:
        search_detail = "no runtime — disabled"
    capabilities.append(
        Capability(
            key="web_search",
            label="WEB SEARCH",
            status="nominal" if web_search_configured else "warn",
            detail=search_detail,
        )
    )

    return Overview(
        version=get_settings().version,
        endpoint_count=len(endpoints),
        conversation_count=conversation_count,
        memory_count=memory_count,
        active_run_count=len(active_runs),
        capabilities=capabilities,
    )
