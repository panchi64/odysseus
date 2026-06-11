"""Backend detection — the fail-closed factory.

At startup the app asks for a sandbox. If a usable backend is present we return
it; if none is, we return ``None`` and the code-execution capability is **disabled
by construction**. The contract is the one safety rule that matters here: a
missing sandbox NEVER degrades to running on the host — it degrades to *not
running at all*, and the agent is told the capability is unavailable.
"""

from __future__ import annotations

from core.config import Settings

from .base import Sandbox
from .container import ContainerSandbox


async def detect_sandbox(settings: Settings) -> Sandbox | None:
    """Return a ready sandbox backend, or ``None`` to disable code execution.

    Honors ``settings.sandbox_enabled`` (operator kill-switch) and
    ``settings.sandbox_runtime`` (pin Docker/Podman). The only backend today is
    the container runtime; the return type keeps the seam open for others.
    """
    if not settings.sandbox_enabled:
        return None

    backend = ContainerSandbox(
        runtime=settings.sandbox_runtime,
        image=settings.sandbox_image,
        memory=settings.sandbox_memory,
        cpus=settings.sandbox_cpus,
    )
    if await backend.available():
        return backend
    return None  # fail closed — never a host fallback
