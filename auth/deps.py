"""FastAPI dependencies: who is calling, and may they touch this record?

`get_current_user` is used by every protected route. `get_optional_user` keeps the
existing demo usable without a token while still attributing data to the signed-in
user as soon as one is presented. Ownership is always resolved from the token —
a `user_id` in a request body or query string is never trusted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.config import AUTH_SETTINGS
from auth.tokens import ACCESS, TokenError, decode_token
from db import crud
from db.crud import to_oid
from db.models import AccountStatus
from db.schemas import AuthenticatedUser

_bearer = HTTPBearer(auto_error=False, description="JWT access token")


class Unauthorized(HTTPException):
    def __init__(self, message: str, code: str = "invalid_token") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": f"Bearer error=\"{code}\""},
        )


def _user_from_token(token: str) -> AuthenticatedUser:
    payload = decode_token(token, ACCESS)
    try:
        user_id = to_oid(payload.get("sub"), "sub")
    except ValueError as exc:
        raise Unauthorized("The token subject is not a valid user id.") from exc

    document = crud.users.get(user_id)
    if document is None:
        raise Unauthorized("The account no longer exists.", "unknown_subject")
    status_value = str(document.get("status") or AccountStatus.ACTIVE.value)
    if status_value == AccountStatus.DISABLED.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been disabled.")
    if status_value == AccountStatus.PENDING.value and AUTH_SETTINGS.require_email_verification:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email address first.")

    session_id = payload.get("sid")
    if session_id:
        session = crud.user_sessions.get(session_id)
        if session is None or session.get("revoked_at"):
            raise Unauthorized("This session has been revoked.", "revoked_session")

    return AuthenticatedUser(
        id=document["_id"],
        email=document.get("email", ""),
        full_name=document.get("full_name", ""),
        status=AccountStatus(status_value),
        token_id=str(payload.get("jti") or ""),
        session_id=str(session_id) if session_id else None,
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise Unauthorized("Authentication is required.", "missing_token")
    try:
        return _user_from_token(credentials.credentials)
    except TokenError as exc:
        raise Unauthorized(exc.message, exc.code) from exc


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[AuthenticatedUser]:
    """Anonymous callers get None; a bad token is still rejected."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        return _user_from_token(credentials.credentials)
    except TokenError as exc:
        raise Unauthorized(exc.message, exc.code) from exc


def current_user_or_anonymous(user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    return user


def require_authenticated(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return user


def deny_anonymous(user: Optional[AuthenticatedUser]) -> None:
    """Legacy AI routes: allow the token-less demo, but never cross users."""
    if user is None and AUTH_SETTINGS.auth_required:
        raise Unauthorized("Authentication is required.", "missing_token")


def owns(document: Optional[Dict[str, Any]], user: AuthenticatedUser) -> bool:
    if document is None:
        return False
    owner = document.get("user_id")
    try:
        return owner is not None and to_oid(owner, "user_id") == to_oid(user.id, "user_id")
    except ValueError:
        return False


def require_owned(document: Optional[Dict[str, Any]], what: str = "Record",
                  user: Optional[AuthenticatedUser] = None) -> Dict[str, Any]:
    """404 rather than 403 so another user's data cannot be probed."""
    if document is None or (user is not None and not owns(document, user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found.")
    return document


def client_ip(request: Optional[Request]) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:80]
    return (request.client.host if request.client else "") or ""
