"""Execution-sandbox capability — isolated code/shell execution for the agent.

The default is the sandboxed path (``Sandbox`` + ``ContainerSandbox``), built so
that when code-execution tools land they are safe by construction; ``host`` is the
single, deliberately-separate, approval-gated escape hatch to the real host. The
agent reaches it through a per-conversation :class:`SandboxSessionManager`, which
keeps a container warm for iterative work and reaps it when idle.
"""

from __future__ import annotations

from .base import (
    Sandbox,
    SandboxError,
    SandboxFile,
    SandboxResult,
    SandboxSpec,
)
from .container import (
    ContainerSandbox,
    await_listening,
    detached_run_argv,
    discover_runtime,
    ensure_image,
    force_remove_container,
    published_host_port,
    run_subprocess,
)
from .detect import detect_sandbox
from .host import HostExecutionError, run_on_host
from .preview import PreviewHandle
from .session import SandboxSession, SandboxSessionManager

__all__ = [
    "Sandbox",
    "SandboxError",
    "SandboxFile",
    "SandboxResult",
    "SandboxSpec",
    "ContainerSandbox",
    "await_listening",
    "detached_run_argv",
    "discover_runtime",
    "ensure_image",
    "force_remove_container",
    "published_host_port",
    "run_subprocess",
    "detect_sandbox",
    "PreviewHandle",
    "SandboxSession",
    "SandboxSessionManager",
    "HostExecutionError",
    "run_on_host",
]
