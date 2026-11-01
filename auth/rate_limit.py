"""Per-IP rate limiting for the authentication endpoints (SlowAPI)."""

from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from auth.config import AUTH_SETTINGS

limiter = Limiter(
    key_func=get_remote_address,
    enabled=AUTH_SETTINGS.rate_limit_enabled,
    strategy="fixed-window",
    default_limits=[],
)

login_limit = limiter.limit(AUTH_SETTINGS.login_limit)
register_limit = limiter.limit(AUTH_SETTINGS.register_limit)
refresh_limit = limiter.limit(AUTH_SETTINGS.refresh_limit)
reset_limit = limiter.limit(AUTH_SETTINGS.reset_limit)


def configure(app) -> None:
    """Wire the limiter into FastAPI; called from main.py at startup."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
