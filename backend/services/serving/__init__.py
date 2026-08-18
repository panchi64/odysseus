"""Managed local inference serving — download a model, supervise an engine, serve it.

The platform owns the serving lifecycle (the engine subprocess, downloads, health,
stop). A served model registers as a normal ``ModelEndpoint`` at ``127.0.0.1`` so it
flows through the existing resolve→role→chat path unchanged. The engine is a pluggable
adapter; llama.cpp is the universal baseline and MLX an Apple-Silicon speed upgrade.
"""

from __future__ import annotations

from .models import (
    DownloadProgress,
    EngineKind,
    EngineRecommendation,
    KvCacheType,
    LaunchOptions,
    ManagedModelView,
    ServeState,
    Workload,
    validate_extra_args,
    validate_options,
)
from .paths import ServingPaths
from .service import ServingService

__all__ = [
    "DownloadProgress",
    "EngineKind",
    "EngineRecommendation",
    "KvCacheType",
    "LaunchOptions",
    "ManagedModelView",
    "ServeState",
    "ServingPaths",
    "ServingService",
    "Workload",
    "validate_extra_args",
    "validate_options",
]
