"""JWT access and refresh tokens.

Access tokens are short-lived and carry only the user id, the session id and a jti.
Refresh tokens are opaque-ish JWTs whose SHA-256 hash is stored in `user_sessions`,
so a session can be revoked or rotated server-side.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt

from auth.config import AUTH_SETTINGS

ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_jti() -> str:
    return uuid.uuid4().hex


def _issue(user_id: str, token_type: str, ttl: timedelta, *, session_id: Optional[str] = None,
           jti: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> Tuple[str, str, datetime]:
    issued = _now()
    expires_at = issued + ttl
    identifier = jti or new_jti()
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "typ": token_type,
        "jti": identifier,
        "iss": AUTH_SETTINGS.issuer,
        "aud": AUTH_SETTINGS.audience,
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if session_id:
        payload["sid"] = str(session_id)
    payload.update(extra or {})
    token = jwt.encode(payload, AUTH_SETTINGS.secret, algorithm=AUTH_SETTINGS.algorithm)
    return token, identifier, expires_at


def create_access_token(user_id: Any, session_id: Optional[Any] = None,
                        ttl: Optional[timedelta] = None) -> Tuple[str, str, datetime]:
    return _issue(
        str(user_id),
        ACCESS,
        ttl or timedelta(minutes=AUTH_SETTINGS.access_ttl_minutes),
        session_id=str(session_id) if session_id else None,
    )


def create_refresh_token(user_id: Any, session_id: Any, family_id: Optional[str] = None,
                         ttl: Optional[timedelta] = None) -> Tuple[str, str, str, datetime]:
    """Return (token, jti, family_id, expires_at)."""
    family = family_id or new_jti()
    token, jti, expires_at = _issue(
        str(user_id),
        REFRESH,
        ttl or timedelta(days=AUTH_SETTINGS.refresh_ttl_days),
        session_id=str(session_id),
        extra={"fam": family},
    )
    return token, jti, family, expires_at


def hash_token(value: str) -> str:
    """Store only a digest of a token, never the token itself."""
    return hmac.new(AUTH_SETTINGS.secret.encode("utf-8"), value.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def decode_token(token: str, expected_type: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            AUTH_SETTINGS.secret,
            algorithms=[AUTH_SETTINGS.algorithm],
            audience=AUTH_SETTINGS.audience,
            issuer=AUTH_SETTINGS.issuer,
            options={"require": ["exp", "sub", "typ", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired", "The token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid", "The token is not valid.") from exc
    if payload.get("typ") != expected_type:
        raise TokenError("wrong_type", f"Expected a {expected_type} token.")
    return payload
