"""Scoped API token schema (`AUTH-4`) — **reserved stub**, filled in by the platform track
(T6).

See ``models/mail.py`` for why the module is imported before it declares anything.

**Inbound** auth: tokens issued to clients for programmatic access. Distinct from
``ServiceCredential``, which holds the outbound keys this system calls other services with.
Store a one-way **hash** of each token, never the token itself — it is shown once at issue
and is unrecoverable afterwards, the same posture as the login password (`XC-SEC-3`).
"""

from __future__ import annotations
