"""Boot reconciliation — collecting what a previous process left running.

A crash, a ``kill -9``, a laptop lid closing mid-run: none of those get to run a
teardown, and what survives is invisible to every map the session manager keeps.
A container nothing will ever exec into holds memory and a mount; a network
nothing joins accumulates one per boot. Startup is the one moment every container
carrying our names is provably *not* in use, which is what makes clearing them
wholesale safe here and nowhere else.

Its own module because it needs none of the manager's state — a runtime name and
the work root are the whole input — and because it answers a different question
from the rest of the sandbox: not "what is this conversation doing" but "what is
left over from a process that is gone". Both halves of that question live here,
even though only one of them runs at boot: :func:`reconcile` clears the containers
and networks, and :func:`orphan_fork_keys` names the delegated forks, which the
manager's idle sweep collects because deleting one has to go through the tombstone
protocol. An ordinary conversation's workspace is not leftover at all — it is that
conversation's files, waiting for its next turn, and nothing collects it.

Best-effort throughout, and deliberately so: a runtime that is down at boot must
not stop the app from starting. Nothing else collects these, so what one pass
leaves behind waits for the next boot.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Container
from pathlib import Path

from .base import SandboxError
from .container import force_remove_container, run_subprocess
from .fork import fork_marker
from .names import DEFAULT_NAMES, ContainerNames
from .sidecar import remove_network

logger = logging.getLogger(__name__)

# Total wall clock reconciliation may spend talking to the runtime. Startup waits on
# it, so it is a budget for the whole pass rather than a per-call timeout: leftovers
# are cheap to carry to the next boot, a backend that never finishes starting is not.
_BUDGET_S = 30.0


async def reconcile(
    runtime: str | None, work_root: Path, names: ContainerNames = DEFAULT_NAMES
) -> None:
    """Clear what the previous process left behind — containers, networks, and the
    scratch dirs of a pool this build no longer keeps.

    ``names`` decides what counts as left behind, and it must be the same scheme the
    sessions were named under: this removes everything its filters match without asking,
    so a mismatch here either strands leftovers forever or reaches into another
    instance's live workspaces."""
    if runtime is not None:
        await _reconcile_runtime(runtime, names)
    dirs = await asyncio.to_thread(_remove_pool_dirs, work_root)
    if dirs:
        logger.info("sandbox: removed %d leftover pre-warmed workspace dir(s)", dirs)


async def _reconcile_runtime(runtime: str, names: ContainerNames) -> None:
    """Remove the containers and networks carrying our names, under a single
    wall-clock budget for the lot.

    Boot waits on this, and every call in it talks to a daemon that can accept the
    connection and then never answer — a wedged overlay mount, a Docker Desktop
    still coming up. Per-call timeouts alone would still let a hundred leftovers
    add up to an hour of silent startup, so the budget covers the whole pass and
    whatever it cuts short is left for the next boot to finish."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _BUDGET_S
    stale = await _listed_names(
        [
            runtime, "ps", "-a",
            "--filter", f"name={names.container_filter}",
            "--format", "{{.Names}}",
        ],
        timeout_s=deadline - loop.time(),
    )
    removed = 0
    for name in stale:
        left = deadline - loop.time()
        if left <= 0:
            break
        await force_remove_container(runtime, name, timeout_s=left)
        removed += 1
    networks = await _listed_names(
        [
            runtime, "network", "ls",
            "--filter", f"name={names.network_filter}",
            "--format", "{{.Name}}",
        ],
        timeout_s=deadline - loop.time(),
    )
    dropped = 0
    for name in networks:
        left = deadline - loop.time()
        if left <= 0:
            break
        await remove_network(runtime, name, timeout_s=left)
        dropped += 1
    if stale or networks:
        logger.info(
            "sandbox: reconciled %d/%d stale container(s) and %d/%d network(s) from a "
            "previous run",
            removed,
            len(stale),
            dropped,
            len(networks),
        )


async def _listed_names(argv: list[str], *, timeout_s: float) -> list[str]:
    """The names a runtime listing prints, or none at all if it cannot answer.
    A runtime that is missing, down, or too old to understand the filter is a
    reason to skip reconciliation, never to fail a boot."""
    if timeout_s <= 0:
        return []
    try:
        _timed_out, code, out, err = await run_subprocess(argv, timeout_s=timeout_s)
    except SandboxError:
        logger.info("sandbox: could not list %s for reconciliation", argv[1], exc_info=True)
        return []
    if code != 0:
        logger.info(
            "sandbox: reconciliation listing failed: %s", err.decode("utf-8", "replace").strip()
        )
        return []
    lines = out.decode("utf-8", "replace").splitlines()
    return [line.strip() for line in lines if line.strip()]


def _remove_pool_dirs(work_root: Path) -> int:
    """Drop the neutral workspace dirs a previous build's pre-warmed container pool
    left under the work root. Nothing creates these any more — a container is worth
    having only once a conversation is running code in it — so any that remain are
    dead weight from an older process."""
    if not work_root.exists():
        return 0
    removed = 0
    for path in sorted(work_root.glob("_spare-*")):
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


def orphan_fork_keys(work_root: Path, taken: Container[str]) -> list[str]:
    """The delegated forks under ``work_root`` that nothing owns any more.

    A fork is the one workspace directory a crash can strand that nobody will ever ask
    for again: its files copy a parent workspace that still exists under its own key,
    and its delegation ended when the process died. Every other directory here is an
    ordinary conversation's files, which is not a leftover and must never be collected.

    ``taken`` is whatever the caller still considers live — the session map and its
    in-flight teardowns. Passed in rather than reached for, so this stays a pure reading
    of a directory and the caller keeps the answer atomic against its own maps.
    """
    if not work_root.exists():
        return []
    return [
        path.name
        for path in sorted(work_root.iterdir())
        if path.is_dir()
        and path.name.startswith("s")  # `safe_key`'s prefix — never a scratch dir
        and path.name not in taken
        and fork_marker(path).exists()
    ]
