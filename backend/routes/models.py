"""Model registry surface — manage endpoints and role→chain bindings.

The operator's catalog of model endpoints and the role bindings that map ``main``
/ ``utility`` / ``embedding`` to ordered fallback chains. The API key is
**write-only**: it is accepted on create/update and sealed with the vault, but
never returned — listings expose only ``has_api_key``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.exceptions import DegradedCapabilityError, NotFoundError
from models.registry import ModelEndpoint
from routes import deps
from routes.deps import OPERATOR_ID
from services import llm

router = APIRouter(prefix="/models", tags=["models"])


class EndpointCreate(BaseModel):
    name: str
    base_url: str
    model: str | None = None
    api_key: str | None = None
    context_window: int | None = None
    native_tools: bool = True
    vision: bool = False
    thinking: bool = False


class EndpointUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # "" clears the key; omitted leaves it unchanged
    context_window: int | None = None
    native_tools: bool | None = None
    vision: bool | None = None
    thinking: bool | None = None


class EndpointView(BaseModel):
    id: str
    name: str
    base_url: str
    model: str | None
    has_api_key: bool
    context_window: int | None
    native_tools: bool
    vision: bool
    thinking: bool


def _view(endpoint: ModelEndpoint) -> EndpointView:
    return EndpointView(
        id=endpoint.id,
        name=endpoint.name,
        base_url=endpoint.base_url,
        model=endpoint.model,
        has_api_key=endpoint.api_key_enc is not None,
        context_window=endpoint.context_window,
        native_tools=endpoint.native_tools,
        vision=endpoint.vision,
        thinking=endpoint.thinking,
    )


@router.get("/endpoints", response_model=list[EndpointView])
async def list_endpoints(request: Request) -> list[EndpointView]:
    endpoints = await deps.models(request).list_endpoints(OPERATOR_ID)
    return [_view(e) for e in endpoints]


@router.post("/endpoints", status_code=201, response_model=EndpointView)
async def create_endpoint(body: EndpointCreate, request: Request) -> EndpointView:
    endpoint = await deps.models(request).create_endpoint(OPERATOR_ID, **body.model_dump())
    return _view(endpoint)


@router.get("/endpoints/{endpoint_id}", response_model=EndpointView)
async def get_endpoint(endpoint_id: str, request: Request) -> EndpointView:
    try:
        endpoint = await deps.models(request).get_endpoint(OPERATOR_ID, endpoint_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="endpoint not found") from None
    return _view(endpoint)


class EndpointModels(BaseModel):
    models: list[str]
    # False when the provider has no models API (or is unreachable) — the picker
    # then falls back to the endpoint's configured model instead of a live list.
    supported: bool


@router.get("/endpoints/{endpoint_id}/models", response_model=EndpointModels)
async def list_endpoint_models(endpoint_id: str, request: Request) -> EndpointModels:
    try:
        models = await deps.models(request).list_provider_models(OPERATOR_ID, endpoint_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="endpoint not found") from None
    except DegradedCapabilityError:
        return EndpointModels(models=[], supported=False)
    return EndpointModels(models=models, supported=True)


@router.patch("/endpoints/{endpoint_id}", response_model=EndpointView)
async def update_endpoint(endpoint_id: str, body: EndpointUpdate, request: Request) -> EndpointView:
    changes = body.model_dump(exclude_unset=True)
    try:
        endpoint = await deps.models(request).update_endpoint(OPERATOR_ID, endpoint_id, **changes)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="endpoint not found") from None
    return _view(endpoint)


@router.delete("/endpoints/{endpoint_id}", status_code=204)
async def delete_endpoint(endpoint_id: str, request: Request) -> None:
    try:
        await deps.models(request).delete_endpoint(OPERATOR_ID, endpoint_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="endpoint not found") from None


class RoleBinding(BaseModel):
    endpoint_ids: list[str]


@router.get("/roles", response_model=dict[str, list[str]])
async def list_roles(request: Request) -> dict[str, list[str]]:
    return await deps.models(request).list_roles(OPERATOR_ID)


@router.put("/roles/{role}", status_code=204)
async def set_role(role: str, body: RoleBinding, request: Request) -> None:
    if role not in llm.ROLES:
        raise HTTPException(status_code=422, detail=f"unknown role {role!r}")
    try:
        await deps.models(request).set_role(OPERATOR_ID, role, body.endpoint_ids)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="endpoint not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
