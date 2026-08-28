"""EngineAdapter — the pluggable seam each inference engine implements.

An adapter knows how to make its engine available, how to download a model in its
format, how to launch the OpenAI-compatible server for it, and what model id that
server answers to. Everything around it (supervision, persistence, the registry
endpoint) is engine-agnostic and lives in the service. llama.cpp is the universal
baseline; MLX is the Apple-Silicon speed adapter (added later). Both are MIT.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.exceptions import InvalidInputError

from ..download import DownloadSpec
from ..models import EngineKind, LaunchOptions, Workload, validate_extra_args
from ..supervisor import ServeSpec


class EngineAdapter(ABC):
    kind: EngineKind
    workloads: frozenset[Workload]
    # Capability defaults seeded onto the registered endpoint. Tool-driving roles
    # require native tool-calling (AE-8.1); the operator is expected to point chat
    # roles at instruct models that support it.
    native_tools_default: bool = True
    context_window_hint: int | None = None

    # --- launch-option vocabulary ----------------------------------------
    # Kept beside the adapter that emits the flags, so adding an engine can't leave a
    # central table of someone else's flag names behind.

    # LaunchOptions field names this engine can actually translate. Anything else is
    # rejected by name rather than stored as tuning that never reaches a process.
    supported_options: frozenset[str] = frozenset()
    # Flags the adapter emits itself and the operator may never override: they define
    # the served model's identity and pin it to loopback.
    owned_flags: frozenset[str] = frozenset()
    # How long this engine may take between spawn and serving. Engines differ by more
    # than jitter: llama.cpp binds its port and then mmaps, while mlx-vlm loads the whole
    # model inside its lifespan *before* uvicorn binds, so a large model's entire load
    # sits inside this budget.
    startup_timeout_s: float = 180.0

    def validate_options(self, options: LaunchOptions | None) -> None:
        """Reject launch overrides this engine can't honour, by field name, then check
        the verbatim arguments against :attr:`owned_flags`. Raises ``InvalidInputError`` —
        a flag aimed at an engine that can't use it is the operator's to correct, not an
        engine fault, and the tuning form shows the message inline.

        Refusing beats storing: a stored-but-undeliverable option leaves the row carrying
        tuning that never reaches a process while the form renders it as applied. An
        all-empty ``LaunchOptions`` is always fine — it asks for nothing."""
        if options is None:
            return
        unsupported = sorted(
            set(options.model_dump(exclude_defaults=True)) - {"extra_args"} - self.supported_options
        )
        if unsupported:
            raise InvalidInputError(
                f"the {self.kind.value} engine has no equivalent for "
                f"{', '.join(unsupported)} — clear it, or pass the engine's own flag "
                "in the extra arguments"
            )
        validate_extra_args(options.extra_args, owned=self.owned_flags)

    def validate_artifact(self, path: Path) -> None:
        """Confirm ``path`` is a model this engine can actually load — the gate on
        importing weights the operator already has on disk. Raises ``InvalidInputError``
        with what was expected. The default accepts anything that exists; an adapter that
        knows its own format overrides."""
        if not path.exists():
            raise InvalidInputError(f"there is nothing at {path}")

    @abstractmethod
    async def is_available(self) -> bool:
        """Whether this engine can run on this host at all (platform supported + the
        runtime is present or can be obtained). ``True`` doesn't imply it's installed —
        see :meth:`is_installed`."""

    async def is_installed(self) -> bool:
        """Whether the runtime is already present locally, so serving won't pay an
        install/download step first. Distinct from :meth:`is_available` (which allows a
        fetchable-but-absent runtime); the recommendation surface uses the pair to show
        'ready' vs 'will install on first use'. Defaults to not-installed; adapters that
        can cheaply locate their runtime override this."""
        return False

    @abstractmethod
    async def ensure_engine(self) -> None:
        """Make the engine runtime present (locate or install it). Raises
        ``ServingError`` if it can't be made available."""

    @abstractmethod
    def download_spec(
        self, repo: str, quant: str | None, dest: Path, token: str | None = None
    ) -> DownloadSpec:
        """How to launch the child process that fetches the model (in this engine's
        format) into ``dest`` — run and killed by the download manager. ``token`` is the
        operator's optional HuggingFace token (faster downloads + gated repos)."""

    def download_size(
        self, repo: str, quant: str | None, token: str | None = None
    ) -> int | None:
        """Best-effort total download footprint in bytes, for the pre-flight headroom
        guard (blocking — run in a thread). ``None`` when it can't be determined, so the
        guard degrades toward allowing. Real adapters query the HuggingFace API in their
        own format (one GGUF file vs the whole snapshot); the default declines to size."""
        return None

    def list_quants(self, repo: str, token: str | None = None) -> list[str]:
        """The distinct quantizations this engine could serve from ``repo``, for the
        picker's quant dropdown (blocking — run in a thread). Best-effort: ``[]`` when the
        engine bakes the quant into the repo id (MLX) or the listing can't be obtained, so
        the UI degrades to the engine's default pick. llama.cpp overrides to introspect
        the repo's GGUF files."""
        return []

    @abstractmethod
    def serve_spec(
        self,
        artifact: Path,
        port: int,
        workload: Workload,
        model_id: str,
        options: LaunchOptions | None = None,
    ) -> ServeSpec:
        """How to launch the OpenAI-compatible server for ``artifact`` on ``port``.

        ``options`` carries the operator's per-model launch overrides. It is optional so
        an adapter that has no use for them can ignore the parameter entirely; an adapter
        that does honour them must treat an unset field as "emit no flag", never as a
        value to invent."""

    async def probe_context_window(self, port: int) -> int | None:
        """The context window the running server actually settled on, asked of the server
        itself rather than inferred from the launch flags — the two differ whenever the
        engine splits a total context across parallel slots. Best-effort: ``None`` when
        the engine can't report it, so the endpoint falls back to
        :attr:`context_window_hint`."""
        return None

    async def probe_native_tools(self, port: int) -> bool:
        """Whether the *loaded* model can actually call tools, asked of the running
        server. Tool-calling is a property of the model's chat template, not of the
        engine, so an engine that can report it should — the alternative is a chat role
        bound to a model that silently never calls a tool. Best-effort: an engine that
        can't tell keeps :attr:`native_tools_default`."""
        return self.native_tools_default

    def describe_speculative(self, artifact: Path) -> str | None:
        """What draft-token capability these weights actually carry, phrased for the
        operator — or ``None`` when they carry none (blocking; run in a thread).

        Multi-token prediction is a *pretraining* property: a model either has the heads
        or it doesn't, and no flag can add them. It also can't be read off the config —
        conversions routinely keep ``mtp_num_hidden_layers`` in ``config.json`` long after
        dropping the tensors — so an adapter that answers this must look at the weights
        (or, for GGUF, the header) rather than the declaration."""
        return None

    def detect_vision(self, artifact: Path, workload: Workload) -> bool:
        """Whether the served model accepts images (blocking — run in a thread). The
        declared workload is the baseline; an adapter that can read the model's own
        config says so from the weights instead of from what was asked for."""
        return workload == Workload.vision

    @abstractmethod
    def resolved_model_id(self, repo: str, artifact: Path) -> str:
        """The model id the served endpoint answers to (stored as ``endpoint.model``
        and used as the server's alias so requests and the alias agree)."""

    def health_url(self, port: int) -> str:
        """The OpenAI-compatible base URL the endpoint points at."""
        return f"http://127.0.0.1:{port}/v1"
