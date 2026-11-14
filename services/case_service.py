"""Cases: one legal matter per row, owned by exactly one account.

A case is the unit of isolation. Documents, chats, facts, generations and
generated files all hang off `case_id`, and every query here pins the
authenticated user in the filter itself, so a guessed ObjectId belonging to
another account never resolves.

The AI engine still runs on the in-memory session id (`runtime_case_id`); this
service keeps the durable Mongo copy in step with it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from db import crud
from db.crud import Conflict
from db.models import Case
from db.schemas import CaseCreate, CaseRead, CaseUpdate

NOT_FOUND = "Case not found."


def _oid(user: Any):
    return crud.to_oid(getattr(user, "id", user))


def read(document: Dict[str, Any]) -> Dict[str, Any]:
    payload = CaseRead.model_validate(document).model_dump(mode="json")
    payload["document_count"] = crud.documents.count({"case_id": document["_id"]})
    payload["message_count"] = crud.messages.count({"case_id": document["_id"]})
    return payload


def create(user: Any, payload: Optional[CaseCreate] = None,
           runtime_case_id: str = "") -> Dict[str, Any]:
    body = payload or CaseCreate(name="New case")
    owner = _oid(user)
    document = Case(
        user_id=owner,
        case_key=crud.new_object_key("case_"),
        runtime_case_id=runtime_case_id or body.runtime_case_id,
        name=body.name,
        case_type=body.case_type,
        description=body.description,
        status=body.status,
        court=body.court,
        filed_on=body.filed_on,
    )
    try:
        case_id = crud.cases.insert(document)
    except Conflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    crud.activity_logs.insert({
        "user_id": owner,
        "action": "case.created",
        "resource_type": "case",
        "resource_id": str(case_id),
        "detail": document.name,
    })
    return crud.cases.get(case_id)


def link_runtime(user: Any, runtime_case_id: str) -> Optional[Dict[str, Any]]:
    """The case already bound to this runtime session id, if any."""
    if not runtime_case_id:
        return None
    return crud.cases.find_one(crud.user_query(user, runtime_case_id=runtime_case_id))


def get_or_create_for_runtime(user: Any, runtime_case_id: str,
                              name: str = "New case") -> Dict[str, Any]:
    existing = link_runtime(user, runtime_case_id)
    if existing is not None:
        return existing
    return create(user, CaseCreate(name=name[:200]), runtime_case_id=runtime_case_id)


def get(user: Any, case_id: Any) -> Dict[str, Any]:
    document = crud.cases.find_one(crud.user_query(user, _id=case_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return document


def list_cases(user: Any, *, page: int = 1, page_size: int = 20, search: str = "",
               status_filter: str = "", include_archived: bool = True) -> Dict[str, Any]:
    query: Dict[str, Any] = crud.user_query(user)
    if search:
        query["name"] = {"$regex": crud.escape_regex(search), "$options": "i"}
    if status_filter:
        query["status"] = status_filter
    if not include_archived:
        query["archived"] = {"$ne": True}
    result = crud.cases.paginate(query, page=page, page_size=page_size,
                                 sort=[("updated_at", -1)])
    result["items"] = [read(item) for item in result["items"]]
    return result


def update(user: Any, case_id: Any, payload: CaseUpdate) -> Dict[str, Any]:
    document = get(user, case_id)
    changes = {key: value for key, value in payload.model_dump(exclude_unset=True).items()
               if value is not None}
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide at least one field to update.")
    if changes.get("status") == "closed" and not document.get("closed_at"):
        changes["closed_at"] = crud.utc_now()
    updated = crud.cases.update({"_id": document["_id"], "user_id": _oid(user)}, changes)
    crud.activity_logs.insert({
        "user_id": _oid(user),
        "action": "case.updated",
        "resource_type": "case",
        "resource_id": str(case_id),
        "detail": ", ".join(sorted(changes)),
    })
    return updated


def rename_from_title(user: Any, case_id: Any, title: str) -> None:
    """Adopt the analysed document type as the case name while it is still default."""
    document = crud.cases.find_one(crud.user_query(user, _id=case_id))
    if document is None or document.get("name") != "New case" or not title:
        return
    crud.cases.set_by_id(document["_id"], {"name": str(title)[:200]})


def archive(user: Any, case_id: Any) -> Dict[str, Any]:
    document = get(user, case_id)
    crud.cases.set_by_id(document["_id"], {"archived": True})
    crud.activity_logs.insert({
        "user_id": _oid(user),
        "action": "case.archived",
        "resource_type": "case",
        "resource_id": str(case_id),
    })
    return crud.cases.get(document["_id"])


def delete(user: Any, case_id: Any, *, permanent: bool = False) -> Dict[str, Any]:
    """Archive by default — legal history is never destroyed silently."""
    document = get(user, case_id)
    if not permanent:
        archive(user, case_id)
        return {"ok": True, "permanent": False,
                "detail": "Case archived. Documents, chats and analyses are kept."}

    owner = _oid(user)
    case_oid = document["_id"]
    conversation_ids = [row["_id"] for row in crud.conversations.find(
        {"user_id": owner, "case_id": case_oid}, projection={"_id": 1})]
    deleted = {
        "uploaded_documents": crud.documents.delete({"user_id": owner, "case_id": case_oid}),
        "document_analyses": crud.analyses.delete({"user_id": owner, "case_id": case_oid}),
        "case_facts": crud.case_facts.delete({"user_id": owner, "case_id": case_oid}),
        "generation_sessions": crud.generation_sessions.delete(
            {"user_id": owner, "case_id": case_oid}),
        "generated_documents": crud.generated_documents.delete(
            {"user_id": owner, "case_id": case_oid}),
        "messages": crud.messages.delete({"user_id": owner, "case_id": case_oid}),
        "conversations": crud.conversations.delete({"user_id": owner, "case_id": case_oid}),
    }
    if conversation_ids:
        deleted["conversation_memory"] = crud.memory.delete(
            {"user_id": owner, "conversation_id": {"$in": conversation_ids}})
    deleted["cases"] = 1 if crud.cases.delete_by_id(case_oid) else 0
    crud.activity_logs.insert({
        "user_id": owner,
        "action": "case.deleted_permanently",
        "resource_type": "case",
        "resource_id": str(case_oid),
        "detail": str(deleted),
    })
    return {"ok": True, "permanent": True, "deleted": deleted}


def summary(user: Any, case_id: Any) -> Dict[str, Any]:
    document = get(user, case_id)
    owner = _oid(user)
    case_oid = document["_id"]
    return {
        "case": read(document),
        "counts": {
            "documents": crud.documents.count({"user_id": owner, "case_id": case_oid}),
            "analyses": crud.analyses.count({"user_id": owner, "case_id": case_oid}),
            "facts": crud.case_facts.count({"user_id": owner, "case_id": case_oid}),
            "conversations": crud.conversations.count({"user_id": owner, "case_id": case_oid}),
            "messages": crud.messages.count({"user_id": owner, "case_id": case_oid}),
            "generations": crud.generation_sessions.count({"user_id": owner, "case_id": case_oid}),
            "generated_documents": crud.generated_documents.count(
                {"user_id": owner, "case_id": case_oid}),
        },
        "recent_activity": crud.activity_logs.find(
            {"user_id": owner, "resource_type": "case", "resource_id": str(case_oid)},
            sort=[("created_at", -1)], limit=10),
    }


def stats(user: Any) -> Dict[str, Any]:
    owner = _oid(user)
    return {
        "cases": crud.cases.count({"user_id": owner}),
        "archived_cases": crud.cases.count({"user_id": owner, "archived": True}),
        "documents": crud.documents.count({"user_id": owner}),
        "analyses": crud.analyses.count({"user_id": owner}),
        "conversations": crud.conversations.count({"user_id": owner}),
        "messages": crud.messages.count({"user_id": owner}),
        "generations": crud.generation_sessions.count({"user_id": owner}),
        "generated_documents": crud.generated_documents.count({"user_id": owner}),
        "database": crud.database.db().name,
    }
