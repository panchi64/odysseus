"""MlxAdapter — the Apple-Silicon speed upgrade (chat + vision, arm64 macOS).

Serves ``mlx-community/*`` MLX models via ``mlx-vlm``'s OpenAI-compatible server.
mlx-vlm pulls the whole MLX stack (mlx, mlx-lm, mlx-audio, transformers, torch-free but
heavy), so it is *not* a backend dependency: the adapter installs it into an **isolated,
adapter-owned venv** under ``data/serving/engines/mlx/`` (created with ``uv`` on a pinned
3.12 interpreter, decoupled from the backend's Python 3.14) and launches that venv's
console script. Embeddings stay on llama.cpp everywhere for one uniform GGUF embedding
stack, even though mlx-vlm exposes an embeddings route (see the package CLAUDE.md).

Vision is a real workload here, not an aspiration: mlx-vlm is a VLM server first, so the
same argv serves a text-only MLX chat model and a multimodal one. Which of the two a
snapshot actually is can't be read off the declared workload, so ``detect_vision`` reads
it from the model's own ``config.json``.

Two things are asked of the running server rather than assumed, both from ``/health``
(which sits at the **root**, not under the ``/v1`` prefix): the context window it settled
on, and whether the loaded model's chat template carries a tool parser at all. And the
readiness contract is unusual — mlx-vlm loads the model inside its FastAPI lifespan and
uvicorn binds the socket only after lifespan startup, so **the port opening already means
the weights are resident**, and a large model's whole load sits inside the startup budget.

MLX is Apple-Silicon only: ``is_available()`` is False off arm64 macOS, so the engine is
present-but-unavailable elsewhere and the service degrades cleanly rather than erroring
(XC-PORT-1/XC-DEG-*). All failures raise ``ServingError`` with an actionable hint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
from pathlib import Path

import httpx

from core.exceptions import ServingError

from .. import hf
from ..download import DownloadSpec, worker_spec
from ..models import (
    EngineKind,
    KvCacheType,
    LaunchOptions,
    SpeculativeMode,
    Workload,
    emit_flag,
    flag_names,
)
from ..paths import ServingPaths
from ..supervisor import ServeSpec
from .base import EngineAdapter

logger = logging.getLogger(__name__)

# The neutral KV-cache precisions, as the bit widths mlx-vlm's --kv-bits takes. f16 is
# absent on purpose: it is mlx-vlm's own unquantized default, so it emits no flag.
_KV_BITS = {KvCacheType.q8_0: "8", KvCacheType.q4_0: "4"}

# Pinned to a known-good release on PyPI (MIT). Bump deliberately — a new release can
# shift CLI flags, the model-id convention, or the tool-parser surface the agent's
# tool-calling rides on.
_PIN = "0.6.15"
_REQUIREMENT = f"mlx-vlm=={_PIN}"
# mlx-vlm does not declare jinja2, but every chat request renders the model's chat
# template through it — without it the server starts, reports healthy, answers
# /v1/models, and then fails *every* completion with an import error. Installed
# explicitly rather than relied on transitively, since that is exactly how it went
# missing. Unpinned: it is a stable, widely-shared library and the resolver should be
# free to reuse a compatible version.
_REQUIREMENTS = [_REQUIREMENT, "jinja2"]
# The console script the package installs into its venv's bin/. mlx-vlm also exposes
# `python -m mlx_vlm server`; the script is the same entry point without the interpreter
# hop, so the supervisor's argv[0] is a file we can existence-check.
_SCRIPT = "mlx_vlm.server"
# The venv interpreter. mlx-vlm itself only requires >=3.10 — 3.12 is pinned because it
# is the interpreter this pin's wheel set is verified against, not because of a cap.
_VENV_PYTHON = "3.12"
_INSTALL_HINT = (
    "Ensure `uv` is installed and on PATH, then retry — MLX serving installs "
    f"{_REQUIREMENT} into an isolated venv under data/serving/engines/mlx/."
)


def _mtp_tensor_names(artifact: Path) -> list[str]:
    """The ``mtp.*`` tensors in a snapshot — the prefix mlx-vlm's own splitter looks for.

    Reads the safetensors **index** when there is one, and otherwise each shard's JSON
    header (a length prefix then the header; no weights are touched, so this costs the
    same on a 25GB model as a 250MB one). Never raises — an unreadable snapshot reports
    no MTP, which is the safe answer.
    """
    try:
        index = artifact / "model.safetensors.index.json"
        if index.is_file():
            weight_map = json.loads(index.read_text()).get("weight_map") or {}
            return [k for k in weight_map if k.startswith("mtp.")]
        names: list[str] = []
        for shard in sorted(artifact.glob("*.safetensors")):
            with open(shard, "rb") as fh:
                header_len = int.from_bytes(fh.read(8), "little")
                if header_len <= 0 or header_len > (1 << 26):
                    continue
                header = json.loads(fh.read(header_len))
            names += [k for k in header if k.startswith("mtp.")]
        return names
    except (OSError, ValueError, TypeError) as exc:
        logger.info("serving: could not read tensor names from %s: %s", artifact, exc)
        return []


class MlxAdapter(EngineAdapter):
    kind = EngineKind.mlx
    workloads = frozenset({Workload.chat, Workload.vision})
    native_tools_default = True
    # mlx-community chat models are typically 32K-context (Qwen2.5/Llama 3.1 8B go higher);
    # a conservative hint the registered endpoint carries only when the running server
    # can't be asked — `probe_context_window` replaces it on every serve.
    context_window_hint = 32768
    # `cache_reuse` has no equivalent: mlx-vlm's prefix cache is automatic and always on,
    # so there is no minimum-reuse knob to set.
    supported_options = frozenset(
        {"context_size", "kv_cache_type", "speculative", "draft_model"}
    )
    owned_flags = frozenset({"--model", "--host", "--port"})
    # mlx-vlm loads the model inside its FastAPI lifespan, and uvicorn runs lifespan
    # startup *before* it binds the socket — so the port opening already means "weights
    # resident", and a large model's entire load has to fit in this budget.
    startup_timeout_s = 900.0

    def __init__(self, paths: ServingPaths) -> None:
        self._paths = paths
        self._script: str | None = None

    async def is_available(self) -> bool:
        # Apple Silicon only — MLX rides Metal on arm64 macOS. Everywhere else the engine
        # is present-but-unavailable (the service degrades, never crashes).
        return platform.system() == "Darwin" and platform.machine() == "arm64"

    async def is_installed(self) -> bool:
        # The isolated venv's server script is already built — serving won't run uv.
        return await self.is_available() and self._locate() is not None

    async def ensure_engine(self) -> None:
        if self._script and Path(self._script).exists():
            return
        located = self._locate()
        if located:
            self._script = located
            return
        logger.info("serving: creating an isolated MLX venv and installing %s", _REQUIREMENT)
        self._script = await asyncio.to_thread(self._install)

    def download_spec(
        self, repo: str, quant: str | None, dest: Path, token: str | None = None
    ) -> DownloadSpec:
        # MLX serves a safetensors snapshot, not a single quantized file — quant is baked
        # into the repo (e.g. `…-4bit`), so the worker fetches the whole repo snapshot.
        return worker_spec("snapshot", repo, dest, token=token)

    def download_size(
        self, repo: str, quant: str | None, token: str | None = None
    ) -> int | None:
        # MLX fetches the whole repo snapshot — size every sibling file.
        return hf.snapshot_size(repo, token=token)

    def serve_spec(
        self,
        artifact: Path,
        port: int,
        workload: Workload,
        model_id: str,
        options: LaunchOptions | None = None,
    ) -> ServeSpec:
        if self._script is None:
            raise ServingError("MLX is not initialized (call ensure_engine first)")
        opts = options or LaunchOptions()
        overrides = flag_names(opts.extra_args)
        argv = [
            self._script,
            # Pre-loads the model at startup, inside the server's lifespan — so the
            # supervisor's /v1/models readiness probe only answers once weights are
            # resident, and the first request doesn't pay the load.
            "--model", str(artifact),
            # mlx-vlm defaults to 0.0.0.0; bind loopback explicitly.
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        # The neutral fields, in mlx-vlm's vocabulary. Each is skipped when the operator's
        # extra arguments already name it, so an override reaches the engine once.
        if opts.context_size is not None:
            # mlx-vlm has no total-context flag: it bounds the KV cache instead, which is
            # the same thing from the operator's side — the tokens one request may hold.
            argv += emit_flag(
                "--max-kv-size", [str(opts.context_size)],
                aliases=frozenset({"--max-kv-size"}), overrides=overrides,
            )
        # mlx-vlm quantizes the cache by bit width rather than by dtype name; f16 is its
        # unquantized default and maps to no flag at all.
        kv_bits = _KV_BITS.get(opts.kv_cache_type) if opts.kv_cache_type else None
        if kv_bits is not None:
            argv += emit_flag(
                "--kv-bits", [kv_bits],
                aliases=frozenset({"--kv-bits"}), overrides=overrides,
            )
        argv += self._speculative_args(artifact, opts, overrides)
        argv += opts.extra_args
        return ServeSpec(argv=argv, cwd=Path(self._script).parent)

    def _speculative_args(
        self, artifact: Path, opts: LaunchOptions, overrides: set[str]
    ) -> list[str]:
        """Draft-token flags for MLX, which packages MTP differently from llama.cpp.

        The MLX conversion pipeline **splits the MTP head out** of the checkpoint into its
        own small companion repo (``mlx-community/Qwen3.8-27B-MTP-4bit`` beside
        ``mlx-community/Qwen3.8-27B-4bit``, ~240MB), so a converted model almost never
        carries its own MTP tensors — the operator names the drafter instead. The head
        alone isn't runnable: it borrows the target's token embeddings and LM head at
        runtime, which is why it has to pair with a drafter built from the *same*
        checkpoint.

        ``--draft-kind`` is deliberately not passed: mlx-vlm reads the drafter's own
        ``model_type`` and picks the round-loop for it, and would override a wrong guess
        anyway. A checkpoint that *does* still carry ``mtp.*`` tensors can be split into a
        drafter with mlx-vlm's own ``…drafters.qwen3_5_mtp.split``; we don't do that
        implicitly, because it writes a second copy of the weights.
        """
        if opts.speculative is SpeculativeMode.off or not opts.draft_model:
            return []
        if overrides & {"--draft-model", "--draft-kind"}:
            return []  # the operator is driving this themselves
        return ["--draft-model", opts.draft_model]

    def mtp_layers(self, artifact: Path) -> int:
        """MTP layers this snapshot carries in its own weights (0 = none, the usual case
        for an MLX conversion).

        Read from the tensor names, never from the config: a converted checkpoint keeps
        ``mtp_num_hidden_layers`` in ``config.json`` long after the conversion dropped the
        tensors, so the config alone reports MTP on models that plainly don't have it."""
        return len(_mtp_tensor_names(artifact))

    def describe_speculative(self, artifact: Path) -> str | None:
        if self.mtp_layers(artifact):
            return "MTP tensors in the weights (split them into a drafter to use them)"
        return None

    async def probe_context_window(self, port: int) -> int | None:
        """The context the loaded model actually settled on, read from mlx-vlm's
        ``/health``. `effective_context_limit` is the honest number — it already folds a
        `--max-kv-size` cap into the model's own declared window — so the launch flag
        alone can't stand in for it. Best-effort: ``None`` leaves the hint in place."""
        payload = await self._health(port)
        if not isinstance(payload, dict):
            return None
        for key in ("effective_context_limit", "loaded_context_size", "configured_context_limit"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return None

    async def probe_native_tools(self, port: int) -> bool:
        """Whether the loaded model's chat template carries a tool parser, read from
        ``/health``. mlx-vlm infers the parser from the processor at load time and reports
        it as ``loaded_tool_parser``; a null one means tool calls would never be produced,
        however well-formed the request.

        Only a payload that actually carries the key downgrades the default — an
        unreachable server or an mlx-vlm without the field must not silently break a role
        binding that already worked."""
        payload = await self._health(port)
        if isinstance(payload, dict) and "loaded_tool_parser" in payload:
            return bool(payload["loaded_tool_parser"])
        return self.native_tools_default

    async def _health(self, port: int) -> object | None:
        """mlx-vlm's ``/health`` body, or ``None``. Note it sits at the root, *not* under
        the ``/v1`` prefix ``health_url`` builds for the OpenAI surface."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://127.0.0.1:{port}/health")
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("serving: could not read /health on port %s: %s", port, exc)
            return None

    def detect_vision(self, artifact: Path, workload: Workload) -> bool:
        """Whether this snapshot is a vision model, read from its own ``config.json``.
        mlx-vlm serves text-only and multimodal checkpoints through the identical launch,
        so the declared workload can't tell them apart — but a VLM's config carries a
        ``vision_config`` block, which is the same signal mlx-vlm itself loads on."""
        if workload == Workload.vision:
            return True
        try:
            config = json.loads((artifact / "config.json").read_text())
        except (OSError, ValueError):
            return False
        return isinstance(config, dict) and bool(config.get("vision_config"))

    def validate_artifact(self, path: Path) -> None:
        # MLX serves a snapshot directory. The shape checked here is the one mlx-vlm's own
        # model listing uses to decide a checkpoint is loadable.
        if not path.exists():
            raise ServingError(f"there is nothing at {path}")
        if not path.is_dir():
            raise ServingError(
                f"{path.name} is a file — MLX serves a model folder (the snapshot "
                "directory holding config.json and the safetensors weights)"
            )
        if not (path / "config.json").is_file():
            raise ServingError(f"{path} has no config.json — it isn't an MLX model folder")
        if not any(path.glob("*.safetensors")):
            raise ServingError(f"{path} has no .safetensors weights — nothing to serve")

    def resolved_model_id(self, repo: str, artifact: Path) -> str:
        # mlx-vlm has no --served-model-name: it identifies a model by the path (or repo
        # id) it was loaded from, and resolves a request's `model` the same way — an
        # unrecognized value would send it to the HuggingFace cache for a *different*
        # model. So the served id is the local snapshot path we launched with, which is
        # what /v1/models advertises and what requests must ask for.
        return str(artifact)

    # --- venv resolution --------------------------------------------------

    def _venv_dir(self) -> Path:
        return self._paths.engine_dir(self.kind.value) / "venv"

    def _script_path(self) -> Path:
        # uv-created venvs use POSIX `bin/`; this adapter only runs on macOS, where that
        # always holds.
        return self._venv_dir() / "bin" / _SCRIPT

    def _locate(self) -> str | None:
        script = self._script_path()
        return str(script) if script.is_file() else None

    def _install(self) -> str:
        """Create the isolated venv (if absent) and install the pinned server into it.
        Blocking — run in a thread. Raises ``ServingError`` with the uv output on
        failure. Idempotent: a present-and-installed venv short-circuits via ``_locate``."""
        venv_dir = self._venv_dir()
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        # `uv venv` is idempotent — it reuses an existing venv. Built on the pinned
        # interpreter rather than the backend's 3.14, so the MLX wheel set resolves.
        self._uv(["venv", "--python", _VENV_PYTHON, str(venv_dir)])
        self._uv(["pip", "install", "--python", str(self._script_path().parent / "python"),
                  *_REQUIREMENTS])
        script = self._script_path()
        if not script.is_file():
            raise ServingError(
                f"installed {_REQUIREMENT} but its `{_SCRIPT}` script is missing. "
                f"{_INSTALL_HINT}"
            )
        return str(script)

    def _uv(self, args: list[str]) -> None:
        """Run a ``uv`` subcommand, cross-platform (no shell). Raises ``ServingError``
        with the captured output on a non-zero exit or a missing ``uv``."""
        import subprocess  # noqa: PLC0415 — local to keep the import off the hot path

        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted input
                ["uv", *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise ServingError(f"could not run uv: {exc}. {_INSTALL_HINT}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ServingError(
                f"`uv {' '.join(args[:2])}` failed for the MLX venv: {detail}. "
                f"{_INSTALL_HINT}"
            )
