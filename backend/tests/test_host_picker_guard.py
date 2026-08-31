"""Regression guard for the host file chooser: it is **agent-unreachable by
construction**, the same invariant the Operator Shell carries. Nothing under `tools/` or
`agent/` may reference `services/host_picker.py` — a model that could open dialogs on the
operator's desktop (and read back whatever path came out) would be acting on the host
outside every sensitive-action approval gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_FORBIDDEN = ("host_picker", "PickerAvailability")
_SCAN_DIRS = ("tools", "agent")


def _source_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return [path for dirname in _SCAN_DIRS for path in (root / dirname).rglob("*.py")]


def test_scan_dirs_contain_source_files() -> None:
    # A parametrize over a possibly-empty rglob list collects zero cases and pytest
    # reports the parametrized test below as SKIPPED, not FAILED — so a renamed/missing
    # scan dir would silently drop the guard instead of failing loudly.
    assert _source_files(), (
        f"expected source files under {_SCAN_DIRS} to scan — the host-picker guard "
        "would otherwise pass vacuously"
    )


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: str(p))
def test_agent_reachable_code_never_references_the_picker(path: Path) -> None:
    text = path.read_text()
    for needle in _FORBIDDEN:
        assert needle not in text, (
            f"{path} references {needle!r} — the host file chooser must stay "
            "agent-unreachable by construction"
        )
