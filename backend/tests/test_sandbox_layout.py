"""The shape of the sandbox package itself: three modules with one reason to change
each, and one public surface everything outside the package binds to.

Both halves are regressions that only ever creep back. ``session.py`` grew past a
thousand lines by accumulating the archive format and the whole live-session policy
alongside the one container it is actually about; a size ceiling is the cheapest thing
that notices. And the names below are what every importer outside ``services.sandbox``
uses — moving a class between modules must stay invisible to them.
"""

from __future__ import annotations

from pathlib import Path

import services.sandbox as sandbox_pkg

# Generous rather than tight: this is a ceiling that catches a module quietly absorbing
# a second job, not a style rule about the length any of them happens to be today.
_MAX_LINES = 700

_MODULES = ("seal.py", "session.py", "manager.py")


def test_each_sandbox_module_stays_one_reason_to_change():
    package = Path(sandbox_pkg.__file__).parent
    too_long = {
        name: len((package / name).read_text().splitlines())
        for name in _MODULES
        if len((package / name).read_text().splitlines()) > _MAX_LINES
    }
    assert not too_long, f"over {_MAX_LINES} lines: {too_long}"


def test_the_package_still_exposes_the_names_importers_bind_to():
    for name in ("SandboxSession", "SandboxSessionManager", "LiveWork", "PreviewHandle"):
        assert hasattr(sandbox_pkg, name)
        assert name in sandbox_pkg.__all__
