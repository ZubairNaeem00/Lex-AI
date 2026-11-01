"""Accounts, sessions, tokens, verification and password reset.

Security rules enforced here:
- passwords are hashed with Argon2id and never returned or logged;
- refresh tokens are stored only as a keyed digest, so a database dump is useless;
- rotating a refresh token revokes the previous one (reuse invalidates the family);
- every login/refresh/logout is written to the activity log.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import HTTPException, status

from auth.config import AUTH_SETTINGS
from auth.passwords import hash_password, needs_rehash, verify_password
from auth.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)
from db import crud
from db.crud import Conflict, utc_now
from db.models import AccountStatus, User, UserProfile, UserSession
from db.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    ResetPasswordRequest,
    SignupRequest,
    UserRead,
)
from services import activity_service, email_service

# Constant work factor for unknown emails, so a probe cannot be timed.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(24))


class AuthError(HTTPException):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(status_code=code, detail=message)


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _user_read(document: Dict[str, Any]) -> Dict[str, Any]:
    return UserRead.model_validate(document).model_dump(mode="json")


def _token_response(user_doc: Dict[str, Any], access: str, refresh: str,
                    access_ttl: int, refresh_ttl: int) -> Dict[str, Any]:
    return {
        # `token` is what the existing frontend reads after login/signup.
        "token": access,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": access_ttl,
        "refresh_expires_in": refresh_ttl,
        "user": _user_read(user_doc),
    }


def _open_session(user_id: Any, email: str, ip: str, user_agent: str,
                  family_id: Optional[str] = None) -> Dict[str, Any]:
    """Create one signed-in session; the refresh token is stored only as a digest."""
    session_id = ObjectId()
    refresh_token, _, family, refresh_expires = create_refresh_token(
        user_id, session_id, family_id=family_id
    )
    access_token, access_jti, access_expires = create_access_token(user_id, session_id)
    crud.user_sessions.insert(
        UserSession(
            id=session_id,
            user_id=user_id,
            refresh_token_hash=hash_token(refresh_token),
            family_id=family,
            access_jti=access_jti,
            ip_address=ip,
            user_agent=user_agent[:300],
            expires_at=refresh_expires,
        )
    )
    return {
        "session_id": str(session_id),
        "access_token": access_token,
        "access_expires_at": access_expires,
        "refresh_token": refresh_token,
        "refresh_expires_at": refresh_expires,
    }


def _email_taken(email: str) -> bool:
    return crud.users.exists({"email": email})


def signup(payload: SignupRequest, ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    email = normalize_email(payload.email)
    if _email_taken(email):
        raise AuthError(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    needs_verification = AUTH_SETTINGS.require_email_verification
    document = User(
        full_name=payload.full_name,
        email=email,
        password_hash=hash_password(payload.password),
        profile=UserProfile(occupation=payload.role or ""),
        status=AccountStatus.PENDING if needs_verification else AccountStatus.ACTIVE,
        email_verified=not needs_verification,
    )
    try:
        user_id = crud.users.insert(document)
    except Conflict as exc:
        raise AuthError(status.HTTP_409_CONFLICT, str(exc)) from exc

    stored = crud.users.get(user_id)
    activity_service.log(user_id, "account.signup", resource_type="user",
                         resource_id=user_id, ip_address=ip)
    activity_service.log(user_id, "account.profile_created", resource_type="user",
                         resource_id=user_id, ip_address=ip)

    verification_link = ""
    if needs_verification:
        verification_link = _issue_verification_token(user_id, email)
        email_service.send_email(
            email,
            "Verify your AI Law Agent account",
            "Welcome. Confirm this address to activate your account.",
            verification_link,
        )
    else:
        email_service.send_email(
            email,
            "Welcome to AI Law Agent",
            "Your account is ready. Cases, chats and documents are stored per user.",
        )

    if needs_verification:
        body = {"user": _user_read(stored), "verification_required": True}
        if email_service.show_links_enabled():
            body["verification_link"] = verification_link
        return body

    session = _open_session(user_id, email, ip, user_agent)
    response = _token_response(
        stored,
        session["access_token"],
        session["refresh_token"],
        AUTH_SETTINGS.access_ttl_minutes * 60,
        AUTH_SETTINGS.refresh_ttl_days * 24 * 3600,
    )
    response["verification_required"] = False
    return response


def _issue_verification_token(user_id: Any, email: str) -> str:
    raw = secrets.token_urlsafe(32)
    crud.users.set_by_id(
        user_id,
        {
            "verification_token_hash": hash_token(raw),
            "verification_expires_at": utc_now()
            + timedelta(hours=AUTH_SETTINGS.verification_ttl_hours),
        },
    )
    return email_service.public_link("/verify-email", raw)


def login(payload: LoginRequest, ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    email = normalize_email(payload.email)
    stored = crud.users.find_one({"email": email})
    if stored is None:
        verify_password(payload.password, _DUMMY_HASH)
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")

    ok = verify_password(payload.password, stored.get("password_hash", ""))
    if not ok:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")

    if stored.get("status") == AccountStatus.DISABLED.value:
        raise AuthError(status.HTTP_403_FORBIDDEN, "This account has been disabled.")
    if AUTH_SETTINGS.require_email_verification and not stored.get("email_verified"):
        activity_service.log(stored["_id"], "auth.login_blocked_unverified",
                             resource_type="user", resource_id=stored["_id"], ip_address=ip)
        raise AuthError(
            status.HTTP_403_FORBIDDEN,
            "Verify your email address before signing in. Use the link we sent you.",
        )

    if needs_rehash(stored.get("password_hash", "")):
        crud.users.set_by_id(stored["_id"], {"password_hash": hash_password(payload.password)})

    session = _open_session(stored["_id"], email, ip, user_agent)
    crud.users.set_by_id(stored["_id"], {"last_login_at": utc_now()})
    activity_service.log(stored["_id"], "auth.login", resource_type="user",
                         resource_id=stored["_id"], ip_address=ip)

    return _token_response(
        crud.users.get(stored["_id"]),
        session["access_token"],
        session["refresh_token"],
        AUTH_SETTINGS.access_ttl_minutes * 60,
        AUTH_SETTINGS.refresh_ttl_days * 24 * 3600,
    )


def refresh(refresh_token: str, ip: str = "", user_agent: str = "") -> Dict[str, Any]:
    try:
        payload = decode_token(refresh_token, "refresh")
    except TokenError as exc:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, exc.message) from exc

    digest = hash_token(refresh_token)
    session = crud.user_sessions.find_one({"refresh_token_hash": digest})
    if session is None:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "This refresh token is unknown.")
    if session.get("revoked_at"):
        # Token reuse after rotation: kill the whole family.
        revoke_family(session.get("family_id"), reason="reuse-detected")
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "This refresh token was already used.")

    user_doc = crud.users.get(session["user_id"])
    if user_doc is None or user_doc.get("status") == AccountStatus.DISABLED.value:
        raise AuthError(status.HTTP_403_FORBIDDEN, "This account cannot sign in.")

    crud.user_sessions.set_by_id(
        session["_id"],
        {"revoked_at": utc_now(), "revoked_reason": "rotated"},
    )
    new_session = _open_session(user_doc["_id"], user_doc.get("email", ""), ip, user_agent,
                                family_id=session.get("family_id"))
    activity_service.log(user_doc["_id"], "auth.token_refreshed", resource_type="user_session",
                         resource_id=new_session["session_id"], ip_address=ip)

    return _token_response(
        user_doc,
        new_session["access_token"],
        new_session["refresh_token"],
        AUTH_SETTINGS.access_ttl_minutes * 60,
        AUTH_SETTINGS.refresh_ttl_days * 24 * 3600,
    )


def logout(user_id: Any, refresh_token: Optional[str], ip: str = "") -> Dict[str, Any]:
    if refresh_token:
        digest = hash_token(refresh_token)
        revoked = crud.user_sessions.update(
            {"refresh_token_hash": digest, "user_id": user_id, "revoked_at": None},
            {"revoked_at": utc_now(), "revoked_reason": "logout"},
            return_document=False,
        )
        revoked = 1 if revoked else 0
    else:
        revoked = revoke_query(user_id, "logout")
    activity_service.log(user_id, "auth.logout", resource_type="user", resource_id=user_id,
                         detail=f"sessions revoked: {revoked}", ip_address=ip)
    return {"ok": True, "revoked_sessions": revoked}


def revoke_family(family_id: Optional[str], reason: str = "revoked") -> int:
    if not family_id:
        return 0
    result = crud.user_sessions.collection().update_many(
        {"family_id": family_id, "revoked_at": None},
        {"$set": {"revoked_at": utc_now(), "revoked_reason": reason, "updated_at": utc_now()}},
    )
    return int(result.modified_count)


def logout_all(user_id: Any, ip: str = "") -> Dict[str, Any]:
    count = revoke_query(user_id, "logout-all")
    activity_service.log(user_id, "auth.logout_all", resource_type="user",
                         resource_id=user_id, detail=f"sessions revoked: {count}", ip_address=ip)
    return {"ok": True, "revoked_sessions": count}


def revoke_query(user_id: Any, reason: str) -> int:
    result = crud.user_sessions.collection().update_many(
        {"user_id": crud.to_oid(user_id, "user_id"), "revoked_at": None},
        {"$set": {"revoked_at": utc_now(), "revoked_reason": reason, "updated_at": utc_now()}},
    )
    return int(result.modified_count)


def active_sessions(user_id: Any) -> list:
    return crud.user_sessions.find(
        {"user_id": user_id, "revoked_at": None},
        sort=[("login_at", -1)],
        projection={"refresh_token_hash": 0, "password_hash": 0},
    )


def revoke_session(user_id: Any, session_id: Any) -> bool:
    """Revoke one sign-in, but only if it belongs to the caller."""
    updated = crud.user_sessions.update(
        {"_id": session_id, "user_id": user_id, "revoked_at": None},
        {"revoked_at": utc_now(), "revoked_reason": "user-revoked"},
        return_document=False,
    )
    revoked = updated is not None
    if revoked:
        activity_service.log(user_id, "auth.session_revoked", resource_type="user_session",
                             resource_id=session_id)
    return revoked


def verify_email(token: str, ip: str = "") -> Dict[str, Any]:
    digest = hash_token(token)
    user_doc = crud.users.find_one({"verification_token_hash": digest})
    if user_doc is None:
        raise AuthError(status.HTTP_400_BAD_REQUEST, "This verification link is not valid.")
    expires = user_doc.get("verification_expires_at")
    if expires is not None and expires < utc_now():
        raise AuthError(status.HTTP_400_BAD_REQUEST, "This verification link has expired.")

    crud.users.set_by_id(
        user_doc["_id"],
        {
            "email_verified": True,
            "status": AccountStatus.ACTIVE,
            "verification_token_hash": None,
            "verification_expires_at": None,
        },
    )
    activity_service.log(user_doc["_id"], "auth.email_verified", resource_type="user",
                         resource_id=user_doc["_id"], ip_address=ip)
    email_service.send_email(user_doc.get("email", ""), "Your account is verified",
                             "You can now sign in and create cases.")
    return {"ok": True, "email": user_doc.get("email"), "user": _user_read(crud.users.get(user_doc["_id"]))}


def request_password_reset(payload: ForgotPasswordRequest, ip: str = "") -> Dict[str, Any]:
    email = normalize_email(payload.email)
    user_doc = crud.users.find_one({"email": email})
    link = ""
    if user_doc is not None:
        raw = secrets.token_urlsafe(32)
        link = email_service.public_link("/reset-password", raw)
        crud.users.set_by_id(
            user_doc["_id"],
            {
                "reset_token_hash": hash_token(raw),
                "reset_expires_at": utc_now() + timedelta(minutes=AUTH_SETTINGS.reset_ttl_minutes),
            },
        )
        email_service.send_email(
            email,
            "Reset your AI Law Agent password",
            "Use the link below to choose a new password. It expires in "
            f"{AUTH_SETTINGS.reset_ttl_minutes} minutes. If you did not request this, ignore it.",
            link,
        )
        activity_service.log(user_doc["_id"], "auth.password_reset_requested",
                             resource_type="user", resource_id=user_doc["_id"], ip_address=ip)
    response = {
        "ok": True,
        # Never confirm whether the address exists.
        "detail": "If that email is registered, a reset link has been sent.",
    }
    if link and email_service.show_links_enabled():
        response["reset_link"] = link
    return response


def reset_password(payload: ResetPasswordRequest, ip: str = "") -> Dict[str, Any]:
    digest = hash_token(payload.token)
    user_doc = crud.users.find_one({"reset_token_hash": digest})
    if user_doc is None:
        raise AuthError(status.HTTP_400_BAD_REQUEST, "This reset link is not valid.")
    expires = user_doc.get("reset_expires_at")
    if expires is not None and expires < utc_now():
        raise AuthError(status.HTTP_400_BAD_REQUEST, "This reset link has expired.")

    crud.users.set_by_id(
        user_doc["_id"],
        {
            "password_hash": hash_password(payload.new_password),
            "reset_token_hash": None,
            "reset_expires_at": None,
            "verification_token_hash": None,
        },
    )
    revoked = revoke_query(user_doc["_id"], "password-reset")
    activity_service.log(user_doc["_id"], "auth.password_reset", resource_type="user",
                         resource_id=user_doc["_id"], detail=f"sessions revoked: {revoked}",
                         ip_address=ip)
    email_service.send_email(user_doc.get("email", ""), "Your password was changed",
                             "If this was not you, contact support immediately.")
    return {"ok": True, "revoked_sessions": revoked,
            "detail": "Password updated. Please sign in again."}


def change_password(user_id: Any, current_password: str, new_password: str, ip: str = "") -> Dict[str, Any]:
    user_doc = crud.users.get(user_id)
    if user_doc is None:
        raise AuthError(status.HTTP_404_NOT_FOUND, "Account not found.")
    if not verify_password(current_password, user_doc.get("password_hash", "")):
        raise AuthError(status.HTTP_400_BAD_REQUEST, "Your current password is incorrect.")
    crud.users.set_by_id(user_id, {"password_hash": hash_password(new_password)})
    revoked = revoke_query(user_id, "password-changed")
    activity_service.log(user_id, "auth.password_changed", resource_type="user",
                         resource_id=user_id, detail=f"sessions revoked: {revoked}", ip_address=ip)
    return {"ok": True, "revoked_sessions": revoked, "detail": "Password updated."}


def get_profile(user_id: Any) -> Dict[str, Any]:
    user_doc = crud.users.get(user_id)
    if user_doc is None:
        raise AuthError(status.HTTP_404_NOT_FOUND, "Account not found.")
    return _user_read(user_doc)


def update_profile(user_id: Any, payload: ProfileUpdateRequest) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}
    if payload.full_name is not None:
        changes["full_name"] = payload.full_name
    if payload.profile is not None:
        existing = crud.users.get(user_id) or {}
        merged = {**(existing.get("profile") or {}), **payload.profile.model_dump(exclude_unset=True)}
        changes["profile"] = merged
    if not changes:
        raise AuthError(status.HTTP_400_BAD_REQUEST, "Provide at least one field to update.")
    updated = crud.users.set_by_id(user_id, changes)
    activity_service.log(user_id, "account.profile_updated", resource_type="user", resource_id=user_id)
    return _user_read(updated)
