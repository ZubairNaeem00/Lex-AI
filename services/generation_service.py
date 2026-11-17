"""Generation sessions and generated documents.

The drafting workflow is stateful: it asks for one missing field at a time. If
that state lived only in memory, a restart would make the assistant re-ask
questions the user already answered. `workflow_state` is therefore stored verbatim
(so answers, locked fields and the outstanding question survive) and rebuilt on
demand — never re-derived from guessed data.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from db import crud
from db.models import GeneratedDocument, GenerationSession, GenerationStatus
from db.schemas import GeneratedDocumentRead, GenerationSessionRead
from doc_generation import GENERATED_FOLDER, MISSING_SENTINELS

GENERATED_ROOT = Path(GENERATED_FOLDER).resolve()
NOT_FOUND = "Document generation not found."


def _parse_ts(value: Any) -> Optional[datetime]:
    """Runtime sessions carry ISO-8601 "Z" strings."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _oid(user: Any):
    return crud.to_oid(getattr(user, "id", user))


def _jsonable(value: Any) -> Any:
    """Drop callables/objects the workflow may carry so the row stays BSON-safe."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _missing_names(gen: Dict[str, Any]) -> List[str]:
    missing = gen.get("missing_fields") or []
    names = []
    for item in missing:
        if isinstance(item, dict):
            names.append(str(item.get("name") or ""))
        else:
            names.append(str(item))
    return [name for name in names if name][:200]


def save_session(user: Any, gen: Dict[str, Any], *, case: Optional[Dict[str, Any]] = None,
                 conversation_id: Any = None) -> Dict[str, Any]:
    owner = _oid(user)
    session_key = str(gen.get("id") or crud.new_object_key("gen_"))
    status_value = GenerationStatus(str(gen.get("status") or "collecting"))
    document = GenerationSession(
        user_id=owner,
        case_id=(case or {}).get("_id"),
        conversation_id=conversation_id,
        session_key=session_key,
        document_type=str(gen.get("template_label") or gen.get("template_name") or "")[:120],
        template_name=str(gen.get("template_name") or "")[:200],
        current_step=str(gen.get("pending_field") or "")[:120],
        collected_information=_jsonable(gen.get("values") or {}),
        missing_fields=_missing_names(gen),
        workflow_state=_jsonable(gen),
        status=status_value,
        error=str(gen.get("error") or "")[:500],
    )
    document.workflow_state.pop("_id", None)
    crud.generation_sessions.upsert(
        {"user_id": owner, "session_key": session_key}, document)
    stored = crud.generation_sessions.find_one({"user_id": owner, "session_key": session_key})
    return stored


def get_session(user: Any, session_key: str) -> Optional[Dict[str, Any]]:
    return crud.generation_sessions.find_one(
        crud.user_query(user, session_key=session_key))


def session_id_for(user: Any, session_key: str) -> Optional[Any]:
    document = get_session(user, session_key)
    return document["_id"] if document else None


def list_sessions(user: Any, *, case_id: Any = None, page: int = 1,
                  page_size: int = 20, status_filter: str = "") -> Dict[str, Any]:
    query: Dict[str, Any] = crud.user_query(user)
    if case_id is not None:
        query["case_id"] = case_id
    if status_filter:
        query["status"] = status_filter
    result = crud.generation_sessions.paginate(query, page=page, page_size=page_size,
                                               sort=[("updated_at", -1)],
                                               projection={"workflow_state": 0})
    result["items"] = [
        GenerationSessionRead.model_validate(item).model_dump(mode="json")
        for item in result["items"]
    ]
    return result


def restore_workflow(user: Any, session_key: str) -> Optional[Dict[str, Any]]:
    """The exact runtime dict, so a resumed session asks only for what is missing."""
    document = get_session(user, session_key)
    if document is None:
        return None
    state = document.get("workflow_state") or {}
    if not state:
        return None
    state.setdefault("id", document.get("session_key"))
    return state


def read_session(user: Any, session_or_id: Any) -> Dict[str, Any]:
    document = crud.generation_sessions.find_one(
        crud.user_query(user, _id=session_or_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    payload = GenerationSessionRead.model_validate(document).model_dump(mode="json")
    payload.pop("workflow_state", None)
    return payload


def record_generated_document(user: Any, metadata: Dict[str, Any], *,
                              case: Optional[Dict[str, Any]] = None,
                              generation_session_id: Any = None,
                              conversation_id: Any = None) -> Dict[str, Any]:
    owner = _oid(user)
    document = GeneratedDocument(
        user_id=owner,
        case_id=(case or {}).get("_id"),
        generation_session_id=generation_session_id,
        conversation_id=conversation_id,
        runtime_document_id=str(metadata.get("id") or "")[:80],
        document_type=str(metadata.get("template_name") or "")[:120],
        template_name=str(metadata.get("template_name") or "")[:200],
        filename=str(metadata.get("filename") or "")[:300],
        file_path=str(metadata.get("file_path") or "")[:1000],
        download_url=str(metadata.get("download_url") or "")[:600],
        values={str(k): str(v) for k, v in (metadata.get("values") or {}).items()},
        created_at=_parse_ts(metadata.get("created_at")) or crud.utc_now(),
    )
    document_id = crud.generated_documents.insert(document)
    crud.activity_logs.insert({
        "user_id": owner,
        "action": "generation.document_created",
        "resource_type": "generated_document",
        "resource_id": str(document_id),
        "detail": document.template_name,
    })
    return crud.generated_documents.get(document_id)


def list_generated_documents(user: Any, *, case_id: Any = None, page: int = 1,
                             page_size: int = 20) -> Dict[str, Any]:
    query: Dict[str, Any] = crud.user_query(user)
    if case_id is not None:
        query["case_id"] = case_id
    result = crud.generated_documents.paginate(query, page=page, page_size=page_size,
                                               sort=[("created_at", -1)])
    result["items"] = [
        GeneratedDocumentRead.model_validate(item).model_dump(mode="json")
        for item in result["items"]
    ]
    return result


DOC_READY = {"generated", "downloaded", "superseded"}
DOC_LABELS = {"generated": "Ready", "downloaded": "Downloaded",
              "superseded": "Superseded", "missing_file": "File missing"}
GEN_LABELS = {"collecting": "Draft", "review": "Draft", "generating": "Preparing",
              "error": "Needs attention"}
# A completed/cancelled session is already represented by its generated document (or
# was abandoned), so it never appears as a separate report row.
GEN_REPORT_STATUSES = {"collecting", "review", "generating", "error"}

SUMMARY_KEYS = ("fir_number", "police_station", "list_relevant_sections", "court_name_location")


def _template_labels() -> Dict[str, str]:
    """Map a template file name to its friendly catalogue label."""
    from doc_generation import load_template_catalog

    labels: Dict[str, str] = {}
    for entry in load_template_catalog():
        path = str(entry.get("path") or "")
        if path:
            labels[path.lower()] = str(entry.get("name") or Path(path).stem)
    return labels


def _friendly_type(template_name: str, labels: Dict[str, str]) -> str:
    key = str(template_name or "").strip()
    if not key:
        return "Document"
    return labels.get(key.lower()) or Path(key).stem


_TITLE_SUFFIX = re.compile(r"(?:_?(?:precedent|analysis|report|docx))+$", re.IGNORECASE)
_HEX_TAIL = re.compile(r"_?[0-9a-f]{4,}$", re.IGNORECASE)
_STAMP_TAIL = re.compile(r"_(?:\d{8}_\d{6}|\d+)$")


def _title_from_filename(filename: str) -> str:
    stem = Path(str(filename or "")).stem
    stem = _TITLE_SUFFIX.sub("", stem)
    for _ in range(3):
        shortened = _HEX_TAIL.sub("", stem)
        shortened = _STAMP_TAIL.sub("", shortened)
        if shortened == stem:
            break
        stem = shortened
    return re.sub(r"[_\s]+", " ", stem).strip(" -")[:80]


def _report_title(type_label: str, values: Dict[str, Any], filename: str = "") -> str:
    name = str(values.get("applicants_full_name") or "").strip()
    if name:
        return f"{name} — {type_label}"
    stem = _title_from_filename(filename)
    if stem and stem.lower() != type_label.lower():
        return stem
    return type_label


def _report_snippet(values: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in SUMMARY_KEYS:
        text = str(values.get(key) or "").strip()
        if text and text.lower() not in MISSING_SENTINELS:
            parts.append(text)
    return " · ".join(parts[:4])


def _days_ago(value: Any) -> bool:
    moment = _parse_ts(value)
    if moment is None:
        return False
    return (datetime.now(timezone.utc) - moment).days <= 7


def _document_report(document: Dict[str, Any], labels: Dict[str, str],
                     case_cache: Dict[str, Any],
                     gen_cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    values = document.get("values") or {}
    type_label = _friendly_type(document.get("template_name") or document.get("document_type"), labels)
    status_code = str(document.get("status") or "generated")
    case_oid = str(document.get("case_id") or "")
    runtime_case_id = ""
    if case_oid:
        if case_oid not in case_cache:
            row = crud.cases.get(case_oid)
            case_cache[case_oid] = str((row or {}).get("runtime_case_id") or f"case_{case_oid}") if row else ""
        runtime_case_id = case_cache[case_oid]
    # The side editor opens a draft by its generation key, which is the linked
    # session's key (the document row only stores a separate file id).
    gen_session_oid = str(document.get("generation_session_id") or "")
    generation_id = ""
    if gen_session_oid:
        if gen_cache is not None and gen_session_oid in gen_cache:
            generation_id = gen_cache[gen_session_oid]
        else:
            row = crud.generation_sessions.get(gen_session_oid)
            generation_id = str((row or {}).get("session_key") or "")
            if gen_cache is not None:
                gen_cache[gen_session_oid] = generation_id
    filename = str(document.get("filename") or "")
    has_file = bool(filename) and (GENERATED_ROOT / filename).is_file()
    downloadable = status_code in DOC_READY and has_file
    return {
        "id": str(document.get("_id") or ""),
        "kind": "document",
        "type": type_label,
        "title": _report_title(type_label, values, filename),
        "status": "Ready" if status_code in DOC_READY else DOC_LABELS.get(status_code, "Ready"),
        "status_code": status_code,
        "case_number": str(values.get("fir_number") or "").strip(),
        "court": str(values.get("court_name_location") or "").strip(),
        "snippet": _report_snippet(values),
        "date": _parse_ts(document.get("created_at")),
        "runtime_case_id": runtime_case_id,
        "generation_id": generation_id,
        "filename": filename,
        "downloadable": downloadable,
        "openable": bool(downloadable and runtime_case_id and generation_id),
        "days_ago": _days_ago(document.get("created_at")),
    }


def _session_report(session: Dict[str, Any], labels: Dict[str, str],
                    case_cache: Dict[str, Any]) -> Dict[str, Any]:
    values = session.get("collected_information") or {}
    type_label = _friendly_type(session.get("template_name") or session.get("document_type"), labels)
    status_code = str(session.get("status") or "collecting")
    case_oid = str(session.get("case_id") or "")
    runtime_case_id = ""
    if case_oid:
        if case_oid not in case_cache:
            row = crud.cases.get(case_oid)
            case_cache[case_oid] = str((row or {}).get("runtime_case_id") or f"case_{case_oid}") if row else ""
        runtime_case_id = case_cache[case_oid]
    missing = session.get("missing_fields") or []
    snippet = f"Still needed: {', '.join(str(m).replace('_', ' ') for m in missing[:3])}" if missing else ""
    return {
        "id": str(session.get("session_key") or ""),
        "kind": "session",
        "type": type_label,
        "title": _report_title(type_label, values),
        "status": GEN_LABELS.get(status_code, "Draft"),
        "status_code": status_code,
        "case_number": str(values.get("fir_number") or "").strip(),
        "court": str(values.get("court_name_location") or "").strip(),
        "snippet": snippet,
        "date": _parse_ts(session.get("updated_at")),
        "runtime_case_id": runtime_case_id,
        "filename": "",
        "downloadable": False,
        "days_ago": _days_ago(session.get("updated_at")),
    }


def list_reports(user: Any, *, limit: int = 100) -> Dict[str, Any]:
    """Everything the Reports page shows, as one render-ready list.

    Finished drafts (generated documents) read as Ready; open drafting sessions
    that have not produced a file yet read as Draft. Both are keyed by the durable
    case id, so the runtime conversation id is resolved here for the chat links.
    """
    owner = _oid(user)
    labels = _template_labels()
    case_cache: Dict[str, Any] = {}
    gen_cache: Dict[str, Any] = {}
    reports: List[Dict[str, Any]] = []
    for document in crud.generated_documents.find(crud.user_query(user), sort=[("created_at", -1)],
                                                  limit=limit):
        reports.append(_document_report(document, labels, case_cache, gen_cache))
    for session in crud.generation_sessions.find(crud.user_query(user, status={"$in": sorted(GEN_REPORT_STATUSES)}),
                                                 sort=[("updated_at", -1)], limit=limit):
        reports.append(_session_report(session, labels, case_cache))

    reports.sort(key=lambda item: item["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    ready = sum(1 for item in reports if item["status"] == "Ready")
    drafts = sum(1 for item in reports if item["status_code"] in GEN_REPORT_STATUSES)
    this_week = sum(1 for item in reports if item["days_ago"])
    for item in reports:
        item["date"] = item["date"].isoformat() if item["date"] else ""
        item.pop("days_ago", None)
    return {
        "reports": reports,
        "summary": {"total": len(reports), "ready": ready, "drafts": drafts, "this_week": this_week},
        "storage": "mongodb" if owner and crud.generated_documents.available() else "in-memory",
    }


def mark_downloaded(user: Any, document_id: Any) -> Dict[str, Any]:
    document = crud.generated_documents.find_one(crud.user_query(user, _id=document_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated document not found.")
    crud.generated_documents.set_by_id(document["_id"], {"status": "downloaded"})
    return GeneratedDocumentRead.model_validate(
        crud.generated_documents.get(document["_id"])).model_dump(mode="json")


def file_for(user: Any, case_id: Any, filename: str) -> Optional[Path]:
    """Resolve a download only inside Generated/ and only for this user's case."""
    safe_name = Path(str(filename or "")).name
    query: Dict[str, Any] = {"user_id": _oid(user), "filename": safe_name}
    if case_id is not None:
        query["case_id"] = case_id
    document = crud.generated_documents.find_one(query, sort=[("created_at", -1)])
    if document is None:
        return None
    candidate = Path(str(document.get("file_path") or (GENERATED_ROOT / safe_name)))
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if GENERATED_ROOT not in resolved.parents or not resolved.is_file():
        crud.generated_documents.set_by_id(document["_id"], {"status": "missing_file"})
        return None
    return resolved
