"""The download manager — lock-aware, polled-progress, killable subprocess fetches.

The real fetch runs in a child process (so a cancel can kill it); these tests drive the
manager with tiny ``python -c`` stub children instead of the HuggingFace worker, so they
exercise the spawn/progress/cancel/retry lifecycle with no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from services.serving.download import DownloadManager, DownloadSpec
from services.serving.models import ServeState
from services.serving.paths import dir_size


def _vault(*, unlocked: bool = True) -> SimpleNamespace:
    event = asyncio.Event()
    if unlocked:
        event.set()
    return SimpleNamespace(unlocked_event=event)


def _manager(vault, **kw) -> DownloadManager:
    return DownloadManager(vault, poll_interval_s=0.01, base_backoff_s=0.0, **kw)


def _stub_spec(dest: Path, *, total: int = 100, nbytes: int = 100) -> DownloadSpec:
    """A child that writes an artifact and prints the manager's control lines."""
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "d = Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'model.gguf').write_bytes(b'x' * {nbytes})\n"
        f"print('TOTAL {total}', flush=True)\n"
        "print('ARTIFACT ' + str(d / 'model.gguf'), flush=True)\n"
    )
    return DownloadSpec(argv=[sys.executable, "-c", code, str(dest)])


def _failing_spec(dest: Path, counter: Path) -> DownloadSpec:
    """A child that records the attempt and exits non-zero with an error on stderr."""
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        f"c = Path(r'{counter}')\n"
        "c.write_bytes((c.read_bytes() if c.exists() else b'') + b'x')\n"
        "sys.stderr.write('boom\\n')\n"
        "sys.exit(1)\n"
    )
    return DownloadSpec(argv=[sys.executable, "-c", code, str(dest)])


def _sleep_spec(dest: Path) -> DownloadSpec:
    """A child that drops a partial file then blocks — to be killed by a cancel."""
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "d = Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True)\n"
        "(d / 'partial').write_bytes(b'x')\n"
        "time.sleep(30)\n"
    )
    return DownloadSpec(argv=[sys.executable, "-c", code, str(dest)])


async def test_download_completes_and_reports_progress(tmp_path: Path):
    mgr = _manager(_vault())
    done = asyncio.Event()
    result: dict = {}

    async def on_complete(artifact, error):
        result["artifact"], result["error"] = artifact, error
        done.set()

    dest = tmp_path / "m1"
    mgr.start("m1", dest, spec=_stub_spec(dest), on_complete=on_complete)
    await asyncio.wait_for(done.wait(), timeout=10)

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

    dest = tmp_path / "m"
    mgr.start("m", dest, spec=_stub_spec(dest), on_complete=on_complete)
    await asyncio.sleep(0.1)
    assert not done.is_set()  # parked while locked

    vault.unlocked_event.set()
    await asyncio.wait_for(done.wait(), timeout=10)
    assert result["artifact"].name == "model.gguf"


async def test_download_reports_error_after_retries(tmp_path: Path):
    mgr = _manager(_vault(), max_attempts=2)
    done = asyncio.Event()
    result: dict = {}
    counter = tmp_path / "attempts"

    async def on_complete(artifact, error):
        result["artifact"], result["error"] = artifact, error
        done.set()

    dest = tmp_path / "m"
    mgr.start("m", dest, spec=_failing_spec(dest, counter), on_complete=on_complete)
    await asyncio.wait_for(done.wait(), timeout=10)

    assert result["artifact"] is None and "boom" in result["error"]
    assert counter.read_bytes() == b"xx"  # retried up to the cap
    assert mgr._jobs["m"].state == ServeState.error


async def test_cancel_kills_the_child_and_drops_partial(tmp_path: Path):
    mgr = _manager(_vault())
    completed = asyncio.Event()

    async def on_complete(artifact, error):
        completed.set()

    dest = tmp_path / "m"
    mgr.start("m", dest, spec=_sleep_spec(dest), on_complete=on_complete)
    # Wait until the child is genuinely running (it has written its partial file).
    for _ in range(300):
        if (dest / "partial").exists():
            break
        await asyncio.sleep(0.02)
    assert (dest / "partial").exists()

    await mgr.cancel("m")
    assert not mgr.is_active("m")
    assert not completed.is_set()  # a cancelled download never reports completion
    assert not dest.exists()  # the partial artifact was dropped


async def test_download_retries_when_the_worker_cant_spawn(tmp_path: Path, monkeypatch):
    # A transient spawn failure (OSError from create_subprocess_exec) must be retried up
    # to the cap, not fail the download on the first attempt.
    mgr = _manager(_vault(), max_attempts=3)
    calls = {"n": 0}

    async def boom(*args, **kwargs):
        calls["n"] += 1
        raise OSError("cannot fork")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)

    done = asyncio.Event()
    result: dict = {}

    async def on_complete(artifact, error):
        result["artifact"], result["error"] = artifact, error
        done.set()

    dest = tmp_path / "m"
    mgr.start("m", dest, spec=_stub_spec(dest), on_complete=on_complete)
    await asyncio.wait_for(done.wait(), timeout=10)

    assert result["artifact"] is None and "could not start" in result["error"]
    assert calls["n"] == 3  # retried up to the cap, not failed on the first spawn error


def test_dir_size_excludes_hf_cache(tmp_path: Path):
    assert dir_size(tmp_path / "missing") == 0
    (tmp_path / "a").write_bytes(b"123")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"45")
    # HuggingFace stages blobs under <local_dir>/.cache — excluded from the size.
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "blob").write_bytes(b"ignored!")
    assert dir_size(tmp_path) == 5
