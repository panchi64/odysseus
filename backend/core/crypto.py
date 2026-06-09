"""Low-level cryptographic primitives for at-rest encryption.

AES-256-GCM protects content: it stays secure against quantum-capable
adversaries at the symmetric level (Grover only halves the strength, leaving
~128-bit). Argon2id stretches the operator's password two independent ways — a
login verifier and a key-encryption key — so the stored login hash is useless
for decryption.
"""

from __future__ import annotations

import os

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Argon2id work factors for key derivation (deliberately costly).
_KEK_TIME_COST = 3
_KEK_MEMORY_COST = 65536  # 64 MiB
_KEK_PARALLELISM = 4
_KEK_LEN = 32

_NONCE_LEN = 12
_SALT_LEN = 16

_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """A verifier-only Argon2id hash (PHC string) for login checks."""
    return _PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def derive_kek(password: str, salt: bytes) -> bytes:
    """Derive the 256-bit key-encryption key from the password (CPU-heavy)."""
    return hash_secret_raw(
        password.encode(),
        salt,
        time_cost=_KEK_TIME_COST,
        memory_cost=_KEK_MEMORY_COST,
        parallelism=_KEK_PARALLELISM,
        hash_len=_KEK_LEN,
        type=Type.ID,
    )


def generate_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def generate_salt() -> bytes:
    return os.urandom(_SALT_LEN)


def aead_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """AES-256-GCM; returns ``nonce || ciphertext`` (nonce is random per call)."""
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def aead_decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, aad)
