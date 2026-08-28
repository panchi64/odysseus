"""Managed local-model serving schema.

A locally-served model is a normal :class:`~models.registry.ModelEndpoint` (an
OpenAI-compatible ``base_url`` at ``127.0.0.1``) **plus** this side row, which
carries the serving lifecycle the chassis owns: which engine runs it, the
HuggingFace repo it came from, the downloaded artifact, and the live process
state.

Keeping serving state out of ``ModelEndpoint`` keeps that table the pure provider
connection the resolve→role→chat path already depends on — remote endpoints carry
none of these fields — and makes restart reconciliation a clean scan of one table.
Nothing here is sensitive (a local server has no API key), so every field is stored
in the clear like the rest of the registry's structural metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from models._fields import new_id, utcnow


class ManagedModel(SQLModel, table=True):
    __tablename__ = "managed_models"

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(index=True)
    # The endpoint carrying base_url=http://127.0.0.1:PORT/v1, set when the model is
    # first served. None until then — a model is downloaded before any endpoint exists
    # (SQLite's unique index treats NULLs as distinct, so many un-served rows coexist).
    # One managed model ⇄ one endpoint. A real FK: deleting the endpoint from the
    # registry side nulls this reference instead of stranding a dangling id; the
    # service still prunes both together on its own delete path.
    endpoint_id: str | None = Field(
        default=None,
        index=True,
        unique=True,
        foreign_key="model_endpoints.id",
        ondelete="SET NULL",
    )
    engine: str  # EngineKind value: "llama.cpp" | "mlx"
    workload: str  # Workload value: "chat" | "embedding" | "vision"
    hf_repo: str  # the HuggingFace repo id the operator pointed at
    quant: str | None = None  # GGUF quant tag (llama.cpp); None for MLX
    # Resolved local artifact under data/ — a GGUF file (llama.cpp) or a snapshot
    # dir (MLX). None until the download completes.
    artifact_path: str | None = None
    # ModelSource: "huggingface" (we fetched it, so we may remove it) | "local" (the
    # operator pointed us at weights they already had — read where they are, never
    # moved, never deleted). Rows predating this column are downloads, which is the
    # default.
    source: str = Field(default="huggingface", nullable=False)
    state: str = "stopped"  # ServeState: stopped|downloading|starting|running|error
    port: int | None = None  # allocated host port while running
    pid: int | None = None  # OS pid while running (for orphan reconciliation)
    last_error: str | None = None  # plain-language failure detail (never a secret)
    # A serialized services.serving.LaunchOptions — the engine launch overrides this model
    # is served with, kept here so a stop/start cycle reuses them. An empty dict means
    # "every engine default stands", which is the shape a row created before this column
    # existed also lands on.
    launch_options: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
