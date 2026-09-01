"""Suite-wide defaults that keep tests independent of the host they run on.

Settings are read fresh from the environment on every ``get_settings()`` call, so the
place to pin a test-only default is the environment, before any test imports a module
that reads one.

The two patches below are installed at *import* time rather than from a fixture. Both
targets are bound by name at module scope (``from core.db import init_db``, and
``core.crypto``'s module-level hasher), and this file is imported before any test module
is collected — so patching here is what reaches every caller, including the ones inside
``app.py``.
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

import core.crypto  # noqa: E402 — must follow the environment default above
import core.db  # noqa: E402

from . import _schema  # noqa: E402

# Every test database otherwise replays the full Alembic chain; see `_schema`.
core.db.init_db = _schema.init_db

# Argon2id is deliberately costly — 64 MiB over three passes — and every booted test app
# pays two of them, a login verifier and a key-encryption key. That is real seconds per
# run spent re-proving that a slow KDF is slow. What these tests are about is the *shape*
# of the scheme (a DEK only the right passphrase unwraps, a verifier that rejects a wrong
# one, a stale verifier that gets re-minted), and none of that reads the work factors, so
# they go to Argon2's floor here. Production takes its parameters from `core.crypto`
# unchanged; nothing in this file is imported outside the suite.
core.crypto._KEK_TIME_COST = 1
core.crypto._KEK_MEMORY_COST = 8
core.crypto._KEK_PARALLELISM = 1
core.crypto._PASSWORD_HASHER = core.crypto.PasswordHasher(
    time_cost=1, memory_cost=8, parallelism=1
)
