"""The vault — the operator's encryption key, held only in memory.

On disk lives a small keyfile: the login verifier, the KEK salt, and the DEK
wrapped under the password-derived KEK. The **DEK itself is never written** — it
is unwrapped into memory at unlock and wiped at lock, so a restart leaves the
system locked and the data unreadable until the operator unlocks again. No OS
keystore is involved, which keeps this byte-for-byte identical across platforms.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from pathlib import Path

from core import crypto

logger = logging.getLogger(__name__)

_KEYFILE_VERSION = 1


class VaultLocked(Exception):
    """Raised when encrypt/decrypt is attempted while the vault is locked."""


class VaultError(Exception):
    """Setup/unlock misuse (already initialized, not initialized, …)."""


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _b64d(text: str) -> bytes:
    return base64.b64decode(text)


class Vault:
    def __init__(self, keyfile: Path) -> None:
        self._keyfile = keyfile
        self._dek: bytes | None = None
        self._unlocked = asyncio.Event()  # lets lock-aware workers wait on unlock
        # Callbacks other services register to react to a lock without the auth
        # route (or this class) knowing who they are — e.g. the operator shell
        # tearing down every live PTY session the instant the vault re-locks.
        self._on_lock: list[Callable[[], None]] = []

    @property
    def is_initialized(self) -> bool:
        return self._keyfile.exists()

    @property
    def is_unlocked(self) -> bool:
        return self._dek is not None

    @property
    def unlocked_event(self) -> asyncio.Event:
        return self._unlocked

    async def setup(self, password: str) -> None:
        """First run: mint a DEK, wrap it under the password, write the keyfile."""
        if self.is_initialized:
            raise VaultError("vault already initialized")
        dek = crypto.generate_dek()
        salt = crypto.generate_salt()
        kek = await asyncio.to_thread(crypto.derive_kek, password, salt)
        keyfile = {
            "version": _KEYFILE_VERSION,
            "verifier": crypto.hash_password(password),
            "kek_salt": _b64e(salt),
            "wrapped_dek": _b64e(crypto.aead_encrypt(kek, dek)),
        }
        self._keyfile.parent.mkdir(parents=True, exist_ok=True)
        self._keyfile.write_text(json.dumps(keyfile))
        self._set_dek(dek)

    async def unlock(self, password: str) -> bool:
        """Verify the password and unwrap the DEK into memory. False on bad password."""
        if not self.is_initialized:
            raise VaultError("vault not initialized")
        data = json.loads(self._keyfile.read_text())
        if not crypto.verify_password(data["verifier"], password):
            return False
        kek = await asyncio.to_thread(crypto.derive_kek, password, _b64d(data["kek_salt"]))
        try:
            dek = crypto.aead_decrypt(kek, _b64d(data["wrapped_dek"]))
        except Exception:  # noqa: BLE001 — any unwrap failure is just a failed unlock
            return False
        self._set_dek(dek)
        return True

    def verify_password(self, password: str) -> bool:
        """Check the password against the stored verifier without unlocking —
        doesn't touch ``_dek``. Used by host-mode re-authentication, which needs
        proof of the password without granting/renewing decrypt access."""
        if not self.is_initialized:
            return False
        data = json.loads(self._keyfile.read_text())
        return crypto.verify_password(data["verifier"], password)

    def register_on_lock(self, cb: Callable[[], None]) -> None:
        """Register a callback fired synchronously from `lock()`. Lets a
        capability (like the operator shell) react to a lock without this class
        knowing about it."""
        self._on_lock.append(cb)

    def lock(self) -> None:
        self._dek = None
        self._unlocked.clear()
        for cb in self._on_lock:
            try:
                cb()
            except Exception:  # noqa: BLE001 — one bad callback must not block the lock
                logger.exception("vault: on-lock callback failed")

    def encrypt_str(self, plaintext: str) -> str:
        return _b64e(crypto.aead_encrypt(self._require_dek(), plaintext.encode()))

    def decrypt_str(self, token: str) -> str:
        return crypto.aead_decrypt(self._require_dek(), _b64d(token)).decode()

    def encrypt_bytes(self, raw: bytes) -> bytes:
        """Seal a raw blob (e.g. a workspace archive) — returned bytes go to disk."""
        return crypto.aead_encrypt(self._require_dek(), raw)

    def decrypt_bytes(self, token: bytes) -> bytes:
        return crypto.aead_decrypt(self._require_dek(), token)

    def _set_dek(self, dek: bytes) -> None:
        self._dek = dek
        self._unlocked.set()

    def _require_dek(self) -> bytes:
        if self._dek is None:
            raise VaultLocked("vault is locked")
        return self._dek
