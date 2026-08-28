"""Hardware probes — deterministic, by mocking the subprocess runner + psutil.

No real hardware: every external call (`_run`, `shutil.which`) and psutil is patched,
so the same assertions hold on any CI host. Covers parsing of real tool output, the
degrade paths (tool absent / fails), and per-probe isolation.
"""

from __future__ import annotations

from types import SimpleNamespace

from services.cookbook import hardware
from services.cookbook.models import AcceleratorKind, ComputeBackend

_GIB = 1024**3


def _patch_mem(monkeypatch, total: int, available: int) -> None:
    monkeypatch.setattr(
        hardware.psutil, "virtual_memory", lambda: SimpleNamespace(total=total, available=available)
    )


async def test_nvidia_parse(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda name: f"/usr/bin/{name}")

    async def fake_run(argv, *, timeout_s=5.0):
        if argv[0] == "nvidia-smi":
            return 0, "NVIDIA GeForce RTX 4090, 24564\nNVIDIA RTX A6000, 49140\n", ""
        return None

    monkeypatch.setattr(hardware, "_run", fake_run)
    accels = await hardware._probe_nvidia()
    assert [a.name for a in accels] == ["NVIDIA GeForce RTX 4090", "NVIDIA RTX A6000"]
    assert accels[0].kind == AcceleratorKind.cuda
    assert accels[0].vram_bytes == 24564 * 1024 * 1024


async def test_metal_parse(monkeypatch):
    blob = '{"SPDisplaysDataType":[{"sppci_model":"Apple M2 Ultra","sppci_cores":"76"}]}'

    async def fake_run(argv, *, timeout_s=5.0):
        return (0, blob, "") if argv[0] == "system_profiler" else None

    monkeypatch.setattr(hardware, "_run", fake_run)
    accels = await hardware._probe_metal(128 * _GIB)
    assert len(accels) == 1
    accel = accels[0]
    assert accel.kind == AcceleratorKind.metal and accel.unified
    assert accel.name == "Apple M2 Ultra" and accel.gpu_cores == 76
    assert accel.vram_bytes == int(128 * _GIB * 0.75)


async def test_metal_degrades_without_system_profiler(monkeypatch):
    async def fake_run(argv, *, timeout_s=5.0):
        return None

    monkeypatch.setattr(hardware, "_run", fake_run)
    accels = await hardware._probe_metal(64 * _GIB)
    # Still one unified accelerator from RAM, just without the chip name / core count.
    assert len(accels) == 1
    assert accels[0].gpu_cores is None
    assert accels[0].vram_bytes == int(64 * _GIB * 0.75)


async def test_runtime_version_parsed(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda name: f"/usr/bin/{name}")

    async def fake_run(argv, *, timeout_s=5.0):
        return (0, "ollama version is 0.6.4", "") if argv[0] == "ollama" else None

    monkeypatch.setattr(hardware, "_run", fake_run)
    runtime = await hardware._probe_runtime("ollama", [["ollama", "--version"]])
    assert runtime.available and runtime.version == "0.6.4"


async def test_runtime_absent(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    runtime = await hardware._probe_runtime("vllm", [["vllm", "--version"]])
    assert not runtime.available and runtime.version is None


async def test_probe_degrades_fully_on_a_bare_host(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(hardware.platform, "release", lambda: "6.0")
    monkeypatch.setattr(hardware.psutil, "cpu_count", lambda logical=True: 8 if logical else 4)
    _patch_mem(monkeypatch, 16 * _GIB, 8 * _GIB)

    async def fake_run(argv, *, timeout_s=5.0):
        return None

    monkeypatch.setattr(hardware, "_run", fake_run)
    profile = await hardware.probe()
    assert profile.compute_backend == ComputeBackend.cpu
    assert profile.accelerators == []
    assert all(not r.available for r in profile.runtimes)
    assert profile.cpu.physical_cores == 4 and profile.cpu.logical_cores == 8
    assert profile.memory.total_bytes == 16 * _GIB


async def test_probe_isolates_a_failing_probe(monkeypatch):
    async def boom(memory_total):
        raise RuntimeError("accelerator probe blew up")

    monkeypatch.setattr(hardware, "_accelerators", boom)
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(hardware.platform, "release", lambda: "6.0")
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    monkeypatch.setattr(hardware.psutil, "cpu_count", lambda logical=True: 8 if logical else 4)
    _patch_mem(monkeypatch, 16 * _GIB, 8 * _GIB)

    async def fake_run(argv, *, timeout_s=5.0):
        return None

    monkeypatch.setattr(hardware, "_run", fake_run)
    profile = await hardware.probe()
    # The accelerator probe failed → its default, but the rest of the profile survives.
    assert profile.accelerators == []
    assert profile.compute_backend == ComputeBackend.cpu
    assert profile.memory.total_bytes == 16 * _GIB
