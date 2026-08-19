"""Suite-wide defaults that keep tests independent of the host they run on.

Settings are read fresh from the environment on every ``get_settings()`` call, so the
place to pin a test-only default is the environment, before any test imports a module
that reads one.
"""

from __future__ import annotations

import os

# Host-command confinement is a *process-global* singleton (`sandbox-runtime` configures
# one sandbox for the whole interpreter). Several tests drive `code_run_host_command`
# through to a real `echo`, which would otherwise initialize that singleton from whatever
# settings the test happened to have — and then only on machines where the platform
# primitive is actually available, since it needs `ripgrep` on PATH. That makes the suite
# behave differently on two developers' laptops for reasons unrelated to what is being
# tested. Off here, so the host path under test is the plain subprocess; the confinement
# logic itself is exercised explicitly in `test_sandbox.py`, which configures it directly.
os.environ.setdefault("ODYSSEUS_HOST_COMMAND_SANDBOX_ENABLED", "false")
