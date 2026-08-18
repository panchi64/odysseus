"""Serving value types — engines, workloads, catalog entries, and views.

Plain Pydantic (nothing persisted here; the durable shape is
``models.serving.ManagedModel``). The load-bearing rule, borrowed from the
Cookbook: **degrade, don't crash** — an unavailable engine is reported as a
known-but-unavailable recommendation, never an error.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from core.exceptions import ServingError


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


class KvCacheType(StrEnum):
    """The KV cache dtypes offered for the ``-ctk``/``-ctv`` knob — a readable subset of
    what llama.cpp accepts. Quantizing the cache trades a little quality for a lot of the
    VRAM that long contexts eat."""

    f16 = "f16"  # the engine default
    q8_0 = "q8_0"
    q4_0 = "q4_0"


class LaunchOptions(BaseModel):
    """Per-model engine launch overrides.

    The load-bearing rule is **absent means absent**: every field left unset produces no
    flag at all, so the engine's own default stands. That matters more than it sounds —
    llama.cpp already auto-sizes the things worth auto-sizing (server slots, GPU layers,
    flash attention, continuous batching, prompt caching), and pinning them here would
    override that sizing rather than improve on it. Only knobs that are genuinely off by
    default are modelled; anything else the operator wants goes in ``extra_args``.
    """

    # Total context across all server slots. The one option the platform itself reasons
    # about: it is what lets a served endpoint declare a real context window.
    context_size: int | None = None
    kv_cache_type: KvCacheType | None = None
    cache_reuse: int | None = None
    # Passed to the engine verbatim, ahead of the flags the adapter owns. Unsupported by
    # design — the escape hatch for every flag this model doesn't name.
    extra_args: list[str] = Field(default_factory=list)


# Flags an operator may not set through ``extra_args``. The curated ones would silently
# disagree with the fields above; the adapter-owned ones define the served model's
# identity and its loopback binding (``--host 0.0.0.0`` would put the model server on the
# network, outside the assumption the rest of serving is built on).
_CURATED_FLAGS = frozenset(
    {"-c", "--ctx-size", "-ctk", "--cache-type-k", "-ctv", "--cache-type-v", "--cache-reuse"}
)
_ADAPTER_FLAGS = frozenset(
    {"-m", "--model", "--host", "--port", "--alias", "--jinja", "--embeddings"}
)


def validate_extra_args(args: list[str]) -> None:
    """Reject engine arguments that something else already owns, naming the flag so the
    operator can fix it. Raises ``ServingError``; a clean rejection at request time beats
    a spawn that quietly disagrees with the form above it."""
    for arg in args:
        # Tolerate `--flag=value` as well as `--flag value`.
        flag = arg.split("=", 1)[0]
        if flag in _CURATED_FLAGS:
            raise ServingError(
                f"{flag} is set by the fields above — remove it from the extra arguments"
            )
        if flag in _ADAPTER_FLAGS:
            raise ServingError(f"{flag} is managed by the platform and can't be overridden")


# Engines whose adapter actually honours LaunchOptions. The curated fields are
# llama.cpp's flag vocabulary; nothing else has an equivalent for them.
_TUNABLE_ENGINES = frozenset({EngineKind.llama_cpp})


def validate_options(engine: EngineKind, options: LaunchOptions | None) -> None:
    """Reject launch overrides the chosen engine would silently discard.

    Storing them would be worse than refusing them: the row would keep tuning that
    never reaches a process, and the UI would render it as though it had been applied.
    An all-empty ``LaunchOptions`` is always fine — it asks for nothing.
    """
    if options is None or engine in _TUNABLE_ENGINES:
        validate_extra_args(options.extra_args if options else [])
        return
    if options.model_dump(exclude_defaults=True):
        raise ServingError(f"the {engine.value} engine has no tunable launch options")


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
    # The launch overrides this model is (or will next be) served with, so the form can
    # show what it was last given rather than resetting to blank.
    options: LaunchOptions = Field(default_factory=LaunchOptions)
