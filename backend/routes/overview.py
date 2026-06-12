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
    # The main role's resolved model + the endpoint backing it, when configured.
    main_model: str | None
    main_provider: str | None
    context_window: int | None
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
    by_id = {e.id: e for e in endpoints}

    main_ids = roles.get("main") or []
    main_endpoint = by_id.get(main_ids[0]) if main_ids else None
    embedding_configured = bool(roles.get("embedding"))
    sandbox_present = deps.sandbox_sessions(request) is not None

    conversation_count = await deps.store(request).count_conversations(OPERATOR_ID)
    memory_count = await deps.memory(request).count(OPERATOR_ID)
    active_runs = [r for r in deps.registry(request).list(OPERATOR_ID) if not r.is_terminal]

    capabilities: list[Capability] = []
    # Main model — the one capability the workspace can't function without.
    if main_endpoint is not None:
        capabilities.append(
            Capability(
                key="main_model",
                label="MAIN MODEL",
                status="nominal",
                detail=main_endpoint.model or main_endpoint.name,
                critical=True,
            )
        )
    else:
        capabilities.append(
            Capability(
                key="main_model",
                label="MAIN MODEL",
                status="alert",
                detail="no endpoint bound",
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

    return Overview(
        version=get_settings().version,
        main_model=main_endpoint.model if main_endpoint else None,
        main_provider=main_endpoint.name if main_endpoint else None,
        context_window=main_endpoint.context_window if main_endpoint else None,
        endpoint_count=len(endpoints),
        conversation_count=conversation_count,
        memory_count=memory_count,
        active_run_count=len(active_runs),
        capabilities=capabilities,
    )
