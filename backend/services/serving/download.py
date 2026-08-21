"""Off-request model downloads — lock-aware, polled progress, killable.

A download is one long job per managed model: a background task that waits for the vault
to unlock (model files land under ``data/``), runs the blocking HuggingFace fetch in a
**child process** so it can be killed cleanly, and exposes a progress snapshot the status
endpoint polls. Cancelling a job kills the child (and its group) and drops the partial
artifact — unlike a worker thread, which can't be interrupted mid-fetch.

The child is described by a ``DownloadSpec`` (an argv, like the supervisor's ``ServeSpec``)
each adapter supplies, so the engine-specific fetch logic stays in the adapter/worker and
this manager stays engine-agnostic. The worker reports two control lines on stdout —
``TOTAL <bytes>`` (when known) and ``ARTIFACT <path>`` (on success); progress is polled
from the destination's on-disk size, so it stays decoupled from ``huggingface_hub``.
Transient failures retry with bounded backoff.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from core.backoff import backoff_delay
from core.vault import Vault

from .models import DownloadProgress, ServeState
from .paths import dir_size

logger = logging.getLogger(__name__)

# on_complete(artifact_path | None, error | None): persist the terminal outcome.
OnComplete = Callable[[Path | None, str | None], Awaitable[None]]

# The backend code root (parent of the ``services`` package) — the cwd the worker child
# runs in so ``python -m services.serving.download_worker`` resolves.
_CODE_ROOT = Path(__file__).resolve().parents[2]
_WORKER_MODULE = "services.serving.download_worker"


@dataclass(frozen=True)
class DownloadSpec:
    """How to launch the child process that fetches one model's artifact into ``dest``."""

    argv: list[str]
    env: dict[str, str] | None = None
    cwd: Path | None = None


