"""Host hardware detection — best-effort, gracefully-degrading probes.

The one rule, borrowed from the sandbox: **degrade, never crash**. Every external
tool is gated by ``shutil.which`` and driven over an ``asyncio`` subprocess (no SDK
— small dependency surface, portable across hosts); a missing tool, a timeout, or a
parse failure leaves the corresponding field empty rather than sinking the profile.
The code runs on any POSIX host and reports whatever it can determine there.

Cross-platform CPU/RAM facts come from ``psutil``; everything OS-shaped beyond that
(CPU model string, GPU/VRAM, serving runtimes) is a per-platform subprocess probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import platform
import re
import shutil
from pathlib import Path

import psutil

from .models import (
    Accelerator,
    AcceleratorKind,
    ComputeBackend,
    CpuInfo,
    HardwareProfile,
    MemoryInfo,
    PlatformInfo,
    ServingRuntime,
)

logger = logging.getLogger(__name__)

_MIB = 1024 * 1024
# Apple Silicon shares one memory pool; the GPU's working-set budget is a fraction
# of system RAM. ~75% mirrors Metal's recommendedMaxWorkingSetSize without a PyObjC
# dependency (which would break the portable, dependency-light posture).
_UNIFIED_VRAM_FRACTION = 0.75
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")

# Each serving runtime, with the binary/flag candidates to probe for a version.
_RUNTIMES: tuple[tuple[str, list[list[str]]], ...] = (
    ("ollama", [["ollama", "--version"]]),
    ("llama.cpp", [["llama-server", "--version"], ["llama-cli", "--version"]]),
    ("mlx-lm", [["mlx_lm.server", "--version"], ["mlx_lm.generate", "--version"]]),
    ("vllm", [["vllm", "--version"]]),
)


async def _run(argv: list[str], *, timeout_s: float = 5.0) -> tuple[int, str, str] | None:
    """Run a command and return ``(returncode, stdout, stderr)``, or ``None`` on any
    failure to start, timeout, or kill. Never raises — the degrade primitive."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError):
        return None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        return None
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


# --- CPU / RAM (psutil + per-platform model string) -------------------------


def _cpu_counts() -> tuple[int | None, int | None]:
    return psutil.cpu_count(logical=False), psutil.cpu_count(logical=True)


def _memory() -> MemoryInfo:
    vm = psutil.virtual_memory()
    return MemoryInfo(total_bytes=vm.total, available_bytes=vm.available)


async def _cpu_model() -> str | None:
    system = platform.system()
    if system == "Darwin":
        result = await _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if result and result[0] == 0 and result[1].strip():
            return result[1].strip()
        return None
    if system == "Linux":
        try:
            text = Path("/proc/cpuinfo").read_text()
        except OSError:
            return None
        for line in text.splitlines():
            # x86 uses "model name"; some ARM kernels expose "Model".
            if line.startswith(("model name", "Model")) and ":" in line:
                return line.split(":", 1)[1].strip()
    return None


# --- accelerators (GPU / VRAM / compute backend) ----------------------------


async def _probe_nvidia() -> list[Accelerator]:
    if shutil.which("nvidia-smi") is None:
        return []
    result = await _run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    if not result or result[0] != 0:
        return []
    accels: list[Accelerator] = []
    for line in result[1].splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        vram = None
        if len(parts) > 1:
            with contextlib.suppress(ValueError):
                vram = int(float(parts[1])) * _MIB
        accels.append(Accelerator(name=parts[0], kind=AcceleratorKind.cuda, vram_bytes=vram))
    return accels


async def _probe_amd() -> list[Accelerator]:
    if shutil.which("rocm-smi") is None:
        return []
    result = await _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])
    if not result or result[0] != 0:
        return []
    try:
        data = json.loads(result[1])
    except (json.JSONDecodeError, ValueError):
        return []
    accels: list[Accelerator] = []
    for card_key, card in data.items():
        if not isinstance(card, dict):
            continue
        name = (
            card.get("Card series")
            or card.get("Card model")
            or card.get("Card SKU")
            or card_key
        )
        vram = None
        for key, value in card.items():
            if "vram total memory" in key.lower():
                with contextlib.suppress(ValueError, TypeError):
                    vram = int(value)
        accels.append(Accelerator(name=str(name), kind=AcceleratorKind.rocm, vram_bytes=vram))
    return accels


