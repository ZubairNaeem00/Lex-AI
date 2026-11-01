"""Generation sessions and generated documents.

The drafting workflow is stateful: it asks for one missing field at a time. If
that state lived only in memory, a restart would make the assistant re-ask
questions the user already answered. `workflow_state` is therefore stored verbatim
(so answers, locked fields and the outstanding question survive) and rebuilt on
demand — never re-derived from guessed data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from db import crud
from db.models import GeneratedDocument, GenerationSession, GenerationStatus
from db.schemas import GeneratedDocumentRead, GenerationSessionRead
from doc_generation import GENERATED_FOLDER

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
