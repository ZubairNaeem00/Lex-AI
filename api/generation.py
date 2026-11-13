"""Persisted drafting state and generated DOCX files.

The chat-driven workflow itself lives on `/api/chat` and
`/api/sessions/{case_id}/generation*`; these routes expose the durable copies, so
the document list and download links survive a restart and stay scoped to the
caller.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.deps import AuthenticatedUser, get_current_user
from db import crud
from db.schemas import GenerationSessionRead
from doc_generation import get_supported_templates, get_template_catalog
from fastapi.responses import FileResponse
from services import case_service, generation_service

router = APIRouter(prefix="/api/generation", tags=["generation"])


@router.get("/templates", summary="Templates the drafting workflow can fill")
def templates() -> Dict[str, Any]:
    return {"supported": get_supported_templates(), "catalog": get_template_catalog()}


@router.get("/sessions", summary="My drafting sessions")
def list_sessions(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=20, ge=1, le=200),
    case_id: Optional[str] = Query(default=None, max_length=80),
    generation_status: Optional[str] = Query(default=None, alias="status", max_length=40),
) -> Dict[str, Any]:
    resolved = case_service.get(user, case_id)["_id"] if case_id else None
    return generation_service.list_sessions(user, case_id=resolved, page=page,
                                           page_size=page_size,
                                           status_filter=generation_status or "")


@router.get("/sessions/{session_key}", summary="One drafting session")
def get_session(session_key: str,
                user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    document = generation_service.get_session(user, session_key)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document generation not found.")
    payload = GenerationSessionRead.model_validate(document).model_dump(mode="json")
    payload["runtime_case_id"] = (document.get("workflow_state") or {}).get("session_id", "")
    return payload


@router.get("/documents", summary="Documents drafted for me")
def list_generated(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=20, ge=1, le=200),
    case_id: Optional[str] = Query(default=None, max_length=80),
) -> Dict[str, Any]:
    resolved = case_service.get(user, case_id)["_id"] if case_id else None
    return generation_service.list_generated_documents(user, case_id=resolved, page=page,
                                                      page_size=page_size)


@router.get("/documents/{document_id}/download", summary="Download a drafted document")
def download(document_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    document = crud.generated_documents.find_one(crud.user_query(user, _id=document_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated document not found.")
    path = generation_service.file_for(user, document.get("case_id"), document["filename"])
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated document file is missing.")
    generation_service.mark_downloaded(user, document["_id"])
    return FileResponse(str(path), filename=document["filename"],
                        media_type="application/vnd.openxmlformats-officedocument."
                                   "wordprocessingml.document")
