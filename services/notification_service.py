"""In-app notifications per user."""

from __future__ import annotations

from typing import Any, Dict, Optional

from db import crud
from db.models import Notification, utc_now
from db.schemas import NotificationRead


def notify(user_id: Any, title: str, message: str = "", kind: str = "info",
           metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    try:
        return crud.notifications.insert(
            Notification(user_id=user_id, title=title[:200], message=message[:4000],
                         kind=kind[:60], metadata=metadata or {})
        )
    except Exception as exc:  # pragma: no cover - notifications are best effort
        print(f"[Notifications] could not store {title!r}: {type(exc).__name__}: {exc}", flush=True)
        return None


def list_for_user(user_id: Any, page: int = 1, page_size: int = 20, unread_only: bool = False) -> Dict[str, Any]:
    query: Dict[str, Any] = {"user_id": user_id}
    if unread_only:
        query["read"] = False
    result = crud.notifications.paginate(query, page=page, page_size=page_size,
                                         sort=[("created_at", -1)])
    result["items"] = [
        NotificationRead.model_validate(item).model_dump(mode="json")
        for item in result["items"]
    ]
    return result


def unread_count(user_id: Any) -> int:
    return crud.notifications.count({"user_id": user_id, "read": False})


def mark_read(user_id: Any, notification_id: Any) -> Optional[Dict[str, Any]]:
    return crud.notifications.update(
        {"_id": notification_id, "user_id": user_id},
        {"read": True, "read_at": utc_now()},
    )


def mark_all_read(user_id: Any) -> int:
    collection = crud.notifications.collection()
    return int(collection.update_many(
        {"user_id": crud.to_oid(user_id, "user_id"), "read": False},
        {"$set": {"read": True, "read_at": utc_now(), "updated_at": utc_now()}},
    ).modified_count)


def remove(user_id: Any, notification_id: Any) -> bool:
    collection = crud.notifications.collection()
    return int(collection.delete_one(
        {"_id": crud.to_oid(notification_id, "id"), "user_id": crud.to_oid(user_id, "user_id")}
    ).deleted_count) == 1
