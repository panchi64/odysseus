"""The deliberate host-execution escape hatch — the one non-sandboxed path.

This is the exception to everything its sibling modules enforce: it runs a command
**directly on the host**. It exists for the legitimate case where the operator
genuinely needs their own machine changed. It is therefore reachable by the agent
*only* through an approval-gated tool whose request carries a plain-language
explanation of what the command does — never as a silent fallback, never without
explicit per-call consent. Kept here, beside the sandbox, so both execution paths
live in one place and the contrast is impossible to miss.
"""

from __future__ import annotations

import asyncio
import os
import signal

from core.exceptions import OdysseusError

from .base import SandboxResult


class HostExecutionError(OdysseusError):
    """The host command could not be launched (a non-zero exit is a normal
    :class:`SandboxResult`, not this)."""


async def run_on_host(command: str, *, timeout_s: float = 120.0) -> SandboxResult:
    """Run ``command`` in the host shell, after approval. Bounded by a wall-clock
    timeout; the process group is killed on overrun."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group, so we can kill the whole tree
        )
    except (OSError, ValueError) as exc:
        raise HostExecutionError(f"failed to launch host command: {exc}") from exc

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        # Kill the whole process group, not just the shell — otherwise a child the
        # command spawned (a server, a backgrounded job) survives the timeout.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        await proc.wait()
        return SandboxResult(
            exit_code=124, stdout="", stderr="host command timed out", timed_out=True
        )
    return SandboxResult(
        exit_code=proc.returncode or 0,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )
