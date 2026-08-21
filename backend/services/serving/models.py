"""Serving value types — engines, workloads, catalog entries, and views.

Plain Pydantic (nothing persisted here; the durable shape is
``models.serving.ManagedModel``). The load-bearing rule, borrowed from the
Cookbook: **degrade, don't crash** — an unavailable engine is reported as a
known-but-unavailable recommendation, never an error.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from core.exceptions import InvalidInputError


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
    """The precision the KV cache is held at — a readable subset of what the engines
    accept, spelled semantically rather than in one engine's flag vocabulary (llama.cpp
    takes a dtype on ``-ctk``/``-ctv``, mlx-vlm a bit width on ``--kv-bits``). Quantizing
    the cache trades a little quality for a lot of the VRAM that long contexts eat."""

    f16 = "f16"  # the engine default — emits no flag anywhere
    q8_0 = "q8_0"
    q4_0 = "q4_0"


class SpeculativeMode(StrEnum):
    """Whether to draft tokens ahead with the model's own multi-token-prediction head.

    MTP is a training-time property — a model either has the heads or it doesn't — so the
    useful default is ``auto``: enable it exactly when the artifact really carries it, and
    stay quiet otherwise. ``off`` is the escape hatch for a model whose MTP head is
    present but unhelpful (acceptance rates vary a lot by workload) or memory-tight.
    """

    auto = "auto"  # on when the weights actually carry it
    off = "off"


class LaunchOptions(BaseModel):
    """Per-model engine launch overrides, spelled as **engine-neutral semantics**.

    Each field names something an operator wants (the context window to hold, how
    precisely to keep the KV cache), and each adapter translates it into its own flags.
    An engine with no equivalent for a field rejects it by name rather than storing
    tuning that never reaches a process.

    The load-bearing rule is **absent means absent**: every field left unset produces no
    flag at all, so the engine's own default stands. That matters more than it sounds —
    the engines already auto-size the things worth auto-sizing (server slots, GPU layers,
    flash attention, continuous batching, prompt caching), and pinning them here would
    override that sizing rather than improve on it. Only knobs that are genuinely off by
    default are modelled; anything else the operator wants goes in ``extra_args``.
    """

    # The context/KV window the server should hold. The one option the platform itself
    # reasons about: it is what lets a served endpoint declare a real context window.
    context_size: int | None = None
    kv_cache_type: KvCacheType | None = None
    cache_reuse: int | None = None
    # Speculative decoding off the model's own MTP head. Unset means `auto` — the two
    # engines package MTP differently (llama.cpp ships the heads inside the GGUF, MLX
    # splits them into a companion drafter), so each adapter decides what auto means for
    # the artifact in front of it.
    speculative: SpeculativeMode | None = None
    # An explicit drafter, as a local path or a HuggingFace repo id. Required by MLX,
    # whose conversion pipeline splits the MTP head out of the checkpoint into its own
    # `…-MTP-<quant>` repo; llama.cpp needs it only for a separate draft *model*, since
    # its MTP heads travel inside the GGUF.
    draft_model: str | None = None
    # Passed to the engine verbatim. These **override** the fields above: an extra
    # argument naming a flag one of them would have emitted suppresses that emission, so
    # the operator's value is the only one on the command line. Unsupported by design —
    # the escape hatch for every flag this model doesn't name.
    extra_args: list[str] = Field(default_factory=list)


def flag_names(args: list[str]) -> set[str]:
    """The flags named by a verbatim argument list, tolerating ``--flag=value`` as well
    as ``--flag value``. Used to tell which curated emissions an operator overrode."""
    return {arg.split("=", 1)[0] for arg in args if arg.startswith("-")}


def validate_extra_args(args: list[str], *, owned: frozenset[str]) -> None:
    """Reject engine arguments the platform itself owns, naming the flag so the operator
    can fix it. Raises ``InvalidInputError`` — this is the operator's to correct, not an
    engine fault — and a clean rejection at request time beats a spawn that quietly
    disagrees with the rest of serving.

    Only ``owned`` flags are refused — they define the served model's identity and its
    loopback binding (``--host 0.0.0.0`` would put the model server on the network,
    outside the assumption the rest of serving is built on). A flag one of the curated
    fields would emit is deliberately *allowed*: that is the override.
    """
    for flag in flag_names(args):
        if flag in owned:
            raise InvalidInputError(
                f"{flag} is managed by the platform and can't be overridden"
            )


def emit_flag(flag: str, values: list[str], *, aliases: frozenset[str], overrides: set[str]):
    """One curated flag's argv fragment — empty when the operator's extra arguments
    already name it (or any of its ``aliases``), so their value is the only one passed.
    Shared by the adapters so the override rule is written once."""
    if overrides & aliases:
        return []
    return [flag, *values]


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
    # The LaunchOptions field names this engine honours, so the tuning form renders what
    # will actually reach a process instead of hardcoding what each engine can take.
    supported_options: list[str] = Field(default_factory=list)


class DownloadProgress(BaseModel):
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    fraction: float | None = None  # 0..1 when total is known
    file: str | None = None  # the file currently transferring


class ServeStage(StrEnum):
    """What a model in ``starting`` is actually doing. Both steps can run for minutes —
    an engine runtime is installed once per host, and weights load before the server
    binds its port — so the state flag alone reads as a stall."""

    installing_engine = "installing_engine"
    loading_model = "loading_model"


class ServeStageInfo(BaseModel):
    """The live stage of a starting model. In-memory only (like download progress): it
    describes an in-flight process, so it is meaningless after a restart."""

    stage: ServeStage
    started_at: datetime  # UTC — the UI derives elapsed from it
    timeout_s: float | None = None  # when this step gives up, for an honest wait


class ModelSource(StrEnum):
    """Where a managed model's artifact came from. ``local`` weights belong to the
    operator and live wherever they put them — we read them and never remove them."""

    huggingface = "huggingface"
    local = "local"


class ManagedModelView(BaseModel):
    """A managed model's live state — the LOCAL MODELS UI polls a list of these."""

    id: str
    engine: EngineKind
    workload: Workload
    hf_repo: str
    quant: str | None = None
    state: ServeState
    source: ModelSource = ModelSource.huggingface
    artifact_path: str | None = None
    endpoint_id: str | None = None
    endpoint_name: str | None = None
    port: int | None = None
    last_error: str | None = None
    progress: DownloadProgress | None = None
    stage: ServeStageInfo | None = None
    # What draft-token capability the downloaded weights carry, phrased for the operator
    # (None ⇒ none). Read from the artifact, so it is only known once it's on disk.
    speculative: str | None = None
    # The launch overrides this model is (or will next be) served with, so the form can
    # show what it was last given rather than resetting to blank.
    options: LaunchOptions = Field(default_factory=LaunchOptions)
