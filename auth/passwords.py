"""Argon2id password hashing. Plain-text passwords are never stored or logged."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from auth.config import AUTH_SETTINGS

_HASHER: PasswordHasher | None = None


def _hasher() -> PasswordHasher:
    global _HASHER
    if _HASHER is None:
        _HASHER = PasswordHasher(
            time_cost=AUTH_SETTINGS.argon2_time_cost,
            memory_cost=AUTH_SETTINGS.argon2_memory_cost_kib,
            parallelism=AUTH_SETTINGS.argon2_parallelism,
            hash_len=32,
            salt_len=16,
        )
    return _HASHER


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _hasher().verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher().check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
