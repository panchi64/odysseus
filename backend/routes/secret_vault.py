"""Password vault — the operator's secrets manager (`VAULT-1..2`) — **reserved stub**,
filled in by the vault/backup track (T4).

Distinct from ``core/vault``: that is the password-derived at-rest key custody that unlocks
the app at login. This is the user-facing place to keep credentials, with its own lock. The
module is named ``secret_vault`` rather than ``vault`` so ``app.py`` can import it plainly
alongside its local ``vault`` handle on the key custody — same reason the ``deps`` accessor
is ``secret_vault()``.

See ``routes/mail.py`` for why the surface is registered before it exists.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/vault", tags=["vault"])
