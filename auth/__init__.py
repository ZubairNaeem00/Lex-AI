"""Authentication and authorization helpers for the MongoDB-backed API."""

from auth.config import AUTH_SETTINGS
from auth.deps import current_user_or_anonymous, get_current_user, get_optional_user
from auth.passwords import hash_password, verify_password
from auth.tokens import TokenError, create_access_token, create_refresh_token, decode_token

__all__ = [
    "AUTH_SETTINGS",
    "TokenError",
    "create_access_token",
    "create_refresh_token",
    "current_user_or_anonymous",
    "decode_token",
    "get_current_user",
    "get_optional_user",
    "hash_password",
    "verify_password",
]
