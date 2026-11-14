"""Account profile, sessions and per-user totals.

Nothing here accepts a user id from the client: the subject always comes from the
access token, so these routes can only ever describe the caller's own account.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from auth.deps import AuthenticatedUser, client_ip, get_current_user
from db.config import database
from db.schemas import (
    ChangePasswordRequest,
    ProfileUpdateRequest,
)
from services import activity_service, auth_service, case_service
from services.notification_service import unread_count

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", summary="Current account")
def me(user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    profile = auth_service.get_profile(user.id)
    profile["counts"] = case_service.stats(user)
    profile["notifications_unread"] = unread_count(user.id)
    return profile


@router.patch("/me", summary="Update the account profile")
def update_me(payload: ProfileUpdateRequest,
              user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return auth_service.update_profile(user.id, payload)


@router.post("/me/password", summary="Change password (revokes all sessions)")
def change_password(payload: ChangePasswordRequest, request: Request,
                    user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return auth_service.change_password(user.id, payload.current_password,
                                        payload.new_password, ip=client_ip(request))


@router.get("/me/sessions", summary="Active sign-ins for this account")
def sessions(user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    rows = auth_service.active_sessions(user.id)
    return {
        "items": [
            {
                "id": str(row["_id"]),
                "login_at": row.get("login_at"),
                "last_used_at": row.get("last_used_at"),
                "expires_at": row.get("expires_at"),
                "ip_address": row.get("ip_address", ""),
                "user_agent": row.get("user_agent", ""),
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.delete("/me/sessions/{session_id}", summary="Revoke one sign-in")
def revoke_session(session_id: str,
                   user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return {"ok": auth_service.revoke_session(user.id, session_id)}


@router.delete("/me/sessions", summary="Revoke every sign-in")
def revoke_sessions(user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return auth_service.logout_all(user.id)


@router.get("/me/summary", summary="Dashboard totals for this account")
def summary(user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "counts": case_service.stats(user),
        "recent_activity": activity_service.recent(user.id, limit=8),
        "database": database.status(),
    }
