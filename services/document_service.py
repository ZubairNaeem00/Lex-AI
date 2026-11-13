"""Uploaded documents, LlamaParse analyses and corrected case facts.

Files land in `uploads/<user id>/` and are only ever served back through a route
that re-checks ownership, so one user cannot read another user's FIR. Text,
report, original report and the edit history are stored per analysis version,
which is what makes "never lose the extraction" and "show me what changed"
both true.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from case_context import collection_fields
from db import crud
from db.models import (
    AnalysisStatus,
    CaseFact,
    DocumentAnalysis,
    UploadedDocument,
    UploadStatus,
)
from db.schemas import AnalysisRead, CaseFactRead, DocumentRead

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_ROOT = (BASE_DIR / "uploads").resolve()
MAX_FILENAME_LENGTH = 140
SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u0600-\u06FF ]+")

NOT_FOUND_DOCUMENT = "Document not found."


def _oid(user: Any):
    return crud.to_oid(getattr(user, "id", user))


def safe_filename(filename: str) -> str:
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = SAFE_NAME.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name or name in {".", ".."}:
        name = "upload"
    return name[-MAX_FILENAME_LENGTH:]


def storage_dir(user: Any) -> Path:
    return UPLOAD_ROOT / str(_oid(user))


def store_upload(user: Any, data: bytes, filename: str) -> Dict[str, Any]:
    """Write the original file under the owner's folder and fingerprint it."""
    digest = hashlib.sha256(data).hexdigest()
    target_dir = storage_dir(user)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / f"{digest[:16]}_{safe_filename(filename)}"
    if not str(stored.resolve()).startswith(str(UPLOAD_ROOT)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsafe upload path.")
    with stored.open("wb") as handle:
        handle.write(data)
    return {"sha256": digest, "stored_path": str(stored.resolve()), "size_bytes": len(data)}


def resolve_stored_file(document: Dict[str, Any]) -> Optional[Path]:
    """Path of the original upload, only when it really sits in the uploads tree."""
    candidate = document.get("stored_path") or ""
    if not candidate:
        return None
    try:
        resolved = Path(candidate).resolve()
    except OSError:
        return None
    if UPLOAD_ROOT not in resolved.parents or not resolved.is_file():
        return None
    return resolved


def record_upload(user: Any, case: Optional[Dict[str, Any]], *, filename: str,
                  content_type: str, storage: Dict[str, Any],
                  runtime_case_id: str = "",
                  runtime_document_id: str = "",
                  conversation_id: Any = None,
                  created_at: Optional[datetime] = None) -> Dict[str, Any]:
    owner = _oid(user)
    document = UploadedDocument(
        user_id=owner,
        case_id=case["_id"] if case else None,
        conversation_id=conversation_id,
        runtime_case_id=runtime_case_id,
        runtime_document_id=runtime_document_id[:80],
        filename=safe_filename(filename),
        stored_path=storage.get("stored_path", ""),
        content_type=content_type[:120],
        size_bytes=int(storage.get("size_bytes") or 0),
        sha256=str(storage.get("sha256") or ""),
        status=UploadStatus.PENDING,
        created_at=created_at or crud.utc_now(),
    )
    document_id = crud.documents.insert(document)
    return crud.documents.get(document_id)


def get(user: Any, document_id: Any) -> Dict[str, Any]:
    document = crud.documents.find_one(crud.user_query(user, _id=document_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_DOCUMENT)
    return document


def set_status(user: Any, document_id: Any, status_value: UploadStatus,
               error: str = "") -> Dict[str, Any]:
    document = get(user, document_id)
    crud.documents.set_by_id(document["_id"], {
        "status": status_value,
        "error": (error or "")[:500],
    })
    return crud.documents.get(document["_id"])


def list_for_case(user: Any, case_id: Any, *, page: int = 1, page_size: int = 20,
                  include_archived: bool = False) -> Dict[str, Any]:
    case = crud.cases.find_one(crud.user_query(user, _id=case_id))
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    query: Dict[str, Any] = {"user_id": _oid(user), "case_id": case["_id"]}
    if not include_archived:
        query["archived"] = {"$ne": True}
    result = crud.documents.paginate(query, page=page, page_size=page_size,
                                     sort=[("created_at", -1)])
    result["items"] = [
        DocumentRead.model_validate(item).model_dump(mode="json") for item in result["items"]
    ]
    return result


def list_uploads(user: Any, *, page: int = 1, page_size: int = 20, search: str = "",
                 include_archived: bool = False) -> Dict[str, Any]:
    query: Dict[str, Any] = crud.user_query(user)
    if search:
        query["filename"] = {"$regex": crud.escape_regex(search), "$options": "i"}
    if not include_archived:
        query["archived"] = {"$ne": True}
    result = crud.documents.paginate(query, page=page, page_size=page_size,
                                     sort=[("created_at", -1)])
    result["items"] = [
        DocumentRead.model_validate(item).model_dump(mode="json") for item in result["items"]
    ]
    return result


def editable_fields(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"label": item["label"], "value": item["value"], "section": item["section_title"],
         "path": item["path"]}
        for item in collection_fields(report or {})
    ]


def save_analysis(user: Any, document: Dict[str, Any], *, extracted_text: str,
                  report: Dict[str, Any], original_report: Optional[Dict[str, Any]] = None,
                  edits: Optional[List[Dict[str, Any]]] = None,
                  analysis_model: str = "",
                  status: AnalysisStatus = AnalysisStatus.COMPLETE,
                  created_at: Optional[datetime] = None) -> Dict[str, Any]:
    owner = _oid(user)
    latest = crud.analyses.find_one({"user_id": owner, "document_id": document["_id"]},
                                    sort=[("version", -1)])
    version = int((latest or {}).get("version", 0)) + 1
    analysis = DocumentAnalysis(
        user_id=owner,
        case_id=document.get("case_id"),
        document_id=document["_id"],
        extracted_text=extracted_text or "",
        report=report or {},
        original_report=original_report or report or {},
        editable_data={"fields": editable_fields(report or {})},
        edits=list(edits or []),
        status=status,
        version=version,
        analysis_model=analysis_model[:120],
        created_at=created_at or crud.utc_now(),
    )
    analysis_id = crud.analyses.insert(analysis)
    crud.documents.set_by_id(document["_id"], {"status": UploadStatus.ANALYZED})
    return crud.analyses.get(analysis_id)


def latest_analysis(user: Any, document_id: Any) -> Optional[Dict[str, Any]]:
    document = get(user, document_id)
    return crud.analyses.find_one({"user_id": _oid(user), "document_id": document["_id"]},
                                  sort=[("version", -1)])


def analysis_for_case(user: Any, case_id: Any) -> List[Dict[str, Any]]:
    case = crud.cases.find_one(crud.user_query(user, _id=case_id))
    if case is None:
        return []
    return crud.analyses.find({"user_id": _oid(user), "case_id": case["_id"]},
                              sort=[("created_at", -1)],
                              projection={"extracted_text": 0})


def read_analysis(user: Any, analysis_id: Any) -> Dict[str, Any]:
    document = crud.analyses.find_one(crud.user_query(user, _id=analysis_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")
    payload = AnalysisRead.model_validate(document).model_dump(mode="json")
    payload["extracted_characters"] = len(document.get("extracted_text") or "")
    return payload


def transcript(user: Any, document_id: Any) -> Dict[str, Any]:
    """Everything the analysis panel needs: text, original, current, edit history."""
    document = get(user, document_id)
    analysis = latest_analysis(user, document["_id"])
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No analysis stored for this document.")
    payload = AnalysisRead.model_validate(analysis).model_dump(mode="json")
    payload["extracted_text"] = analysis.get("extracted_text", "")
    payload["original_report"] = analysis.get("original_report") or {}
    payload["extracted_characters"] = len(analysis.get("extracted_text") or "")
    payload["filename"] = document.get("filename", "")
    return payload


def record_edit(user: Any, document: Dict[str, Any], analysis: Dict[str, Any],
                report: Dict[str, Any], applied_edits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist an accepted edit as a new analysis version plus case facts."""
    owner = _oid(user)
    edits = list(analysis.get("edits") or []) + list(applied_edits)
    version = int(analysis.get("version", 1)) + 1
    crud.analyses.set_by_id(analysis["_id"], {
        "report": report,
        "edits": edits,
        "version": version,
        "status": AnalysisStatus.EDITED,
        "editable_data": {"fields": editable_fields(report)},
    })
    updated = crud.analyses.get(analysis["_id"])
    if document.get("case_id"):
        fields = editable_fields(report)
        edited_paths = {edit.get("path") for edit in edits if edit.get("path")}
        facts = {item["label"]: item["value"] for item in fields}
        corrected_labels = {item["label"] for item in fields if item["path"] in edited_paths}
        put_facts(user, document["case_id"], facts, source="analysis",
                  document_id=document["_id"], corrected_labels=corrected_labels)
    crud.activity_logs.insert({
        "user_id": owner,
        "action": "document.report_edited",
        "resource_type": "document",
        "resource_id": str(document["_id"]),
        "detail": f"{len(applied_edits)} field(s) corrected",
    })
    return updated


def put_facts(user: Any, case_id: Any, facts: Dict[str, str], *, source: str = "user",
              document_id: Any = None,
              corrected_labels: Optional[set] = None) -> int:
    """One row per (case, field); a corrected value overwrites the extracted one."""
    owner = _oid(user)
    corrected_labels = corrected_labels or set()
    written = 0
    for field_name, raw_value in (facts or {}).items():
        value = "" if raw_value is None else str(raw_value)[:5000]
        key = str(field_name)[:200]
        if not value.strip() or not key:
            continue
        crud.case_facts.upsert(
            {"user_id": owner, "case_id": case_id, "field_name": key},
            CaseFact(
                user_id=owner,
                case_id=case_id,
                field_name=key,
                field_value=value,
                source=source[:60],
                source_document_id=document_id,
                corrected=(source == "user") or key in corrected_labels,
            ),
        )
        written += 1
    return written


def upsert_fact(user: Any, case_id: Any, *, field_name: str, field_value: str,
                source: str = "user", document_id: Any = None,
                value_type: str = "string", corrected: bool = True) -> Dict[str, Any]:
    owner = _oid(user)
    key = str(field_name)[:200]
    crud.case_facts.upsert(
        {"user_id": owner, "case_id": case_id, "field_name": key},
        CaseFact(
            user_id=owner,
            case_id=case_id,
            field_name=key,
            field_value=str(field_value or "")[:5000],
            source=source[:60],
            source_document_id=document_id,
            value_type=value_type[:40],
            corrected=corrected,
        ),
    )
    return crud.case_facts.find_one({"user_id": owner, "case_id": case_id, "field_name": key})


def list_facts(user: Any, case_id: Any) -> List[Dict[str, Any]]:
    rows = crud.case_facts.find({"user_id": _oid(user), "case_id": case_id},
                                sort=[("updated_at", -1)])
    return [CaseFactRead.model_validate(row).model_dump(mode="json") for row in rows]


def facts_map(user: Any, case_id: Any) -> Dict[str, str]:
    rows = crud.case_facts.find({"user_id": _oid(user), "case_id": case_id},
                                sort=[("updated_at", -1)])
    known: Dict[str, str] = {}
    for row in rows:
        known.setdefault(row["field_name"], row["field_value"])
    return known


def delete_fact(user: Any, case_id: Any, fact_id: Any) -> bool:
    document = crud.case_facts.find_one(crud.user_query(user, _id=fact_id))
    if document is None or document.get("case_id") != crud.to_oid(case_id, "case_id"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fact not found.")
    return crud.case_facts.delete_by_id(document["_id"])


def delete_upload(user: Any, document_id: Any, *, permanent: bool = False) -> Dict[str, Any]:
    """Without `permanent` the upload is archived — the transcript is never lost."""
    document = get(user, document_id)
    owner = _oid(user)
    if not permanent:
        crud.documents.set_by_id(document["_id"], {"archived": True})
        return {"ok": True, "permanent": False,
                "detail": "Upload archived; extracted text and report are kept."}
    path = resolve_stored_file(document)
    detail = {
        "analyses": crud.analyses.delete({"user_id": owner, "document_id": document["_id"]}),
        "documents": 1 if crud.documents.delete_by_id(document["_id"]) else 0,
        "file_removed": path is not None,
    }
    if path is not None:
        path.unlink(missing_ok=True)
    return {"ok": True, "permanent": permanent, "detail": detail}


def purge_user_uploads(user: Any) -> None:
    """Used by account deletion only; the case APIs never call this."""
    shutil.rmtree(storage_dir(user), ignore_errors=True)
