"""The deliberate host-execution escape hatch — the one non-sandboxed path.

This is the exception to everything its sibling modules enforce: it runs a command
**directly on the host**. It exists for the legitimate case where the operator
genuinely needs their own machine changed. It is therefore reachable by the agent
*only* through an approval-gated tool whose request carries a plain-language
explanation of what the command does — never as a silent fallback, never without
explicit per-call consent. Kept here, beside the sandbox, so both execution paths
live in one place and the contrast is impossible to miss.

**Approval is not the only thing holding the line.** What the operator read and agreed
to is the command; what a command can *reach* once running is a separate question, and
one they cannot audit from a single line of shell. So an approved command is also fenced
at the OS level — ``sandbox-runtime`` (seatbelt on macOS, bubblewrap on Linux, no
container) denies reads of the credential paths and the data directory, and allows egress
only to configured domains.

**This one degrades where the sandbox fails closed, deliberately.** ``detect.py`` disables
sandboxed execution outright when no runtime exists, because nothing was promised there.
Here the operator has explicitly approved *this* command, and refusing it because a
platform primitive is missing would break the single case the tool exists for. So a
missing primitive means the command runs unconfined and says so, rather than not running.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings
from core.exceptions import OdysseusError

from .base import SandboxResult

logger = logging.getLogger(__name__)


class HostExecutionError(OdysseusError):
    """The host command could not be launched (a non-zero exit is a normal
    :class:`SandboxResult`, not this)."""


@dataclass(frozen=True)
class HostConfinement:
    """Whether an approved host command will be OS-confined, and why not when it won't.

    Resolved before the run rather than reported after it, so the tool can tell the
    model — and through it the operator — what actually held, instead of implying a fence
    that was never applied.
    """

    active: bool
    reason: str = ""


# The confinement primitive is a process-global singleton, so it is configured once and
# the outcome cached: the answer cannot change between commands, and re-deciding per call
# would re-run the dependency probe on a hot path.
_resolved: HostConfinement | None = None
# Guards the configure-once: `_configure` awaits, so two approvals resolving at the same
# moment would both pass a bare `is None` check and initialize the singleton twice.
_resolve_lock = asyncio.Lock()


async def resolve_confinement(settings: Settings) -> HostConfinement:
    """Configure OS-level confinement for host commands, once per process."""
    global _resolved
    if _resolved is not None:
        return _resolved
    async with _resolve_lock:
        if _resolved is not None:  # settled while this call waited for the lock
            return _resolved
        resolved = await _configure(settings)
        if not resolved.active:
            # Worth one line: an operator who believes their host commands are fenced
            # should not have to read a tool result to discover otherwise.
            logger.warning("host commands are running unconfined: %s", resolved.reason)
        _resolved = resolved
        return _resolved


async def _configure(settings: Settings) -> HostConfinement:
    if not settings.host_command_sandbox_enabled:
        return HostConfinement(False, "disabled by configuration")
    try:
        from sandbox_runtime import (
            FilesystemConfig,
            NetworkConfig,
            SandboxManager,
            SandboxRuntimeConfig,
            get_default_write_paths,
        )
    except ImportError as exc:  # pragma: no cover - the dependency is declared
        return HostConfinement(False, f"sandbox-runtime is not installed ({exc})")
    if not SandboxManager.check_dependencies():
        # Name what is actually missing. A generic "unavailable" reads as "your OS can't
        # do this" and gets ignored, when in practice the usual cause is a single absent
        # binary the operator can install in one command — and until they do, every
        # approved host command runs unfenced.
        from sandbox_runtime.utils.platform import get_platform
        from sandbox_runtime.utils.ripgrep import has_ripgrep_sync

        if not SandboxManager.is_supported_platform(get_platform()):
            return HostConfinement(False, f"{get_platform()} has no supported sandbox primitive")
        if not has_ripgrep_sync():
            return HostConfinement(
                False,
                "ripgrep (`rg`) is not installed — sandbox-runtime needs it to resolve "
                "the filesystem deny rules; install it to fence host commands",
            )
        return HostConfinement(False, "the platform's sandbox dependencies are unavailable")
    # The data directory carries the vault, the sealed workspaces and the database. It is
    # denied here rather than left to the credential list because it is the one path whose
    # exposure would undo at-rest encryption wholesale.
    data_dir = str(Path(settings.data_dir).resolve())
    deny_read = [*settings.host_command_deny_read, data_dir]
    # Writes are deny-by-default in this runtime, so the allow list is not a hardening knob
    # — it is what keeps an approved command able to do the thing it was approved for. The
    # runtime's own defaults (`/dev/null`, `/dev/stdout`, the tty) come first: without them
    # even `echo` into a pipe fails, which would read as the tool being broken.
    # `gettempdir()` rather than a literal `/tmp`: macOS gives each user a private
    # `TMPDIR` under `/var/folders`, so a hardcoded path would miss where temp files
    # actually land (`XC-PORT-1`).
    allow_write = [
        *get_default_write_paths(),
        *settings.host_command_allow_write,
        tempfile.gettempdir(),
        os.getcwd(),
    ]
    # Everything read-denied is write-denied too. Read denial alone would still let a
    # command clobber the vault or an ssh key it could not read.
    deny_write = list(deny_read)
    try:
        await SandboxManager.initialize(
            SandboxRuntimeConfig(
                network=NetworkConfig(allowed_domains=list(settings.host_command_allowed_domains)),
                filesystem=FilesystemConfig(
                    deny_read=deny_read, allow_write=allow_write, deny_write=deny_write
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 - any init failure means "not confined"
        return HostConfinement(False, f"sandbox-runtime could not initialize ({exc})")
    return HostConfinement(True)


async def shutdown_confinement() -> None:
    """Tear down whatever `resolve_confinement` started, and forget the decision.

    Configuring the confinement starts long-lived proxy listeners inside
    ``sandbox-runtime``; without this they outlive the app, and under the reloading dev
    server they accumulate a pair per restart. Registered with the app's lifecycle
    registry like every other background unit, rather than left to process exit.
    """
    global _resolved
    if _resolved is None:
        return
    was_active = _resolved.active
    _resolved = None
    if not was_active:
        return  # nothing was ever initialized
    try:
        from sandbox_runtime import SandboxManager

        await SandboxManager.reset()
    except Exception:  # noqa: BLE001 - shutdown is best-effort, like every other unit's
        logger.warning("host-command confinement did not shut down cleanly", exc_info=True)


async def _confine(command: str) -> str:
    """``command`` rewritten to run under the platform's sandbox."""
    from sandbox_runtime import SandboxManager

    return await SandboxManager.wrap_with_sandbox(command)


async def run_on_host(
    command: str,
    *,
    timeout_s: float = 120.0,
    confinement: HostConfinement | None = None,
) -> SandboxResult:
    """Run ``command`` in the host shell, after approval. Bounded by a wall-clock
    timeout; the process group is killed on overrun.

    ``confinement`` is resolved by the caller (see :func:`resolve_confinement`) and passed
    in rather than looked up here, so the tool reports the same fence it asked for. ``None``
    runs the command unconfined.
    """
    if confinement is not None and confinement.active:
        try:
            command = await _confine(command)
        except Exception as exc:  # noqa: BLE001 - wrapping must never lose the command
            raise HostExecutionError(f"failed to confine host command: {exc}") from exc
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
