"""What the agent already has on disk, told to it once per turn.

The model's own file tools report only the call they just made — `code_execute`
returns two streams, `files_write_file` returns a byte count — and nothing has ever
put the *state* of the workspace in front of it. So knowing what it had already built
depended entirely on the tool calls still being in the replayed history, and a
compaction (`agent/summarize.py`) replaces that stretch with a summary. Past the fold,
a conversation's own files became invisible to it, and it rebuilt them.

This block is the fix, and it is deliberately the dullest possible one: read the
directory, list what is in it, every turn. It is derived from disk rather than
remembered, so it is correct after a fold, after a reap, after a restart, and after a
turn that the model itself has forgotten.

**It goes at the tail, and that placement is the whole cost argument.** A file listing
changes on nearly every step, and a changing block at the *head* of the request
invalidates the inference engine's prompt-prefix cache from byte 0 for the entire
conversation behind it (`tools/deps.py`, `agent/factory.py`). At the tail it is a few
hundred tokens on the turn it rides, and the history in front of it stays byte-stable.

**It creates nothing.** Not a session, not a directory — see `settled_workspace`. A
turn that never touches a file must not pay for a container's worth of bookkeeping to
be told there is nothing to say.
"""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings
from services.modes import mode_spec
from services.sandbox import SandboxSessionManager
from services.sandbox.walk import walk_files
from services.workspace import SANDBOX_MOUNT

from .deps import PromptContextRequest

# Rendered above the listing. Static, so it belongs here rather than in the churn: the
# block's *content* is what changes turn to turn.
_PREAMBLE = (
    "Files already in your workspace, read from disk just now. This is the whole of it "
    "— work you did earlier in this conversation is here, including work from before "
    "anything you can still see in the history above. Read a file before assuming what "
    "is in it, and do not rebuild something that is already listed."
)

# How many entries the listing names before it starts counting instead. A workspace with
# a few hundred files is ordinary once a build has run; one with ten thousand is a
# `node_modules` the walk already prunes, or a checkout, and neither is worth a token.
# Chosen to stay a few hundred tokens at the tail rather than to be a real ceiling on
# what the agent may keep.
_MAX_ENTRIES = 200


def _human(size: int) -> str:
    """A file's size in the shortest honest form. Bytes up to a kilobyte, then one
    decimal — precision below that is noise in a block the model skims."""
    if size < 1024:
        return f"{size}B"
    for unit, scale in (("K", 1024), ("M", 1024**2), ("G", 1024**3)):
        if size < scale * 1024 or unit == "G":
            return f"{size / scale:.1f}{unit}"
    return f"{size}B"  # unreachable; the loop returns at G


def _listing(root: Path, excludes: tuple[str, ...]) -> str:
    """The workspace as ``path  size`` lines, newest first past the cap.

    Sorted by path so the common case reads like a directory and two consecutive turns
    produce the same block for the same files. The *cap* is applied by modification time
    instead — if something has to be dropped, what the agent touched most recently is
    what it is most likely to be working on.
    """
    entries: list[tuple[float, str, int]] = []
    for rel, full in walk_files(root, excludes):
        try:
            stat = full.stat()
        except OSError:  # vanished mid-walk — the agent's own process may be writing
            continue
        entries.append((stat.st_mtime, rel, stat.st_size))
    if not entries:
        return ""

    total = len(entries)
    entries.sort(key=lambda e: e[0], reverse=True)
    kept = entries[:_MAX_ENTRIES]
    lines = [
        f"{SANDBOX_MOUNT}/{rel}  {_human(size)}"
        for _mtime, rel, size in sorted(kept, key=lambda e: e[1])
    ]
    if total > len(kept):
        # Naming the directories rather than only the count: "and 4,812 more" tells the
        # model nothing it can act on, while the directories tell it where to look.
        elided = sorted(
            {rel.split("/", 1)[0] for _m, rel, _s in entries[_MAX_ENTRIES:] if "/" in rel}
        )
        where = f" (mostly under {', '.join(elided[:6])})" if elided else ""
        lines.append(f"… and {total - len(kept)} more{where} — list a directory to see them.")
    return "\n".join(lines)


async def workspace_context(req: PromptContextRequest) -> str:
    """This conversation's files, for the tail of this turn's prompt.

    Empty — no block at all — in the three cases where it would be noise: a thread whose
    workspace is a real checkout, one that has never put a file anywhere, and one whose
    sandbox is unavailable. That is the same discipline `tasks_context` follows for an
    empty task list: a heading over nothing is a heading the model has to read.
    """
    # A worktree is the operator's own repository, with git in it and `repo_instructions`
    # already describing it. Listing thousands of tracked files every turn would be the
    # expensive half of this idea with none of the benefit — the agent there has never
    # been the one who does not know what is on disk.
    if mode_spec(req.mode).workspace == "worktree":
        return ""
    sessions = req.caps.get_optional(SandboxSessionManager)
    if sessions is None:
        return ""
    root = sessions.settled_workspace(req.workspace_key)
    if root is None:
        return ""
    listing = _listing(root, get_settings().sandbox_walk_excludes)
    return f"{_PREAMBLE}\n\n{listing}" if listing else ""