async def _probe_metal(memory_total: int | None) -> list[Accelerator]:
    """Apple Silicon always yields one unified-memory accelerator. ``system_profiler``
    enriches it with the chip name + GPU core count, but is slow and optional."""
    name, gpu_cores = "Apple GPU", None
    result = await _run(["system_profiler", "SPDisplaysDataType", "-json"], timeout_s=8.0)
    if result and result[0] == 0:
        try:
            displays = json.loads(result[1]).get("SPDisplaysDataType", [])
            if displays:
                first = displays[0]
                name = first.get("sppci_model") or first.get("_name") or name
                cores = first.get("sppci_cores")
                if cores is not None:
                    with contextlib.suppress(ValueError, IndexError):
                        gpu_cores = int(str(cores).split()[0])
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
    vram = int(memory_total * _UNIFIED_VRAM_FRACTION) if memory_total else None
    return [
        Accelerator(
            name=name,
            kind=AcceleratorKind.metal,
            vram_bytes=vram,
            unified=True,
            gpu_cores=gpu_cores,
        )
    ]


async def _accelerators(memory_total: int | None) -> tuple[list[Accelerator], ComputeBackend]:
    """Detect accelerators in backend priority ``cuda > rocm > metal > cpu``. The
    single-operator desktop target realistically has exactly one of these."""
    if nvidia := await _probe_nvidia():
        return nvidia, ComputeBackend.cuda
    if amd := await _probe_amd():
        return amd, ComputeBackend.rocm
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return await _probe_metal(memory_total), ComputeBackend.metal
    return [], ComputeBackend.cpu


# --- serving runtimes -------------------------------------------------------


async def _probe_runtime(name: str, candidates: list[list[str]]) -> ServingRuntime:
    for argv in candidates:
        if shutil.which(argv[0]) is None:
            continue
        result = await _run(argv)
        if result is None:
            continue
        match = _VERSION_RE.search(result[1] + result[2])
        return ServingRuntime(name=name, version=match.group(1) if match else None, available=True)
    return ServingRuntime(name=name, available=False)


async def _probe_runtimes() -> list[ServingRuntime]:
    return list(await asyncio.gather(*(_probe_runtime(n, c) for n, c in _RUNTIMES)))


# --- orchestration ----------------------------------------------------------


async def _guard(coro, default):
    """Await ``coro``, returning ``default`` if it raises — one failing probe must
    never sink the whole profile."""
    try:
        return await coro
    except Exception:
        logger.warning("cookbook hardware probe failed", exc_info=True)
        return default


def _guard_sync(fn, default):
    try:
        return fn()
    except Exception:
        logger.warning("cookbook hardware probe failed", exc_info=True)
        return default


async def probe() -> HardwareProfile:
    """Build a full hardware profile, running the slow subprocess probes
    concurrently and degrading each independently."""
    plat = PlatformInfo(
        system=platform.system(),
        release=platform.release(),
        arch=platform.machine(),
    )
    memory = _guard_sync(_memory, MemoryInfo())
    physical, logical = _guard_sync(_cpu_counts, (None, None))
    cpu_model, (accels, backend), runtimes = await asyncio.gather(
        _guard(_cpu_model(), None),
        _guard(_accelerators(memory.total_bytes), ([], ComputeBackend.cpu)),
        _guard(_probe_runtimes(), []),
    )
    return HardwareProfile(
        cpu=CpuInfo(model=cpu_model, physical_cores=physical, logical_cores=logical),
        memory=memory,
        accelerators=accels,
        compute_backend=backend,
        platform=plat,
        runtimes=runtimes,
    )
