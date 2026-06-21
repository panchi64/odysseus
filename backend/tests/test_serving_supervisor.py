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
from services.serving.supervisor import ProcessSupervisor, ServeSpec


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