def worker_spec(
    mode: str, repo: str, dest: Path, *, quant: str | None = None, token: str | None = None
) -> DownloadSpec:
    """A spec that runs the bundled HuggingFace download worker — used by the real engine
    adapters (the test double returns its own stub spec). ``mode`` is ``file`` (a single
    GGUF, llama.cpp) or ``snapshot`` (a repo tree, MLX). An optional ``token`` (never
    required — only for faster downloads + gated repos) rides the child env as
    ``HF_TOKEN``, which ``huggingface_hub`` picks up automatically."""
    argv = [
        sys.executable, "-m", _WORKER_MODULE,
        "--mode", mode, "--repo", repo, "--dest", str(dest),
    ]
    if quant:
        argv += ["--quant", quant]
    # Quiet HF's tqdm so the child's stdout carries only our control lines.
    env = {**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
    if token:
        env["HF_TOKEN"] = token
    return DownloadSpec(argv=argv, env=env, cwd=_CODE_ROOT)


class DownloadFailed(Exception):
    """A download attempt failed (retryable up to the cap)."""


@dataclass
class _Job:
    progress: DownloadProgress
    state: ServeState
    task: asyncio.Task | None = None


class DownloadManager:
    def __init__(
        self,
        vault: Vault,
        *,
        poll_interval_s: float = 1.0,
        max_attempts: int = 3,
        base_backoff_s: float = 1.0,
    ) -> None:
        self._vault = vault
        self._poll_interval_s = poll_interval_s
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s
        self._jobs: dict[str, _Job] = {}

    def progress(self, managed_id: str) -> DownloadProgress | None:
        job = self._jobs.get(managed_id)
        return job.progress if job else None

    def is_active(self, managed_id: str) -> bool:
        job = self._jobs.get(managed_id)
        return bool(job and job.task and not job.task.done())

    def start(
        self,
        managed_id: str,
        dest: Path,
        *,
        spec: DownloadSpec,
        on_complete: OnComplete,
    ) -> None:
        """Schedule (or restart) the download of one managed model."""
        self._discard(managed_id)
        job = _Job(progress=DownloadProgress(), state=ServeState.downloading)
        job.task = asyncio.create_task(self._run(managed_id, job, dest, spec, on_complete))
        self._jobs[managed_id] = job

    async def wait(self, managed_id: str) -> None:
        """Block until the model's download settles (used by ``serve`` before launch).
        Leaves the job running if the waiter itself is cancelled."""
        job = self._jobs.get(managed_id)
        if job and job.task:
            await asyncio.wait({job.task})

    async def cancel(self, managed_id: str) -> None:
        job = self._jobs.get(managed_id)
        if job and job.task and not job.task.done():
            job.task.cancel()
            with suppress(asyncio.CancelledError):
                await job.task

    async def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            if job.task and not job.task.done():
                job.task.cancel()
                with suppress(asyncio.CancelledError):
                    await job.task

    def _discard(self, managed_id: str) -> None:
        job = self._jobs.pop(managed_id, None)
        if job and job.task and not job.task.done():
            job.task.cancel()

    async def _run(
        self,
        managed_id: str,
        job: _Job,
        dest: Path,
        spec: DownloadSpec,
        on_complete: OnComplete,
    ) -> None:
        try:
            # Park until the vault is unlocked — model files land under data/, and a
            # download is only useful once the operator is actually working anyway.
            await self._vault.unlocked_event.wait()
            artifact = await self._download(job, dest, spec)
            if job.progress.total_bytes:
                job.progress.downloaded_bytes = job.progress.total_bytes
            job.progress.fraction = 1.0
            job.state = ServeState.stopped
            await on_complete(artifact, None)
        except asyncio.CancelledError:
            # Killed mid-fetch — drop the partial artifact so a later serve re-downloads
            # cleanly rather than launching against a truncated file.
            job.state = ServeState.error
            await asyncio.to_thread(_remove_dir, dest)
            raise
        except Exception as exc:  # noqa: BLE001 — any failure is reported, not raised on
            logger.exception("serving: download failed for %s", managed_id)
            job.state = ServeState.error
            with suppress(Exception):
                await on_complete(None, str(exc))

    async def _download(self, job: _Job, dest: Path, spec: DownloadSpec) -> Path:
        attempt = 0
        while True:
            attempt += 1
            dest.mkdir(parents=True, exist_ok=True)
            try:
                return await self._run_once(job, dest, spec)
            except asyncio.CancelledError:
                raise
            except DownloadFailed:
                if attempt >= self._max_attempts:
                    raise
                await asyncio.sleep(backoff_delay(self._base_backoff_s, attempt))

    async def _run_once(self, job: _Job, dest: Path, spec: DownloadSpec) -> Path:
        try:
            proc = await asyncio.create_subprocess_exec(
                *spec.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=spec.env,
                cwd=str(spec.cwd) if spec.cwd else None,
                start_new_session=True,  # own process group, so cancel kills the whole tree
            )
        except OSError as exc:
            # A transient spawn failure (EAGAIN, too many fds, fork failure) is retryable,
            # like any other download attempt — surface it as such, not a hard error.
            raise DownloadFailed(f"could not start the download worker: {exc}") from exc
        holder: dict[str, str] = {}
        tail: deque[str] = deque(maxlen=20)
        reader = asyncio.ensure_future(self._read_control(proc, job, holder, tail))
        poller = asyncio.ensure_future(self._poll(job, dest, proc))
        try:
            returncode = await proc.wait()
        except asyncio.CancelledError:
            _kill_group(proc)
            with suppress(Exception):
                await proc.wait()
            raise
        finally:
            poller.cancel()
            with suppress(asyncio.CancelledError):
                await poller
            with suppress(Exception):
                await reader  # drains to EOF, capturing the artifact line + error tail
        if returncode != 0:
            raise DownloadFailed("\n".join(tail) or f"the downloader exited with code {returncode}")
        artifact = holder.get("artifact")
        if artifact is None:
            raise DownloadFailed("the downloader did not report an artifact")
        return Path(artifact)

    async def _read_control(
        self, proc: asyncio.subprocess.Process, job: _Job, holder: dict[str, str], tail: deque[str]
    ) -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip("\n")
            if line.startswith("TOTAL "):
                with suppress(ValueError):
                    job.progress.total_bytes = int(line[len("TOTAL ") :].strip())
            elif line.startswith("ARTIFACT "):
                holder["artifact"] = line[len("ARTIFACT ") :].strip()
            elif line.strip():
                tail.append(line)

    async def _poll(self, job: _Job, dest: Path, proc: asyncio.subprocess.Process) -> None:
        while proc.returncode is None:
            size = await asyncio.to_thread(dir_size, dest)
            job.progress.downloaded_bytes = size
            if job.progress.total_bytes:
                job.progress.fraction = min(1.0, size / job.progress.total_bytes)
            await asyncio.sleep(self._poll_interval_s)


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the child's process group (POSIX). Downloads carry no state worth a
    graceful stop, and the partial artifact is removed by the caller."""
    with suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def _remove_dir(path: Path) -> None:
    import shutil  # noqa: PLC0415 — local to keep the import off the hot path

    with suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)
