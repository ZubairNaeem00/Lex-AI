"""Case endpoints: the container that owns documents, chats, facts and drafts.

`{case_id}` accepts the MongoDB id or the runtime session id — both resolve only
within the caller's own account, and an id that belongs to somebody else is
reported as 404 so ids cannot be probed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request, status

from auth.deps import AuthenticatedUser, client_ip, get_current_user
from db import persistence
from db.schemas import CaseCreate, CaseUpdate
from services import activity_service, case_service

router = APIRouter(prefix="/api/cases", tags=["cases"])

PAGE = Query(default=1, ge=1, le=100000)
SIZE = Query(default=20, ge=1, le=200)


def _case(user: AuthenticatedUser, case_id: str) -> Dict[str, Any]:
    document = case_service.get(user, case_id)
    return document


@router.post("", status_code=status.HTTP_201_CREATED, summary="Open a new case")
def create_case(payload: CaseCreate, request: Request,
                user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    document = case_service.create(user, payload)
    session = persistence.open_runtime_session(user, document)
    activity_service.log(user.id, "case.opened", resource_type="case",
                         resource_id=document["_id"], ip_address=client_ip(request))
    return {
        "case": case_service.read(document),
        "runtime_case_id": session.session_id,
        "snapshot_case_id": session.session_id,
    }


@router.get("", summary="List my cases")
def list_cases(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = PAGE,
    page_size: int = SIZE,
    search: str = Query(default="", max_length=200),
    case_status: Optional[str] = Query(default=None, alias="status", max_length=40),
    include_archived: bool = Query(default=True),
) -> Dict[str, Any]:
    return case_service.list_cases(user, page=page, page_size=page_size, search=search,
                                   status_filter=case_status or "",
                                   include_archived=include_archived)


@router.get("/summary", summary="Totals across all my cases")
def totals(user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return case_service.stats(user)


@router.get("/{case_id}", summary="One case")
def get_case(case_id: str, user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return case_service.read(_case(user, case_id))


@router.get("/{case_id}/summary", summary="Case with counts and recent activity")
def get_summary(case_id: str,
                user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return case_service.summary(user, case_id)


@router.patch("/{case_id}", summary="Update case details")
def update_case(case_id: str, payload: CaseUpdate,
                user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    updated = case_service.update(user, case_id, payload)
    return case_service.read(updated)


@router.post("/{case_id}/archive", summary="Archive a case (data is kept)")
def archive_case(case_id: str,
                 user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return case_service.read(case_service.archive(user, case_id))


@router.delete("/{case_id}", summary="Archive a case, or delete it permanently")
def delete_case(case_id: str,
                permanent: bool = Query(default=False),
                user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return case_service.delete(user, case_id, permanent=permanent)
