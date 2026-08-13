"""Password-vault schema (`VAULT-*`) — **reserved stub**, filled in by the vault/backup
track (T4).

See ``models/mail.py`` for why the module is imported before it declares anything.

This is the operator's user-facing secrets manager — an additional encrypted layer on top of
at-rest encryption — and is deliberately distinct from ``core/vault``, the password-derived
key custody that unlocks the app at login. Its unlocked state is held **in memory only and
never persisted**, so nothing here records whether the vault is open.
"""

from __future__ import annotations
