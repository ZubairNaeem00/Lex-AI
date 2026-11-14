"""Authentication routes.

Endpoints:
    POST /api/auth/register        create an account (also /signup alias)
    POST /api/auth/check-email     is this address still free to register?
    POST /api/auth/login           email + password -> access + refresh
    POST /api/auth/refresh         rotate the refresh token
    POST /api/auth/logout          revoke the presented session
    POST /api/auth/logout-all      sign out everywhere
    POST /api/auth/forgot-password request a reset link
    POST /api/auth/reset-password  consume a reset link
    POST /api/auth/verify-email    consume a verification link

The login response keeps a `token` field because that is what the existing
frontend already stores in localStorage.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from auth.deps import client_ip, get_current_user
from auth.rate_limit import email_check_limit, login_limit, refresh_limit, register_limit, reset_limit
from auth.config import AUTH_SETTINGS
from db.config import database
from db.schemas import (
    AuthenticatedUser,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    VerifyEmailRequest,
)
from services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = Field(default=None, max_length=4000)


class EmailCheckRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


def _meta(request: Request) -> Dict[str, str]:
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent", "")}


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Create an account")
@router.post("/signup", status_code=status.HTTP_201_CREATED, include_in_schema=False)
@register_limit
def register(payload: SignupRequest, request: Request) -> Dict[str, Any]:
    return auth_service.signup(payload, **_meta(request))


@router.post("/check-email", summary="Is this email free to register?")
@email_check_limit
def check_email(payload: EmailCheckRequest, request: Request) -> Dict[str, Any]:
    """Lets the signup form report a taken address on its first step.

    Rate limited because the answer reveals whether an address has an account.
    """
    email = auth_service.normalize_email(payload.email)
    return {"email": email, "available": auth_service.email_available(email)}


@router.post("/login", summary="Sign in")
@login_limit
def login(payload: LoginRequest, request: Request, response: Response) -> Dict[str, Any]:
    result = auth_service.login(payload, **_meta(request))
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/refresh", summary="Exchange a refresh token")
@refresh_limit
def refresh(payload: RefreshRequest, request: Request) -> Dict[str, Any]:
    return auth_service.refresh(payload.refresh_token, ip=client_ip(request))


@router.post("/logout", summary="Sign out of this device")
def logout(payload: LogoutRequest, request: Request,
           user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return auth_service.logout(user.id, payload.refresh_token, ip=client_ip(request))


@router.post("/logout-all", summary="Sign out everywhere")
def logout_all(request: Request,
               user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return auth_service.logout_all(user.id, ip=client_ip(request))


@router.post("/forgot-password", summary="Email a reset link")
@reset_limit
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> Dict[str, Any]:
    return auth_service.request_password_reset(payload, ip=client_ip(request))


@router.post("/reset-password", summary="Use a reset link")
@reset_limit
def reset_password(payload: ResetPasswordRequest, request: Request) -> Dict[str, Any]:
    return auth_service.reset_password(payload, ip=client_ip(request))


@router.post("/verify-email", summary="Confirm an email address")
@reset_limit
def verify_email(payload: VerifyEmailRequest, request: Request) -> Dict[str, Any]:
    return auth_service.verify_email(payload.token, ip=client_ip(request))


@router.get("/status", summary="Auth configuration for the client")
def auth_status() -> Dict[str, Any]:
    return {
        "database": database.settings.db_name,
        "database_connected": database.status()["connected"],
        "require_email_verification": AUTH_SETTINGS.require_email_verification,
        "auth_required": AUTH_SETTINGS.auth_required,
        "access_token_ttl_minutes": AUTH_SETTINGS.access_ttl_minutes,
        "refresh_token_ttl_days": AUTH_SETTINGS.refresh_ttl_days,
        "rate_limited": AUTH_SETTINGS.rate_limit_enabled,
    }
