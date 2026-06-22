"""Serving value types — engines, workloads, catalog entries, and views.

Plain Pydantic (nothing persisted here; the durable shape is
``models.serving.ManagedModel``). The load-bearing rule, borrowed from the
Cookbook: **degrade, don't crash** — an unavailable engine is reported as a
known-but-unavailable recommendation, never an error.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EngineKind(StrEnum):
    """An inference engine the platform can supervise. Values match the hardware
    probe's runtime tokens where they overlap."""

    llama_cpp = "llama.cpp"
    mlx = "mlx"


class Workload(StrEnum):
    chat = "chat"
    embedding = "embedding"
    vision = "vision"


class ServeState(StrEnum):
    stopped = "stopped"
    downloading = "downloading"
    starting = "starting"
    running = "running"
    error = "error"


class EngineRecommendation(BaseModel):
    """An engine ranked for the host.

    ``available`` reflects whether the engine can actually run here (platform +
    runtime). An unavailable engine is still listed (with ``reason``) so the UI is
    honest about what the host supports. The operator points the engine at any
    HuggingFace repo — there is no curated model list to keep current.
    """

    engine: EngineKind
    rank: int  # 1 = best fit for this host
    available: bool  # can run here (platform ok + runtime present or fetchable)
    installed: bool = False  # runtime already present (no install/download on first serve)
    reason: str
    workloads: list[Workload] = Field(default_factory=list)


class DownloadProgress(BaseModel):
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    fraction: float | None = None  # 0..1 when total is known
    file: str | None = None  # the file currently transferring


class ManagedModelView(BaseModel):
    """A managed model's live state — the LOCAL MODELS UI polls a list of these."""

    id: str
    engine: EngineKind
    workload: Workload
    hf_repo: str
    quant: str | None = None
    state: ServeState
    endpoint_id: str | None = None
    endpoint_name: str | None = None
    port: int | None = None
    last_error: str | None = None
    progress: DownloadProgress | None = None
