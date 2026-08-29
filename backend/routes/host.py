"""Host surface — a native file/folder chooser on the operator's own machine.

Nothing here is model-specific: this is how **any** field that wants an absolute host
path gets one. A browser cannot produce a real path — ``<input type="file">`` hands over
bytes with no location — so the dialog is opened by the process running on the operator's
machine and the chosen path comes back as data.

Progressive enhancement, never a requirement: ``GET`` reports whether this host can open
a chooser at all, and every surface that offers a BROWSE control also takes a typed path.
See ``services/host_picker`` for the platform helpers and the agent-unreachability rule.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import host_picker
from services.host_picker import PickerAvailability, PickMode

router = APIRouter(prefix="/host", tags=["host"])


class PickRequest(BaseModel):
    mode: PickMode = "file"
    title: str = "Choose"
    start_dir: str | None = None
    extensions: list[str] | None = None  # bare, e.g. ["gguf"]


class PickResult(BaseModel):
    path: str | None = None  # None ⇒ the operator cancelled the dialog


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
