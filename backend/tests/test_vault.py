"""Crypto primitives and the vault: key derivation, wrap/unwrap, lock/unlock."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from core import crypto
from core.vault import Vault, VaultError, VaultLocked


# --- primitives --------------------------------------------------------------
def test_aead_round_trip():
    key = crypto.generate_dek()
    blob = crypto.aead_encrypt(key, b"secret", b"aad")
    assert crypto.aead_decrypt(key, blob, b"aad") == b"secret"


def test_aead_rejects_tampering():
    key = crypto.generate_dek()
    blob = bytearray(crypto.aead_encrypt(key, b"secret"))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        crypto.aead_decrypt(key, bytes(blob))


def test_password_hash_and_verify():
    h = crypto.hash_password("hunter2")
    assert crypto.verify_password(h, "hunter2")
    assert not crypto.verify_password(h, "wrong")


def test_kek_is_deterministic_per_salt():
    salt = crypto.generate_salt()
    assert crypto.derive_kek("pw", salt) == crypto.derive_kek("pw", salt)
    assert crypto.derive_kek("pw", salt) != crypto.derive_kek("pw", crypto.generate_salt())


# --- vault -------------------------------------------------------------------
async def test_setup_then_encrypt_decrypt(tmp_path):
    vault = Vault(tmp_path / "keyfile.json")
    assert not vault.is_initialized
    await vault.setup("operator-pw")
    assert vault.is_initialized and vault.is_unlocked

    token = vault.encrypt_str("private note")
    assert token != "private note"
    assert vault.decrypt_str(token) == "private note"


async def test_locked_vault_cannot_encrypt(tmp_path):
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    token = vault.encrypt_str("note")
    vault.lock()
    assert not vault.is_unlocked
    with pytest.raises(VaultLocked):
        vault.decrypt_str(token)


async def test_unlock_round_trip_across_restart(tmp_path):
    keyfile = tmp_path / "keyfile.json"
    vault = Vault(keyfile)
    await vault.setup("pw")
    token = vault.encrypt_str("note")

    # a fresh Vault over the same keyfile starts locked (restart)
    restarted = Vault(keyfile)
    assert restarted.is_initialized and not restarted.is_unlocked
    assert await restarted.unlock("wrong") is False
    assert await restarted.unlock("pw") is True
    assert restarted.decrypt_str(token) == "note"


async def test_setup_twice_and_unlock_uninitialized(tmp_path):
    vault = Vault(tmp_path / "keyfile.json")
    await vault.setup("pw")
    with pytest.raises(VaultError):
        await vault.setup("pw")

    fresh = Vault(tmp_path / "other.json")
    with pytest.raises(VaultError):
        await fresh.unlock("pw")
