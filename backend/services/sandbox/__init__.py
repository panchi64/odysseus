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
from .container import ContainerSandbox
from .detect import detect_sandbox
from .host import HostExecutionError, HostResult, run_on_host
from .session import SandboxSession, SandboxSessionManager

__all__ = [
    "Sandbox",
    "SandboxError",
    "SandboxFile",
    "SandboxResult",
    "SandboxSpec",
    "ContainerSandbox",
    "detect_sandbox",
    "SandboxSession",
    "SandboxSessionManager",
    "HostExecutionError",
    "HostResult",
    "run_on_host",
]
