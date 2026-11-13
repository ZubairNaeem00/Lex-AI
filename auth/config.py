"""Authentication settings read from the environment."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AuthSettings:
    secret: str
    secret_is_generated: bool
    algorithm: str
    access_ttl_minutes: int
    refresh_ttl_days: int
    issuer: str
    audience: str
    argon2_time_cost: int
    argon2_memory_cost_kib: int
    argon2_parallelism: int
    require_email_verification: bool
    verification_ttl_hours: int
    reset_ttl_minutes: int
    auth_required: bool
    rate_limit_enabled: bool
    login_limit: str
    register_limit: str
    email_check_limit: str
    refresh_limit: str
    reset_limit: str

    @classmethod
    def from_env(cls) -> "AuthSettings":
        secret = os.getenv("JWT_SECRET", "").strip()
        generated = not secret
        if generated:
            # A random per-process secret keeps the local demo working; tokens
            # simply stop validating after a restart.
            secret = secrets.token_urlsafe(48)
        return cls(
            secret=secret,
            secret_is_generated=generated,
            algorithm=os.getenv("JWT_ALGORITHM", "HS256").strip() or "HS256",
            access_ttl_minutes=_env_int("ACCESS_TOKEN_TTL_MINUTES", 30),
            refresh_ttl_days=_env_int("REFRESH_TOKEN_TTL_DAYS", 30),
            issuer=os.getenv("JWT_ISSUER", "ai-law-agent").strip() or "ai-law-agent",
            audience=os.getenv("JWT_AUDIENCE", "ai-law-agent-api").strip() or "ai-law-agent-api",
            argon2_time_cost=_env_int("ARGON2_TIME_COST", 3),
            argon2_memory_cost_kib=_env_int("ARGON2_MEMORY_COST_KIB", 65536),
            argon2_parallelism=_env_int("ARGON2_PARALLELISM", 2),
            require_email_verification=_env_bool("REQUIRE_EMAIL_VERIFICATION", False),
            verification_ttl_hours=_env_int("EMAIL_VERIFICATION_TTL_HOURS", 48),
            reset_ttl_minutes=_env_int("PASSWORD_RESET_TTL_MINUTES", 20),
            auth_required=_env_bool("AUTH_REQUIRED", False),
            rate_limit_enabled=_env_bool("RATE_LIMIT_ENABLED", True),
            login_limit=os.getenv("LOGIN_RATE_LIMIT", "10/minute").strip() or "10/minute",
            register_limit=os.getenv("REGISTER_RATE_LIMIT", "5/hour").strip() or "5/hour",
            email_check_limit=os.getenv("EMAIL_CHECK_RATE_LIMIT", "30/hour").strip() or "30/hour",
            refresh_limit=os.getenv("REFRESH_RATE_LIMIT", "30/hour").strip() or "30/hour",
            reset_limit=os.getenv("RESET_RATE_LIMIT", "5/hour").strip() or "5/hour",
        )


AUTH_SETTINGS = AuthSettings.from_env()
