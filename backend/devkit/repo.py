"""Where things are, relative to this file.

Derived from ``__file__`` rather than from the working directory, because half of what
the launcher does is run commands in a directory other than the one it was invoked from,
and a tool that only works when you are standing in the right place is a tool a future
session will run from the wrong one.
"""

from __future__ import annotations

from pathlib import Path

#: ``backend/`` — where the app, its virtualenv and its ``dev.py`` live.
BACKEND = Path(__file__).resolve().parent.parent

#: The repository root, whether a main checkout or a worktree.
ROOT = BACKEND.parent

#: ``frontend/`` — the vite dev server's directory.
FRONTEND = ROOT / "frontend"

#: Where Claude Code reads its per-project configuration. Gitignored, and therefore
#: generated rather than committed — see :mod:`devkit.surfaces`.
CLAUDE_DIR = ROOT / ".claude"
