"""The curated starter catalog — hardware-fittable, capability-tagged models.

A small, opinionated set so the operator has a one-click path before typing any
HuggingFace repo by hand (the UI also accepts a free-text repo). Chat entries are
restricted to families with confirmed native tool-calling support (AE-8.1):
``llama.cpp`` rides its built-in chat-template handlers; ``mlx`` rides
mlx-openai-server's per-model tool parsers. Embeddings are GGUF-only (one uniform
embedding stack across platforms — see the package CLAUDE.md).

``approx_bytes`` is a rough on-disk/VRAM footprint used only for fit-filtering and
sizing hints; it is not authoritative. These are starting points — the operator can
always point at any repo.
"""

from __future__ import annotations

from .models import CatalogEntry, EngineKind, Workload

_GB = 1024**3


def _gb(n: float) -> int:
    return int(n * _GB)


# --- chat: llama.cpp (GGUF, native chat-template tool-calling) ---------------

_LLAMA_CHAT: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        repo="Qwen/Qwen2.5-7B-Instruct-GGUF", label="Qwen2.5 7B Instruct",
        engine=EngineKind.llama_cpp, workload=Workload.chat, params="7B",
        quant="q4_k_m", approx_bytes=_gb(4.7), context_window=32768,
    ),
    CatalogEntry(
        repo="Qwen/Qwen2.5-14B-Instruct-GGUF", label="Qwen2.5 14B Instruct",
        engine=EngineKind.llama_cpp, workload=Workload.chat, params="14B",
        quant="q4_k_m", approx_bytes=_gb(9.0), context_window=32768,
    ),
    CatalogEntry(
        repo="Qwen/Qwen2.5-32B-Instruct-GGUF", label="Qwen2.5 32B Instruct",
        engine=EngineKind.llama_cpp, workload=Workload.chat, params="32B",
        quant="q4_k_m", approx_bytes=_gb(20.0), context_window=32768,
    ),
    CatalogEntry(
        repo="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", label="Llama 3.1 8B Instruct",
        engine=EngineKind.llama_cpp, workload=Workload.chat, params="8B",
        quant="Q4_K_M", approx_bytes=_gb(4.9), context_window=131072,
    ),
    CatalogEntry(
        repo="bartowski/Mistral-Nemo-Instruct-2407-GGUF", label="Mistral Nemo 12B Instruct",
        engine=EngineKind.llama_cpp, workload=Workload.chat, params="12B",
        quant="Q4_K_M", approx_bytes=_gb(7.5), context_window=131072,
    ),
)

# --- chat: MLX (mlx-community, served via mlx-openai-server) -----------------

_MLX_CHAT: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        repo="mlx-community/Qwen2.5-7B-Instruct-4bit", label="Qwen2.5 7B Instruct (MLX 4-bit)",
        engine=EngineKind.mlx, workload=Workload.chat, params="7B",
        approx_bytes=_gb(4.3), context_window=32768,
    ),
    CatalogEntry(
        repo="mlx-community/Qwen2.5-14B-Instruct-4bit", label="Qwen2.5 14B Instruct (MLX 4-bit)",
        engine=EngineKind.mlx, workload=Workload.chat, params="14B",
        approx_bytes=_gb(8.0), context_window=32768,
    ),
    CatalogEntry(
        repo="mlx-community/Qwen2.5-32B-Instruct-4bit", label="Qwen2.5 32B Instruct (MLX 4-bit)",
        engine=EngineKind.mlx, workload=Workload.chat, params="32B",
        approx_bytes=_gb(18.0), context_window=32768,
    ),
    CatalogEntry(
        repo="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        label="Llama 3.1 8B Instruct (MLX 4-bit)",
        engine=EngineKind.mlx, workload=Workload.chat, params="8B",
        approx_bytes=_gb(4.5), context_window=131072,
    ),
)

# --- embeddings: llama.cpp (GGUF) -------------------------------------------

_LLAMA_EMBED: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        repo="nomic-ai/nomic-embed-text-v1.5-GGUF", label="Nomic Embed Text v1.5",
        engine=EngineKind.llama_cpp, workload=Workload.embedding, params="137M",
        quant="Q4_K_M", approx_bytes=_gb(0.1), native_tools=False, context_window=8192,
    ),
    CatalogEntry(
        repo="CompendiumLabs/bge-base-en-v1.5-gguf", label="BGE Base EN v1.5",
        engine=EngineKind.llama_cpp, workload=Workload.embedding, params="109M",
        quant="q4_k_m", approx_bytes=_gb(0.15), native_tools=False, context_window=512,
    ),
    CatalogEntry(
        repo="CompendiumLabs/bge-large-en-v1.5-gguf", label="BGE Large EN v1.5",
        engine=EngineKind.llama_cpp, workload=Workload.embedding, params="335M",
        quant="q4_k_m", approx_bytes=_gb(0.35), native_tools=False, context_window=512,
    ),
)

CATALOG: tuple[CatalogEntry, ...] = _LLAMA_CHAT + _MLX_CHAT + _LLAMA_EMBED


def _entry_for(engine: EngineKind, repo: str) -> CatalogEntry | None:
    """The catalog entry for a model, or ``None`` for a free-text repo not in it."""
    for e in CATALOG:
        if e.engine == engine and e.repo == repo:
            return e
    return None


def bytes_for(engine: EngineKind, repo: str) -> int | None:
    """The curated on-disk/VRAM footprint estimate for a model, or ``None`` for a repo
    not in the catalog (a free-text one we can't size)."""
    entry = _entry_for(engine, repo)
    return entry.approx_bytes if entry is not None else None


def context_window_for(engine: EngineKind, repo: str) -> int | None:
    """The curated context window for a model, or ``None`` for a free-text repo not in
    the catalog (the caller falls back to the adapter's hint)."""
    entry = _entry_for(engine, repo)
    return entry.context_window if entry is not None else None
