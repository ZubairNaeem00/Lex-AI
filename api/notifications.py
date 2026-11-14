"""Notifications for the signed-in account."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.deps import AuthenticatedUser, get_current_user
from db import crud
from db.schemas import NotificationCreate, NotificationRead
from services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", summary="My notifications")
def list_notifications(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=25, ge=1, le=200),
    unread_only: bool = Query(default=False),
) -> Dict[str, Any]:
    result = notification_service.list_for_user(user.id, page=page, page_size=page_size,
                                                unread_only=unread_only)
    result["items"] = [
        NotificationRead.model_validate(item).model_dump(mode="json")
        for item in result["items"]
    ]
    result["unread"] = notification_service.unread_count(user.id)
    return result


@router.post("", status_code=status.HTTP_201_CREATED, summary="Save a note for myself")
def create_notification(payload: NotificationCreate,
                        user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    notification_id = notification_service.notify(user.id, payload.title, payload.message,
                                                  payload.kind, payload.metadata)
    document = crud.notifications.get(notification_id)
    return NotificationRead.model_validate(document).model_dump(mode="json")


@router.post("/read-all", summary="Mark everything read")
def read_all(user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return {"ok": True, "updated": notification_service.mark_all_read(user.id)}


@router.patch("/{notification_id}/read", summary="Mark one notification read")
def mark_read(notification_id: str, read: bool = Query(default=True),
              user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    document = crud.notifications.update(
        {"_id": notification_id, "user_id": user.id},
        {"read": read, "read_at": crud.utc_now() if read else None},
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    return NotificationRead.model_validate(document).model_dump(mode="json")


@router.delete("/{notification_id}", summary="Dismiss a notification")
def dismiss(notification_id: str,
            user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return {"ok": notification_service.remove(user.id, notification_id)}
