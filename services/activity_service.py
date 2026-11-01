"""Activity logging. Audit writes must never break the request they describe."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from db import crud
from db.config import COLLECTIONS
from db.models import ActivityLog
from db.schemas import ActivityRead


def log(user_id: Any = None, action: str = "", *, resource_type: str = "", resource_id: str = "",
        detail: str = "", metadata: Optional[Dict[str, Any]] = None, ip_address: str = "") -> Optional[str]:
    if not action:
        return None
    try:
        return crud.activity_logs.insert(
            ActivityLog(
                user_id=user_id,
                action=action[:120],
                resource_type=resource_type[:80],
                resource_id=str(resource_id or "")[:120],
                detail=detail[:1000],
                metadata=metadata or {},
                ip_address=ip_address[:80],
            )
        )
    except Exception as exc:  # pragma: no cover - audit is best effort
        print(f"[Activity] could not record {action!r}: {type(exc).__name__}: {exc}", flush=True)
        return None


def _read(row: Dict[str, Any]) -> Dict[str, Any]:
    """Raw Mongo rows carry ObjectIds; responses must go through ActivityRead."""
    return ActivityRead.model_validate(row).model_dump(mode="json")


def list_for_user(user_id: Any, page: int = 1, page_size: int = 20,
                  action: str = "", resource_type: str = "") -> Dict[str, Any]:
    query: Dict[str, Any] = {"user_id": user_id}
    if action:
        query["action"] = action
    if resource_type:
        query["resource_type"] = resource_type
    result = crud.activity_logs.paginate(query, page=page, page_size=page_size,
                                         sort=[("created_at", -1)])
    result["items"] = [_read(item) for item in result["items"]]
    return result


def recent(user_id: Any, limit: int = 10) -> List[Dict[str, Any]]:
    rows = crud.activity_logs.find({"user_id": user_id}, sort=[("created_at", -1)], limit=limit)
    return [_read(row) for row in rows]
