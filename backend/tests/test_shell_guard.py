"""Regression guard for the Operator Shell's core invariant (`SHELL-2`): it is
**agent-unreachable by construction**. Nothing under `tools/`, `agent/`, or
`research/` may reference `services/host_shell.py` or `ShellService` — a model
that could reach a host shell would blow through every sensitive-action
approval gate at once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_FORBIDDEN = ("host_shell", "ShellService")
_SCAN_DIRS = ("tools", "agent", "research")


def _source_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [path for dirname in _SCAN_DIRS for path in (root / dirname).rglob("*.py")]


def test_scan_dirs_contain_source_files() -> None:
    # A parametrize over a possibly-empty rglob list collects zero cases and
    # pytest reports the parametrized test below as SKIPPED, not FAILED — so a
    # renamed/missing scan dir would silently drop the SHELL-2 guard instead of
    # failing loudly. This asserts the scan actually found something to check.
    assert _source_files(), (
        f"expected source files under {_SCAN_DIRS} to scan — the SHELL-2 guard "
        "would otherwise pass vacuously"
    )


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: str(p))
def test_agent_reachable_code_never_references_the_shell(path: Path) -> None:
    text = path.read_text()
    for needle in _FORBIDDEN:
        assert needle not in text, (
            f"{path} references {needle!r} — the Operator Shell must stay "
            "agent-unreachable by construction"
        )
