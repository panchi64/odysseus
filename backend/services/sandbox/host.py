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
from dataclasses import dataclass

from core.exceptions import OdysseusError


class HostExecutionError(OdysseusError):
    """The host command could not be launched (a non-zero exit is a normal
    :class:`HostResult`, not this)."""


@dataclass(frozen=True)
class HostResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


async def run_on_host(command: str, *, timeout_s: float = 120.0) -> HostResult:
    """Run ``command`` in the host shell, after approval. Bounded by a wall-clock
    timeout; the process group is killed on overrun."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        raise HostExecutionError(f"failed to launch host command: {exc}") from exc

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return HostResult(exit_code=124, stdout="", stderr="host command timed out", timed_out=True)
    return HostResult(
        exit_code=proc.returncode or 0,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )
