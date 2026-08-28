"""Engine adapters — the pluggable per-engine seam, plus the host registry.

``build_adapters`` returns the adapters the platform supports. llama.cpp is universal;
MLX (Apple-Silicon only) registers here as that slice lands. An adapter whose engine
isn't runnable on this host simply isn't built, so the rest of the system degrades
cleanly rather than erroring.
"""

from __future__ import annotations

from ..models import EngineKind
from ..paths import ServingPaths
from .base import EngineAdapter
from .llamacpp import LlamaCppAdapter
from .mlx import MlxAdapter

__all__ = ["EngineAdapter", "LlamaCppAdapter", "MlxAdapter", "build_adapters"]


def build_adapters(paths: ServingPaths) -> dict[EngineKind, EngineAdapter]:
    """The adapters known to this host. Availability (platform/runtime) is checked per
    call via each adapter's ``is_available`` — this just wires the catalogue. MLX is
    registered everywhere but reports unavailable off Apple Silicon, so a non-Apple host
    sees a clear "not available" rather than an "unsupported engine" error."""
    return {
        EngineKind.llama_cpp: LlamaCppAdapter(paths),
        EngineKind.mlx: MlxAdapter(paths),
    }
