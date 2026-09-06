"""The OS-level fence for everything that runs outside a container, and the escape hatch.

Two paths execute on the operator's real machine: the code-mode shell, working in a
project's throwaway worktree, and ``code_run_host_command``, the approval-gated exception
that exists for when the host itself must change. Both are fenced the same way, by
``sandbox-runtime`` (seatbelt on macOS, bubblewrap on Linux, no container): credential
paths and the data directory are unreadable, writes are deny-by-default, and egress goes
only to allowlisted domains. :func:`confine` is that fence, applied per command;
:func:`resolve_confinement` is the once-per-process machinery behind it.

**Approval is not the only thing holding the line.** What the operator read and agreed
to is the command; what a command can *reach* once running is a separate question, and
one they cannot audit from a single line of shell.

**The hatch degrades where everything else fails closed, deliberately.** The shell refuses
outright without a fence, and ``detect.py`` disables sandboxed execution when no runtime
exists, because nothing was promised in either case. Here the operator has explicitly
approved *this* command, and refusing it because a platform primitive is missing would
break the single case the tool exists for — so it runs unconfined and says so.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostConfinement:
    """The fence an approved host command runs under: whether it applies, why not when it
    doesn't, and what it lets through.

    Resolved before the run rather than reported after it, so the tool can tell the
    model — and through it the operator — what actually held, instead of implying a fence
    that was never applied.
    """

    active: bool
    reason: str = ""
    allowed_domains: tuple[str, ...] = ()
    allow_write: tuple[str, ...] = ()
    deny_read: tuple[str, ...] = ()


# The confinement primitive is a process-global singleton, so it is configured once and
# the outcome cached: the answer cannot change between commands, and re-deciding per call
# would re-run the dependency probe on a hot path.
_resolved: HostConfinement | None = None
# Guards the configure-once: `_configure` awaits, so two approvals resolving at the same
# moment would both pass a bare `is None` check and initialize the singleton twice.
_resolve_lock = asyncio.Lock()


def denied_reads(settings: Settings) -> tuple[str, ...]:
    """Paths no host-side command may read, whichever fence it runs under.

    The data directory carries the vault, the sealed workspaces and the database. It is
    denied here rather than left to the credential list because it is the one path whose
    exposure would undo at-rest encryption wholesale. Derived once for both callers — the
    approved host command and the code-mode shell — because a path added to one fence and
    not the other is a hole nobody notices.
    """
    return (*settings.host_command_deny_read, str(Path(settings.data_dir).resolve()))


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
    deny_read = list(denied_reads(settings))
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
    # Imported here rather than at module scope: `services.egress` reads `safe_key` out of
    # this package, so the two only meet at call time.
    from services.egress import normalise_domain

    # Through the same funnel an approved domain goes through, so what an operator wrote
    # in the setting means the same thing at both fences. Left raw, `Files.PythonHosted.org`
    # or a pasted URL would be allowed by the container's proxy and refused here.
    domains = [normalise_domain(d) for d in settings.egress_allowed_domains]
    try:
        await SandboxManager.initialize(
            SandboxRuntimeConfig(
                # The same allowlist the container fence reads. An approved command is
                # still only approved for what the operator read; where it may *reach* is
                # one installation-wide policy, not a second list that drifts from it.
                # `allow_local_binding` because a dev server or a test suite opening a
                # localhost socket is compute, not egress — and it is read off this global
                # config at wrap time, so a per-call config could not supply it.
                network=NetworkConfig(allowed_domains=domains, allow_local_binding=True),
                filesystem=FilesystemConfig(
                    deny_read=deny_read, allow_write=allow_write, deny_write=list(deny_read)
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 - any init failure means "not confined"
        return HostConfinement(False, f"sandbox-runtime could not initialize ({exc})")
    # Carried on the resolution rather than re-derived at the run: `confine` fences each
    # command individually, and these are the settings half of what it needs — the same
    # values the global init above was given, so the two cannot drift.
    return HostConfinement(
        True,
        allowed_domains=tuple(domains),
        allow_write=tuple(allow_write),
        deny_read=tuple(deny_read),
    )


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


async def confine(
    command: str,
    *,
    allowed_domains: Iterable[str],
    allow_write: Iterable[str],
    deny_read: Iterable[str],
) -> str:
    """``command`` rewritten to run under the platform's sandbox, fenced for *this* call.

    :func:`resolve_confinement` settles the machinery once per process — the platform
    probe, the proxy listeners — but not where a particular command may write, because the
    two callers do not agree on that: the code-mode shell writes into one conversation's
    worktree, the approved host command wherever the operator allowed. Those rules are
    genuinely per-call, because they go into the wrapper the OS itself enforces.

    **The network half is coarser, and that is a property of the runtime, not a choice
    here.** One proxy serves the whole process and filters every request against the
    configuration installed at initialisation, so ``allowed_domains`` decides only whether
    this command gets a route out *at all* — an empty set gets no proxy and no network.
    Which hosts it may then reach is the installation-wide allowlist, identical for every
    command. Folding a conversation's own grants in would mean writing them into that one
    shared configuration, where they would widen the fence around every other command
    running at that moment — a background dev server started by another thread included —
    and stay there after the granting command exited. That is a per-call approval turned
    into a process-wide standing grant, so the host fence does not honour them: on the
    host only ``egress_allowed_domains`` moves the line.
    """
    from sandbox_runtime import (
        FilesystemConfig,
        NetworkConfig,
        SandboxManager,
        SandboxRuntimeConfig,
    )

    # Everything read-denied is write-denied too. Read denial alone would still let a
    # command clobber the vault or an ssh key it could not read.
    denied = list(deny_read)
    return await SandboxManager.wrap_with_sandbox(
        command,
        custom_config=SandboxRuntimeConfig(
            network=NetworkConfig(allowed_domains=sorted(set(allowed_domains))),
            filesystem=FilesystemConfig(
                deny_read=denied, allow_write=list(allow_write), deny_write=denied
            ),
        ),
    )

