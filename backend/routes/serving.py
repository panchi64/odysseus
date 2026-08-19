"""Local model serving surface — recommend an engine and manage locally-served models.

Thin: the route maps the request to ``ServingService`` and its results back out.
Snake-case bodies mirror the sibling ``/models/cookbook/hardware`` surface (both
expose hardware-shaped value types). There is no curated catalog — the operator points
an engine at any HuggingFace repo and it downloads + serves.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.exceptions import NotFoundError, ServingError, ServingUnavailableError
from routes import deps
from routes.deps import OPERATOR_ID
from services import host_picker
from services.host_picker import PickerAvailability, PickMode
from services.serving import (
    EngineKind,
    EngineRecommendation,
    LaunchOptions,
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
    # Per-model engine launch overrides. Omitted ⇒ keep whatever the model was last
    # served with, so a plain re-serve doesn't silently reset the operator's tuning.
    options: LaunchOptions | None = None


class ImportRequest(BaseModel):
    """Weights the operator already has on disk. ``path`` is absolute and stays where it
    is — nothing is copied into the models directory, and deleting the entry later leaves
    the files alone."""

    engine: EngineKind
    path: str
    workload: Workload = Workload.chat
    name: str | None = None  # display name; defaults to the file/folder's own


class ModelsDirBody(BaseModel):
    models_dir: str


class PickRequest(BaseModel):
    mode: PickMode = "file"
    title: str = "Choose"
    start_dir: str | None = None
    extensions: list[str] | None = None  # bare, e.g. ["gguf"]


class PickResult(BaseModel):
    path: str | None = None  # None ⇒ the operator cancelled the dialog


@router.get("/recommendations", response_model=list[EngineRecommendation])
async def get_recommendations(request: Request) -> list[EngineRecommendation]:
    return await deps.serving(request).recommend_engine(OPERATOR_ID)


@router.get("/repo-quants", response_model=list[str])
async def get_repo_quants(request: Request, repo: str, engine: EngineKind) -> list[str]:
    """The quantizations available in ``repo`` for ``engine`` — the quant picker's options.
    Best-effort: an empty list means no selectable quants (the engine bakes the quant into
    the repo id, or the repo couldn't be introspected)."""
    return await deps.serving(request).list_repo_quants(OPERATOR_ID, engine, repo)


@router.get("/settings", response_model=ModelsDirBody)
async def get_serving_settings(request: Request) -> ModelsDirBody:
    return ModelsDirBody(models_dir=await deps.serving(request).get_models_dir(OPERATOR_ID))


@router.put("/settings", response_model=ModelsDirBody)
async def update_serving_settings(request: Request, body: ModelsDirBody) -> ModelsDirBody:
    try:
        stored = await deps.serving(request).set_models_dir(OPERATOR_ID, body.models_dir)
    except ServingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return ModelsDirBody(models_dir=stored)


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


@router.post("/import", response_model=ManagedModelView, status_code=201)
async def import_model(request: Request, body: ImportRequest) -> ManagedModelView:
    """Register a model already on disk, so it can be served without downloading."""
    try:
        return await deps.serving(request).import_local(
            OPERATOR_ID,
            body.engine,
            body.path,
            workload=body.workload,
            name=body.name,
        )
    except ServingUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ServingError as exc:
        # A path that doesn't exist or isn't this engine's format is the operator's to
        # correct, so it comes back as a 400 the form can show inline.
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/file-picker", response_model=PickerAvailability)
async def file_picker_availability() -> PickerAvailability:
    """Whether this host can open a native chooser. The path field works either way —
    this only decides whether a BROWSE control is worth offering."""
    return host_picker.probe()


@router.post("/file-picker", response_model=PickResult)
async def open_file_picker(body: PickRequest) -> PickResult:
    """Open a native file/folder dialog on the host and return what was chosen."""
    try:
        path = await host_picker.pick(
            body.mode,
            title=body.title,
            start_dir=body.start_dir,
            extensions=body.extensions,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return PickResult(path=path)


@router.post("/serve", response_model=ManagedModelView)
async def serve_model(request: Request, body: ServeRequest) -> ManagedModelView:
    # A bad flag (or one aimed at an engine that can't use it) is the operator's mistake,
    # not an engine fault — reject it as a 400 the form can show, rather than letting it
    # become a failed spawn minutes later or tuning that is stored but never applied.
    try:
        deps.serving(request).validate_options(body.engine, body.options)
    except ServingUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ServingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    try:
        return await deps.serving(request).serve(
            OPERATOR_ID,
            body.engine,
            body.repo,
            role=body.role,
            workload=body.workload,
            quant=body.quant,
            options=body.options,
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
