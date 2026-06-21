"""The download manager — lock-aware, polled-progress background fetches."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

from services.serving.download import DownloadManager, _dir_size
from services.serving.models import ServeState


def _vault(*, unlocked: bool = True) -> SimpleNamespace:
    event = asyncio.Event()
    if unlocked:
        event.set()
    return SimpleNamespace(unlocked_event=event)


def _manager(vault, **kw) -> DownloadManager:
    return DownloadManager(vault, poll_interval_s=0.01, base_backoff_s=0.0, **kw)


async def test_download_completes_and_reports_progress(tmp_path: Path):
    mgr = _manager(_vault())
    done = asyncio.Event()
    result: dict = {}

    async def on_complete(artifact, error):
        result["artifact"], result["error"] = artifact, error
        done.set()

    def run(dest: Path, set_total):
        set_total(100)
        (dest / "model.gguf").write_bytes(b"x" * 100)
        return dest / "model.gguf"

    mgr.start("m1", tmp_path / "m1", run=run, on_complete=on_complete)
    await asyncio.wait_for(done.wait(), timeout=5)

    assert result["error"] is None
    assert result["artifact"].name == "model.gguf"
    progress = mgr.progress("m1")
    assert progress is not None and progress.total_bytes == 100 and progress.fraction == 1.0
    assert not mgr.is_active("m1")


async def test_download_parks_until_vault_unlocks(tmp_path: Path):
    vault = _vault(unlocked=False)
    mgr = _manager(vault)
    done = asyncio.Event()
    result: dict = {}

    async def on_complete(artifact, error):
        result["artifact"] = artifact
        done.set()

    def run(dest: Path, set_total):
        (dest / "f").write_bytes(b"y")
        return dest / "f"

    mgr.start("m", tmp_path / "m", run=run, on_complete=on_complete)
    await asyncio.sleep(0.05)
    assert not done.is_set()  # parked while locked

    vault.unlocked_event.set()
    await asyncio.wait_for(done.wait(), timeout=5)
    assert result["artifact"].name == "f"


async def test_download_reports_error_after_retries(tmp_path: Path):
    mgr = _manager(_vault(), max_attempts=2)
    done = asyncio.Event()
    result: dict = {}
    calls = {"n": 0}

    async def on_complete(artifact, error):
        result["artifact"], result["error"] = artifact, error
        done.set()

    def run(dest: Path, set_total):
        calls["n"] += 1
        raise RuntimeError("boom")

    mgr.start("m", tmp_path / "m", run=run, on_complete=on_complete)
    await asyncio.wait_for(done.wait(), timeout=5)

    assert result["artifact"] is None and "boom" in result["error"]
    assert calls["n"] == 2  # retried up to the cap
    assert mgr.progress("m").total_bytes is None
    assert mgr._jobs["m"].state == ServeState.error


async def test_cancel_stops_the_job(tmp_path: Path):
    mgr = _manager(_vault())
    completed = asyncio.Event()
    # A worker thread can't be interrupted mid-flight, so gate it on an event the test
    # releases right after cancelling — the orphaned thread then exits before teardown.
    release = threading.Event()

    async def on_complete(artifact, error):
        completed.set()

    def run(dest: Path, set_total):
        release.wait(2)
        return dest / "f"

    mgr.start("m", tmp_path / "m", run=run, on_complete=on_complete)
    await asyncio.sleep(0.05)
    await mgr.cancel("m")
    assert not mgr.is_active("m")
    assert not completed.is_set()
    release.set()


def test_dir_size_sums_files_recursively(tmp_path: Path):
    assert _dir_size(tmp_path / "missing") == 0
    (tmp_path / "a").write_bytes(b"123")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"45")
    assert _dir_size(tmp_path) == 5
