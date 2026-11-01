"""Audit trail: what the caller did, newest first."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from auth.deps import AuthenticatedUser, get_current_user
from services import activity_service

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", summary="My recent activity")
def list_activity(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=25, ge=1, le=200),
    action: Optional[str] = Query(default=None, max_length=120),
    resource_type: Optional[str] = Query(default=None, max_length=80),
) -> Dict[str, Any]:
    return activity_service.list_for_user(user.id, page=page, page_size=page_size,
                                          action=action or "",
                                          resource_type=resource_type or "")


@router.get("/recent", summary="The last few actions")
def recent_activity(user: AuthenticatedUser = Depends(get_current_user),
                    limit: int = Query(default=10, ge=1, le=50)) -> Dict[str, Any]:
    return {"items": activity_service.recent(user.id, limit=limit)}
