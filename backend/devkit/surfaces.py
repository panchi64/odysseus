"""Writing the files a future session will actually read.

Both of the surfaces a fresh Claude Code session reads — ``.claude/`` and ``CLAUDE.md``
— are gitignored, on purpose. That has a consequence worth stating plainly, because it
is the whole reason this module exists: **writing them by hand solves this session and
nothing after it.** A new clone does not have them. A new git worktree does not have
them, and this project is developed in several worktrees at once, so "a new worktree"
is the ordinary case rather than the rare one.

So the committed source of truth is ``docs/dev-instance.md``, and these are materialized
from it on every ``up``. A fresh checkout gets them the first time anyone starts an
instance, and they are rewritten afterwards — which matters more than it sounds, since
they carry this instance's ports, and a stale copy would point a session at another
worktree's instance.

Writes are confined to the files named here, and the ``CLAUDE.md`` one is a delimited
block replaced in place. The operator's own notes live in that file too.
"""

from __future__ import annotations

import json
from pathlib import Path

from devkit import repo
from devkit.instance import DevInstance


def launch_config(instance: DevInstance, config_name: str) -> dict[str, object]:
    """The Claude Code launch configuration that opens this instance in the browser pane.

    It has no command: ``up`` owns starting the services, and a second launcher racing it
    would fight over ports. An entry with only a ``url`` attaches to what is already
    running, which is exactly the relationship wanted here.
    """
    return {
        "version": "0.0.1",
        "configurations": [
            {
                "name": config_name,
                "url": instance.frontend_url,
                "port": instance.frontend_port,
            }
        ],
    }


def write_launch_json(instance: DevInstance, config_name: str, root: Path | None = None) -> Path:
    """Write ``.claude/launch.json``, preserving any configurations we do not own."""
    claude_dir = (root or repo.CLAUDE_DIR)
    claude_dir.mkdir(parents=True, exist_ok=True)
    path = claude_dir / "launch.json"

    ours = launch_config(instance, config_name)
    configurations = list(ours["configurations"])  # type: ignore[arg-type]
    if path.is_file():
        try:
            existing = json.loads(path.read_text())
        except (OSError, ValueError):
            existing = {}
        # Anything the operator added stays. Only the entry carrying our name is ours to
        # rewrite, and it has to be rewritten because it holds a port that can move.
        configurations += [
            entry
            for entry in existing.get("configurations", [])
            if isinstance(entry, dict) and entry.get("name") != config_name
        ]
    path.write_text(json.dumps({"version": "0.0.1", "configurations": configurations}, indent=2)
                    + "\n")
    return path


def write_all(instance: DevInstance, root: Path | None = None) -> list[Path]:
    """Materialize every generated surface. Returns what was written, for reporting."""
    from devkit.launch import LAUNCH_CONFIG

    return [write_launch_json(instance, LAUNCH_CONFIG, root)]
