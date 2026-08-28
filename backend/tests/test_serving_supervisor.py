"""ProcessSupervisor — spawn/health/stop and crash detection, using the FakeAdapter stub."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from core.exceptions import ServingError
from services.serving.adapters.fake import FakeAdapter
from services.serving.models import Workload
from services.serving.supervisor import (
    EngineExitedDuringStartup,
    ProcessSupervisor,
    ServeSpec,
)


def _supervisor() -> ProcessSupervisor:
    return ProcessSupervisor(startup_timeout_s=15.0, stop_timeout_s=5.0, poll_interval_s=0.1)


async def _noop_crash(managed_id: str, returncode: int | None) -> None:
    return None


def test_allocate_port_returns_a_usable_port():
    port = _supervisor().allocate_port()
    assert 1024 < port < 65536


async def test_spawn_becomes_ready_then_stops_cleanly(tmp_path: Path):
    sup = _supervisor()
    port = sup.allocate_port()
    spec = FakeAdapter().serve_spec(tmp_path / "m.gguf", port, Workload.chat, "acme/m")
    crashes: list = []

    async def on_crash(managed_id: str, returncode: int | None) -> None:
        crashes.append((managed_id, returncode))

    proc = await sup.spawn(
        "m",
        spec,
        port,
        base_url=f"http://127.0.0.1:{port}/v1",
        on_crash=on_crash,
        log_path=tmp_path / "m.log",
    )
    assert proc.pid > 0 and sup.is_running("m")

    await sup.stop("m")
    assert not sup.is_running("m")
    assert crashes == []  # a deliberate stop must not fire the crash callback


async def test_watchdog_fires_when_the_engine_crashes(tmp_path: Path):
    sup = _supervisor()
    port = sup.allocate_port()
    spec = FakeAdapter().serve_spec(tmp_path / "m.gguf", port, Workload.chat, "acme/m")
    crashed = asyncio.Event()
    seen: dict = {}

    async def on_crash(managed_id: str, returncode: int | None) -> None:
        seen["managed_id"] = managed_id
        crashed.set()

    proc = await sup.spawn(
        "m", spec, port, base_url=f"http://127.0.0.1:{port}/v1",
        on_crash=on_crash, log_path=tmp_path / "m.log",
    )
    os.kill(proc.pid, signal.SIGKILL)  # external crash
    await asyncio.wait_for(crashed.wait(), timeout=5)
    assert seen["managed_id"] == "m"
    assert not sup.is_running("m")


async def test_spawn_raises_when_the_engine_never_serves(tmp_path: Path):
    sup = ProcessSupervisor(startup_timeout_s=1.0, poll_interval_s=0.1)
    port = sup.allocate_port()
    # Exits immediately without listening — startup must fail with the log tail.
    crash_now = "import sys; sys.stderr.write('nope'); sys.exit(1)"
    spec = ServeSpec(argv=[sys.executable, "-c", crash_now])
    with pytest.raises(ServingError):
        await sup.spawn(
            "m", spec, port, base_url=f"http://127.0.0.1:{port}/v1",
            on_crash=_noop_crash, log_path=tmp_path / "m.log",
        )
    assert not sup.is_running("m")


async def test_the_per_engine_timeout_overrides_the_constructor_default(tmp_path: Path):
    # How long "starting" may take is a property of the engine, not of the supervisor:
    # one binds its port and then loads, another loads the whole model first.
    sup = ProcessSupervisor(startup_timeout_s=60.0, poll_interval_s=0.05)
    port = sup.allocate_port()
    # Never listens, so the wait runs to the deadline — the short override is what makes
    # this finish in a fraction of a second instead of a minute.
    never = "import time; time.sleep(30)"
    spec = ServeSpec(argv=[sys.executable, "-c", never])
    with pytest.raises(ServingError, match="within 1s"):
        await sup.spawn(
            "m", spec, port, base_url=f"http://127.0.0.1:{port}/v1",
            on_crash=_noop_crash, log_path=tmp_path / "m.log", timeout_s=1.0,
        )


async def test_a_fast_exit_reports_how_long_the_engine_lived(tmp_path: Path):
    # The caller retries a losing port bind but not a failed model load, and the lifetime
    # is what tells them apart — a bind fails on the first syscall.
    sup = ProcessSupervisor(startup_timeout_s=5.0, poll_interval_s=0.05)
    port = sup.allocate_port()
    spec = ServeSpec(argv=[sys.executable, "-c", "import sys; sys.exit(1)"])
    with pytest.raises(EngineExitedDuringStartup) as excinfo:
        await sup.spawn(
            "m", spec, port, base_url=f"http://127.0.0.1:{port}/v1",
            on_crash=_noop_crash, log_path=tmp_path / "m.log",
        )
    assert excinfo.value.elapsed_s < 1.0


async def test_a_slow_exit_is_reported_as_slow(tmp_path: Path):
    # An engine that ran for a while and then died was loading a model; re-running that
    # load on a fresh port would only pay the same failure again.
    sup = ProcessSupervisor(startup_timeout_s=5.0, poll_interval_s=0.05)
    port = sup.allocate_port()
    dies_late = "import sys, time; time.sleep(0.6); sys.stderr.write('bad weights'); sys.exit(1)"
    spec = ServeSpec(argv=[sys.executable, "-c", dies_late])
    with pytest.raises(EngineExitedDuringStartup) as excinfo:
        await sup.spawn(
            "m", spec, port, base_url=f"http://127.0.0.1:{port}/v1",
            on_crash=_noop_crash, log_path=tmp_path / "m.log",
        )
    assert excinfo.value.elapsed_s >= 0.5
    # The log tail still rides along, so the row can say what actually went wrong.
    assert "bad weights" in str(excinfo.value)
