"""The two directions a workspace travels between disk and the vault.

A conversation's files live as a plaintext directory while its container is up and
as one sealed archive the rest of the time, and the crossing between those two
states is the only thing in here: what an archive keeps, how it is written, how it
is read back, and the marker that says a directory is a *fragment* of one.

Kept apart from the session and the manager because it is the only part of the
warm-container model that is pure disk work — no container, no loop, no locks — and
because both of the other two need it: the session seals and restores its own
workspace, the manager sweeps directories no session owns. A single home for the
archive format means the two can never drift into disagreeing about what a sealed
workspace is.
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from core.vault import Vault

from .base import SandboxError


def excluded(arcname: str, excludes: Iterable[str]) -> bool:
    parts = Path(arcname).parts
    return any(fnmatch(part, pat) for part in parts for pat in excludes)


def seal_workspace(workspace: Path, excludes: Iterable[str], vault: Vault) -> bytes:
    """A gzip tar of the workspace, minus the excluded bloat, sealed by the vault.

    Only regular files and directories are archived. Symlinks/hardlinks/devices —
    which the agent (root in the box) can create — are dropped: an unsafe link
    would otherwise make the whole archive un-restorable under the ``data`` filter,
    losing every file with it."""

    def keep(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if excluded(ti.name, excludes) or not (ti.isfile() or ti.isdir()):
            return None
        return ti

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(workspace.iterdir()):
            if excluded(item.name, excludes):
                continue
            tar.add(item, arcname=item.name, filter=keep)
    return vault.encrypt_bytes(buf.getvalue())


def partial_marker(workspace: Path) -> Path:
    """The flag that says: this directory is a *fragment* of the sealed archive, and
    the archive is the complete copy.

    Both directions between archive and plaintext are multi-step, and the process can
    die between the steps — mid-extract on a restore, mid-``rmtree`` after a seal.
    Either leaves a directory indistinguishable, from the outside, from a workspace an
    unclean shutdown stranded whole. That only became dangerous once something started
    adopting such directories on sight (the manager's orphan sweep): sealing a fragment
    back over the archive it came from destroys every file the interrupted step never
    reached. A sibling of the workspace rather than a file inside it, so it can never
    end up in an archive.
    """
    return workspace.with_name(workspace.name + ".partial")


def restore_workspace(blob: bytes, workspace: Path, vault: Vault) -> None:
    marker = partial_marker(workspace)
    try:
        raw = vault.decrypt_bytes(blob)
        # The marker goes down *before* the directory it describes. Dying between the
        # two the other way round leaves an empty, unmarked workspace beside a complete
        # archive — which is precisely the shape the orphan sweep adopts and seals back
        # over that archive, losing every file the conversation owned.
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        workspace.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(workspace, filter="data")  # 'data' guards path traversal
    except Exception as exc:  # noqa: BLE001 — a damaged seal is a legible failure, not a crash
        raise SandboxError(f"could not restore the sandbox workspace: {exc}") from exc
    marker.unlink(missing_ok=True)
