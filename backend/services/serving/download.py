"""Off-request model downloads with lock-aware, polled progress.

A download is one long job per managed model: a background task that waits for the
vault to unlock (model files land under ``data/``), runs the blocking HuggingFace fetch
in a thread, and exposes a progress snapshot the status endpoint polls — the
``EmbeddingReindexer`` shape (one big job + a snapshot), not the write-behind queue
(many small items). Progress is read by polling the destination's on-disk size against a
best-effort total, so it stays decoupled from ``huggingface_hub`` internals. Transient
failures retry with bounded backoff; a job can be cancelled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from core.vault import Vault

from .models import DownloadProgress, ServeState

logger = logging.getLogger(__name__)

# run(dest, set_total) -> artifact_path. Blocking; executed in a worker thread. It does
# the actual fetch and may report the total size it expects via ``set_total``.
DownloadRun = Callable[[Path, Callable[[int | None], None]], Path]
# on_complete(artifact_path | None, error | None): persist the terminal outcome.
OnComplete = Callable[[Path | None, str | None], Awaitable[None]]


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
        run: DownloadRun,
        on_complete: OnComplete,
    ) -> None:
        """Schedule (or restart) the download of one managed model."""
        self._discard(managed_id)
        job = _Job(progress=DownloadProgress(), state=ServeState.downloading)
        job.task = asyncio.create_task(self._run(managed_id, job, dest, run, on_complete))
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
        run: DownloadRun,
        on_complete: OnComplete,
    ) -> None:
        try:
            # Park until the vault is unlocked — model files land under data/, and a
            # download is only useful once the operator is actually working anyway.
            await self._vault.unlocked_event.wait()
            dest.mkdir(parents=True, exist_ok=True)
            artifact = await self._download(job, dest, run)
            if job.progress.total_bytes:
                job.progress.downloaded_bytes = job.progress.total_bytes
            job.progress.fraction = 1.0
            job.state = ServeState.stopped
            await on_complete(artifact, None)
        except asyncio.CancelledError:
            job.state = ServeState.error
            raise
        except Exception as exc:  # noqa: BLE001 — any failure is reported, not raised on
            logger.exception("serving: download failed for %s", managed_id)
            job.state = ServeState.error
            with suppress(Exception):
                await on_complete(None, str(exc))

    async def _download(self, job: _Job, dest: Path, run: DownloadRun) -> Path:
        def set_total(n: int | None) -> None:
            job.progress.total_bytes = n

        attempt = 0
        while True:
            attempt += 1
            future = asyncio.ensure_future(asyncio.to_thread(run, dest, set_total))
            poller = asyncio.ensure_future(self._poll(job, dest, future))
            try:
                return await future
            except asyncio.CancelledError:
                future.cancel()
                raise
            except Exception:
                if attempt >= self._max_attempts:
                    raise
                await asyncio.sleep(self._base_backoff_s * 2 ** (attempt - 1))
            finally:
                poller.cancel()
                with suppress(asyncio.CancelledError):
                    await poller

    async def _poll(self, job: _Job, dest: Path, future: asyncio.Future) -> None:
        while not future.done():
            size = await asyncio.to_thread(_dir_size, dest)
            job.progress.downloaded_bytes = size
            if job.progress.total_bytes:
                job.progress.fraction = min(1.0, size / job.progress.total_bytes)
            await asyncio.sleep(self._poll_interval_s)


def _dir_size(path: Path) -> int:
    """Bytes currently on disk under ``path`` (incomplete temp files included)."""
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        with suppress(OSError):
            if child.is_file():
                total += child.stat().st_size
    return total
