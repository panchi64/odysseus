"""MlxAdapter — the Apple-Silicon speed upgrade (chat + vision, arm64 macOS).

Serves ``mlx-community/*`` MLX models via ``mlx-vlm``'s OpenAI-compatible server.
mlx-vlm pulls the whole MLX stack (mlx, mlx-lm, mlx-audio, transformers, torch-free but
heavy), so it is *not* a backend dependency: the adapter installs it into an **isolated,
adapter-owned venv** under ``data/serving/engines/mlx/`` (created with ``uv`` on a pinned
3.12 interpreter, decoupled from the backend's Python 3.14) and launches that venv's
console script. Embeddings stay on llama.cpp everywhere for one uniform GGUF embedding
stack, even though mlx-vlm exposes an embeddings route (see the package CLAUDE.md).

Vision is a real workload here, not an aspiration: mlx-vlm is a VLM server first, so the
same argv serves a text-only MLX chat model and a multimodal one — the workload only
decides how the endpoint is advertised to the agent.

MLX is Apple-Silicon only: ``is_available()`` is False off arm64 macOS, so the engine is
present-but-unavailable elsewhere and the service degrades cleanly rather than erroring
(XC-PORT-1/XC-DEG-*). All failures raise ``ServingError`` with an actionable hint.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path

from core.exceptions import ServingError

from .. import hf
from ..download import DownloadSpec, worker_spec
from ..models import EngineKind, LaunchOptions, Workload
from ..paths import ServingPaths
from ..supervisor import ServeSpec
from .base import EngineAdapter

logger = logging.getLogger(__name__)

# Pinned to a known-good release on PyPI (MIT). Bump deliberately — a new release can
# shift CLI flags, the model-id convention, or the tool-parser surface the agent's
# tool-calling rides on.
_PIN = "0.6.15"
_REQUIREMENT = f"mlx-vlm=={_PIN}"
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


class MlxAdapter(EngineAdapter):
    kind = EngineKind.mlx
    workloads = frozenset({Workload.chat, Workload.vision})
    native_tools_default = True
    # mlx-community chat models are typically 32K-context (Qwen2.5/Llama 3.1 8B go higher);
    # a conservative hint the registered endpoint can carry until the real value is known.
    context_window_hint = 32768

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
        # `options` is accepted but unused: the curated fields are spelled in llama.cpp's
        # flag vocabulary, and its extra_args validation is llama.cpp-shaped too, so
        # honouring them here would hand mlx-vlm flags it rejects at startup. mlx-vlm does
        # have its own near-equivalents (`--max-kv-size`, `--kv-bits`); wiring them is a
        # per-engine translation this adapter doesn't do yet.
        if self._script is None:
            raise ServingError("MLX is not initialized (call ensure_engine first)")
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
        return ServeSpec(argv=argv, cwd=Path(self._script).parent)

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
                  _REQUIREMENT])
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
