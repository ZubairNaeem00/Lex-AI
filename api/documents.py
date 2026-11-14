"""Uploaded documents, stored analyses and corrected case facts.

These routes read what the AI pipeline already produced; the upload itself stays
on `POST /api/analyze` so there is only one extraction path. Original files are
served back only after an ownership check *and* a path check, and deleting is
archival by default so an extracted record is never silently destroyed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from auth.deps import AuthenticatedUser, get_current_user
from db.schemas import AnalysisRead, CaseFactBatchUpsert, DocumentRead
from services import case_service, document_service

router = APIRouter(prefix="/api/documents", tags=["documents"])
facts_router = APIRouter(prefix="/api/cases/{case_id}/facts", tags=["case facts"])

PAGE = Query(default=1, ge=1, le=100000)
SIZE = Query(default=20, ge=1, le=200)


@router.get("", summary="My uploads")
def list_documents(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = PAGE,
    page_size: int = SIZE,
    case_id: Optional[str] = Query(default=None, max_length=80),
    search: str = Query(default="", max_length=200),
    include_archived: bool = Query(default=False),
) -> Dict[str, Any]:
    if case_id:
        return document_service.list_for_case(user, case_id, page=page, page_size=page_size,
                                              include_archived=include_archived)
    return document_service.list_uploads(user, page=page, page_size=page_size, search=search,
                                         include_archived=include_archived)


@router.get("/{document_id}", summary="Upload metadata")
def get_document(document_id: str,
                 user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return DocumentRead.model_validate(
        document_service.get(user, document_id)).model_dump(mode="json")


@router.get("/{document_id}/analysis", summary="Latest stored analysis")
def get_analysis(document_id: str,
                 user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    document = document_service.get(user, document_id)
    analysis = document_service.latest_analysis(user, document["_id"])
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No analysis stored for this document.")
    payload = AnalysisRead.model_validate(analysis).model_dump(mode="json")
    payload["extracted_characters"] = len(analysis.get("extracted_text") or "")
    return payload


@router.get("/{document_id}/transcript", summary="Extracted text, reports and edit history")
def get_transcript(document_id: str,
                   user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return document_service.transcript(user, document_id)


@router.get("/{document_id}/file", summary="Download the original upload")
def download_original(document_id: str,
                      user: AuthenticatedUser = Depends(get_current_user)) -> Response:
    document = document_service.get(user, document_id)
    path = document_service.resolve_stored_file(document)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "The original file is not stored for this document.")
    return Response(
        content=path.read_bytes(),
        media_type=document.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document["filename"]}"'},
    )


@router.delete("/{document_id}", summary="Archive an upload, or delete it permanently")
def delete_document(document_id: str, permanent: bool = Query(default=False),
                    user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return document_service.delete_upload(user, document_id, permanent=permanent)


# ---------------------------------------------------------------------------
# case facts
# ---------------------------------------------------------------------------

@facts_router.get("", summary="Corrected facts for a case")
def list_facts(case_id: str,
               user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    case = case_service.get(user, case_id)
    items = document_service.list_facts(user, case["_id"])
    return {"items": items, "total": len(items)}


@facts_router.post("", status_code=status.HTTP_201_CREATED, summary="Add or correct facts")
def upsert_facts(case_id: str, payload: CaseFactBatchUpsert,
                 user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    case = case_service.get(user, case_id)
    for fact in payload.facts:
        document_service.upsert_fact(
            user, case["_id"],
            field_name=fact.field_name,
            field_value=fact.field_value,
            source=fact.source,
            document_id=fact.source_document_id,
            value_type=fact.value_type,
            corrected=fact.corrected,
        )
    return {
        "ok": True,
        "written": len(payload.facts),
        "items": document_service.list_facts(user, case["_id"]),
    }


@facts_router.delete("/{fact_id}", summary="Remove one corrected fact")
def delete_fact(case_id: str, fact_id: str,
                user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    case = case_service.get(user, case_id)
    return {"ok": document_service.delete_fact(user, case["_id"], fact_id)}
