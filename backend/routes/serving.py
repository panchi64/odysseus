"""Local model serving surface — recommend an engine, browse the catalog, manage
locally-served models.

Thin: the route maps the request to ``ServingService`` and its results back out.
Snake-case bodies mirror the sibling ``/models/cookbook/hardware`` surface (both
expose hardware-shaped value types). Download/serve/stop land in later slices.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.exceptions import NotFoundError, ServingError, ServingUnavailableError
from routes import deps
from routes.deps import OPERATOR_ID
from services.serving import (
    CatalogEntry,
    EngineKind,
    EngineRecommendation,
    ManagedModelView,
    Workload,
)

router = APIRouter(prefix="/models/serving", tags=["serving"])


class DownloadRequest(BaseModel):
    engine: EngineKind
    repo: str
    workload: Workload = Workload.chat
    quant: str | None = None


class ServeRequest(BaseModel):
    engine: EngineKind
    repo: str
    role: str | None = None  # bind this role (main/utility/embedding) to the served model
    workload: Workload = Workload.chat
    quant: str | None = None


@router.get("/recommendations", response_model=list[EngineRecommendation])
async def get_recommendations(request: Request) -> list[EngineRecommendation]:
    return await deps.serving(request).recommend_engine(OPERATOR_ID)


@router.get("/catalog", response_model=list[CatalogEntry])
async def get_catalog(
    request: Request, engine: EngineKind, workload: Workload = Workload.chat
) -> list[CatalogEntry]:
    return await deps.serving(request).list_catalog(engine, workload)


@router.get("/models", response_model=list[ManagedModelView])
async def list_models(request: Request) -> list[ManagedModelView]:
    return await deps.serving(request).status(OPERATOR_ID)


@router.post("/download", response_model=ManagedModelView, status_code=202)
async def download_model(request: Request, body: DownloadRequest) -> ManagedModelView:
    try:
        return await deps.serving(request).download(
            OPERATOR_ID, body.engine, body.repo, workload=body.workload, quant=body.quant
        )
    except ServingUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ServingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/serve", response_model=ManagedModelView)
async def serve_model(request: Request, body: ServeRequest) -> ManagedModelView:
    try:
        return await deps.serving(request).serve(
            OPERATOR_ID,
            body.engine,
            body.repo,
            role=body.role,
            workload=body.workload,
            quant=body.quant,
        )
    except ServingUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ServingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/{managed_id}/stop", response_model=ManagedModelView)
async def stop_model(request: Request, managed_id: str) -> ManagedModelView:
    try:
        return await deps.serving(request).stop(OPERATOR_ID, managed_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="managed model not found") from None
    except ServingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.delete("/{managed_id}", status_code=204)
async def delete_model(request: Request, managed_id: str) -> None:
    try:
        await deps.serving(request).delete(OPERATOR_ID, managed_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="managed model not found") from None
