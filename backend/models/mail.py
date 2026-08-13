"""Mail schema (`EMAIL-*`) — **reserved stub**, filled in by the mail track (T1).

Imported by ``migrations/env.py`` from this commit so the parallel sprint tracks never
contend for that import block. Declares no tables yet, so ``alembic check`` stays clean.

For the track that fills this in: a ``MailAccount``'s per-account secrets — an IMAP password,
or an OAuth ``{access_token, refresh_token, expires_at, scope}`` bundle — belong in a sealed
column here, sealed with the vault exactly like ``ModelEndpoint.api_key``. Do **not** reuse
``ServiceCredential``: it is a static-catalog, one-key-per-service table (its own docstring
says it is "not inbound auth") and cannot express multiple accounts per provider, refresh
tokens, or expiry. The OAuth *client* registration (Google/Microsoft client id + secret) is
a different thing and does belong in ``ServiceCredential``'s catalog.
"""

from __future__ import annotations
