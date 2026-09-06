"""Running a command on the operator's real machine, and reaping the tree it starts.

Two paths land here — the code-mode shell and ``code_run_host_command``, the approval-gated
escape hatch — and they differ only in what they do with the streams afterwards. The
mechanics live beside the fence rather than inside it (``host.py``) so that *what a command
may reach* and *how a process is started and killed* have separate reasons to change.

Nothing here decides the first of those. Every caller rewrites its command through
:func:`services.sandbox.host.confine` before it gets this far. What this module guarantees
is that whatever was started can be stopped **whole** — a command that backgrounds a
server must not leave it running once the run that started it is gone.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping
from pathlib import Path
from typing import IO

from core.exceptions import OdysseusError

from .base import SandboxResult
from .host import HostConfinement, confine


class HostExecutionError(OdysseusError):
    """The host command could not be launched (a non-zero exit is a normal
    :class:`~services.sandbox.base.SandboxResult`, not this)."""


#: How long a process group gets to shut itself down before it is killed outright. Long
#: enough for a server to close its listeners and drop a lockfile, short enough that an
#: agent stopping a background command does not sit there waiting for it.
_GRACE_S = 2.0


def kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the whole process group, not just the shell — otherwise a child the command
    spawned (a server, a backgrounded job) outlives whatever stopped its parent."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    except OSError:  # already reaped, or no such group
        pass


async def terminate_tree(proc: asyncio.subprocess.Process) -> None:
    """Ask the process group to stop, then make it, and wait for it either way.

    What a `SIGKILL` alone costs is everything the process would have done on its way out:
    a dev server never closes its socket, a compose stack leaves its containers up, a test
    run leaves a scratch database and a lockfile behind. Killing outright is still the
    fallback, because a process that ignores `SIGTERM` must not be able to hold a turn
    open — but it is the fallback, not the opening move.

    Not for teardown paths: a cancelled coroutine cannot await, and :func:`kill_tree` is
    the version that reaps without one.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    except OSError:  # already reaped, or no such group
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_GRACE_S)
    except TimeoutError:
        kill_tree(proc)
        await proc.wait()


async def spawn_confined(
    command: str,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    stdout: int | IO[bytes],
    stderr: int | IO[bytes],
) -> asyncio.subprocess.Process:
    """Start ``command`` in a session of its own, so :func:`kill_tree` can reach it.

    The spawn's own errors are left to propagate unwrapped. The two callers read them
    differently — the shell turns a working directory the model's last command deleted
    into something it can retry, while the hatch reports any launch failure as one — and
    flattening them here would take that distinction away from both.
    """
    return await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,  # own process group, so we can kill the whole tree
    )


async def run_on_host(
    command: str,
    *,
    timeout_s: float = 120.0,
    confinement: HostConfinement | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> SandboxResult:
    """Run ``command`` in the host shell, after approval. Bounded by a wall-clock
    timeout; the process group is killed on overrun — and on cancellation, so a stopped
    run never leaves the command's tree running on the operator's machine.

    ``confinement`` is resolved by the caller (see
    :func:`services.sandbox.host.resolve_confinement`) and passed in rather than looked up
    here, so the tool reports the same fence it asked for. ``None`` runs the command
    unconfined.
    """
    if confinement is not None and confinement.active:
        try:
            command = await confine(
                command,
                allowed_domains=confinement.allowed_domains,
                allow_write=confinement.allow_write,
                deny_read=confinement.deny_read,
            )
        except Exception as exc:  # noqa: BLE001 - wrapping must never lose the command
            raise HostExecutionError(f"failed to confine host command: {exc}") from exc
    try:
        proc = await spawn_confined(
            command,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        raise HostExecutionError(f"failed to launch host command: {exc}") from exc

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        kill_tree(proc)
        await proc.wait()
        return SandboxResult(
            exit_code=124, stdout="", stderr="host command timed out", timed_out=True
        )
    except BaseException:
        # Cancellation lands here — the run hit its inactivity/wall-clock bound, or the
        # operator pressed Stop. Unwinding without reaping would leave the approved
        # command's whole tree alive on the operator's real machine with no run left to
        # stop it, which is precisely what the process group exists to prevent. Not
        # awaited: this coroutine is already being torn down, and the group is signalled.
        kill_tree(proc)
        raise
    return SandboxResult(
        exit_code=proc.returncode or 0,
        stdout=out.decode("utf-8", "replace"),
        stderr=err.decode("utf-8", "replace"),
    )
