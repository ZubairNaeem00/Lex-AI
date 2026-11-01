"""Bridge between the in-memory case session and MongoDB.

The AI engine keeps running on `session_manager.CaseSession`, which is fast and
already battle-tested. This module mirrors that session into the durable
collections after each request and can rebuild a session from them after a
restart, so nothing the user typed, uploaded, corrected or drafted is lost when
the process stops.

Every function here is best-effort: if MongoDB is disabled or unreachable the AI
features keep working exactly as before and the failure is only logged.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from db import crud
from db.config import database
from db.models import AccountStatus, GenerationStatus, MessageRole
from db.schemas import AuthenticatedUser, MessageCreate
from session_manager import CaseSession, new_id, session_manager
from services import case_service, chat_service, document_service, generation_service

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def enabled() -> bool:
    return bool(database.settings.enabled) and crud.cases.available()


def to_dt(value: Any) -> Optional[datetime]:
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


def to_iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return str(value or "")
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _stamp(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _fail(where: str, exc: Exception) -> None:
    print(f"[Persistence] {where} skipped: {type(exc).__name__}: {exc}", flush=True)


def _blank_cursors(sync: Dict[str, Any], user_id: str, title: str) -> None:
    """Cursor state belongs to one account; re-binding wipes it."""
    sync.update({
        "user_id": str(user_id),
        "event_cursor": 0,
        "documents": {},
        "generations": {},
        "generation_oids": {},
        "generated_documents": {},
        "facts_stamp": "",
        "title": title,
    })
    sync.pop("case_id", None)
    sync.pop("conversation_id", None)


def _init_cursors(session: CaseSession, user_id: str) -> None:
    sync = session.sync
    if str(sync.get("user_id") or "") != str(user_id):
        _blank_cursors(sync, user_id, session.title)
        return
    sync.setdefault("event_cursor", 0)
    sync.setdefault("documents", {})
    sync.setdefault("generations", {})
    sync.setdefault("generation_oids", {})
    sync.setdefault("generated_documents", {})
    sync.setdefault("facts_stamp", "")
    sync.setdefault("title", session.title)


def bound_user_id(session: CaseSession) -> str:
    return str(session.sync.get("user_id") or session.user_id or "")


def open_runtime_session(user: Any, case: Dict[str, Any]) -> CaseSession:
    """Start (or re-adopt) the in-memory session that runs the AI features."""
    runtime_id = str(case.get("runtime_case_id") or "") or new_id("case_")
    session = session_manager.get_session(runtime_id, create=True)
    if not case.get("runtime_case_id"):
        crud.cases.set_by_id(case["_id"], {"runtime_case_id": runtime_id})
        case["runtime_case_id"] = runtime_id
    session.title = case.get("name") or session.title
    bind(session, user)
    return session


# ---------------------------------------------------------------------------
# binding + mirroring
# ---------------------------------------------------------------------------
def bind(session: CaseSession, user: Any) -> None:
    """Attach an account to a live session and create its case/conversation rows."""
    if user is None or not enabled():
        return
    user_id = str(getattr(user, "id", user))
    if session.user_id and session.user_id != user_id:
        raise PermissionError("This case belongs to another account.")
    session.user_id = user_id
    try:
        _init_cursors(session, user_id)
        case = case_service.get_or_create_for_runtime(user, session.session_id, session.title)
        session.sync["case_id"] = str(case["_id"])
        conversation = chat_service.for_case(user, case, runtime_case_id=session.session_id)
        session.sync["conversation_id"] = str(conversation["_id"])
    except Exception as exc:  # noqa: BLE001 - persistence must not break the AI call
        _fail("bind", exc)


def sync_session(session: CaseSession) -> None:
    """Mirror everything that changed since the last call. Never raises."""
    if session.user_id is None or not enabled():
        return
    try:
        user = _as_user(session.user_id)
        case = _ensure_case(user, session)
        conversation = _ensure_conversation(user, session, case)
        _sync_messages(user, session, conversation)
        _sync_documents(user, session, case, conversation)
        _sync_facts(user, session, case)
        _sync_generations(user, session, case, conversation)
        _sync_generated_documents(user, session, case, conversation)
        _sync_title(user, session, case)
    except Exception as exc:  # noqa: BLE001
        _fail("sync", exc)


def _as_user(user_id: str) -> Any:
    """Rebuild the principal from the stored id; the route validated the token."""
    document = crud.users.get(user_id)
    if document is None:
        raise LookupError("bound user no longer exists")
    return AuthenticatedUser(
        id=document["_id"],
        email=document.get("email", ""),
        full_name=document.get("full_name", ""),
        status=AccountStatus(str(document.get("status") or AccountStatus.ACTIVE.value)),
    )


def _ensure_case(user: Any, session: CaseSession) -> Dict[str, Any]:
    stored = crud.cases.get(session.sync.get("case_id")) if session.sync.get("case_id") else None
    if stored is None:
        stored = case_service.get_or_create_for_runtime(user, session.session_id, session.title)
        session.sync["case_id"] = str(stored["_id"])
    return stored


def _ensure_conversation(user: Any, session: CaseSession,
                         case: Dict[str, Any]) -> Dict[str, Any]:
    stored = (crud.conversations.get(session.sync.get("conversation_id"))
              if session.sync.get("conversation_id") else None)
    if stored is None:
        stored = chat_service.for_case(user, case, runtime_case_id=session.session_id)
        session.sync["conversation_id"] = str(stored["_id"])
    return stored


def _sync_messages(user: Any, session: CaseSession, conversation: Dict[str, Any]) -> None:
    cursor = int(session.sync.get("event_cursor") or 0)
    events = session.ui_events
    for event in events[cursor:]:
        if event.get("type") != "message":
            continue
        role = str(event.get("role") or "assistant")
        content = str(event.get("content") or "")
        if not content.strip():
            continue
        payload = MessageCreate(
            role=MessageRole(role),
            content=content[:20000],
            kind=str(event.get("kind") or "legal")[:40],
            hidden=bool(event.get("hidden")),
        )
        chat_service.append_message(
            user,
            conversation,
            payload,
            case_id=conversation.get("case_id"),
            include_in_history=bool(event.get("in_history", True)),
            tool_called=event.get("tool_called"),
            source_labels=[str(item) for item in (event.get("sources") or [])][:40],
            meta={"ts": event.get("ts", ""), "generation_id": event.get("generation_id")},
            created_at=to_dt(event.get("ts")) or crud.utc_now(),
        )
        session.sync["event_cursor"] = cursor + 1
        cursor += 1


def _report_hash(report: Dict[str, Any]) -> str:
    return _stamp(report)


def _sync_documents(user: Any, session: CaseSession, case: Dict[str, Any],
                    conversation: Dict[str, Any]) -> None:
    tracked: Dict[str, Any] = session.sync.setdefault("documents", {})
    for document_id, document in session.documents.items():
        state = tracked.get(document_id)
        edits_count = len(document.edits or [])
        if state is None:
            storage = {
                "stored_path": "",
                "sha256": _stamp(document.filename, len(document.extracted_text or "")),
                "size_bytes": len(document.extracted_text or ""),
            }
            upload = document_service.record_upload(
                user, case,
                filename=document.filename,
                content_type="",
                storage=storage,
                runtime_case_id=session.session_id,
                runtime_document_id=document_id,
                conversation_id=conversation["_id"],
                created_at=to_dt(document.uploaded_at) or crud.utc_now(),
            )
            analysis = document_service.save_analysis(
                user, upload,
                extracted_text=document.extracted_text or "",
                report=copy.deepcopy(document.report),
                original_report=copy.deepcopy(document.original_report),
                edits=copy.deepcopy(document.edits),
                created_at=to_dt(document.uploaded_at) or crud.utc_now(),
            )
            tracked[document_id] = {
                "upload_id": str(upload["_id"]),
                "analysis_id": str(analysis["_id"]),
                "edits": edits_count,
                "report_hash": _report_hash(document.report),
            }
            _mirror_document_facts(user, session, case, document, upload["_id"])
            continue

        report_hash = _report_hash(document.report)
        if state.get("edits") == edits_count and state.get("report_hash") == report_hash:
            continue
        analysis = crud.analyses.get(state.get("analysis_id"))
        if analysis is None:
            continue
        document_service.record_edit(user, {"_id": ObjectId(state["upload_id"]),
                                            "case_id": case["_id"]},
                                     analysis,
                                     copy.deepcopy(document.report),
                                     copy.deepcopy(document.edits)[state.get("edits", 0):])
        state["edits"] = edits_count
        state["report_hash"] = report_hash
        _mirror_document_facts(user, session, case, document, ObjectId(state["upload_id"]))


def _mirror_document_facts(user: Any, session: CaseSession, case: Dict[str, Any],
                           document: Any, upload_oid: Any) -> None:
    """Canonical facts from the (possibly corrected) report feed later RAG prompts."""
    from case_context import document_canonical_facts

    facts = document_canonical_facts(document)
    document_service.put_facts(user, case["_id"], facts, source="analysis",
                               document_id=upload_oid)


def _sync_facts(user: Any, session: CaseSession, case: Dict[str, Any]) -> None:
    details = {key: value for key, value in (session.extra_case_details or {}).items() if value}
    stamp = _stamp(sorted(details.items()))
    if not details or stamp == session.sync.get("facts_stamp"):
        return
    document_service.put_facts(user, case["_id"], details, source="drafting")
    session.sync["facts_stamp"] = stamp


def _sync_generations(user: Any, session: CaseSession, case: Dict[str, Any],
                      conversation: Dict[str, Any]) -> None:
    tracked: Dict[str, Any] = session.sync.setdefault("generations", {})
    for generation_id, gen in session.generations.items():
        marker = _stamp(gen.get("status"), gen.get("updated_at"), gen.get("values"),
                        gen.get("pending_field"), gen.get("result"))
        if tracked.get(generation_id) == marker:
            continue
        stored = generation_service.save_session(
            user, gen, case=case, conversation_id=conversation["_id"])
        tracked[generation_id] = marker
        if stored is not None:
            session.sync.setdefault("generation_oids", {})[generation_id] = str(stored["_id"])


def _sync_generated_documents(user: Any, session: CaseSession, case: Dict[str, Any],
                              conversation: Dict[str, Any]) -> None:
    tracked: Dict[str, Any] = session.sync.setdefault("generated_documents", {})
    oids = session.sync.get("generation_oids") or {}
    for metadata in session.generated_documents:
        document_id = str(metadata.get("id") or "")
        if not document_id or document_id in tracked:
            continue
        generation_service.record_generated_document(
            user, metadata,
            case=case,
            generation_session_id=oids.get(str(metadata.get("generation_id") or "")),
            conversation_id=conversation["_id"],
        )
        tracked[document_id] = True


def _sync_title(user: Any, session: CaseSession, case: Dict[str, Any]) -> None:
    if session.title == session.sync.get("title"):
        return
    case_service.rename_from_title(user, case["_id"], session.title)
    session.sync["title"] = session.title


# ---------------------------------------------------------------------------
# restoring a session after a restart
# ---------------------------------------------------------------------------
def resolve(case_ref: str, user: Any) -> Optional[CaseSession]:
    """Return a live session for `case_ref`, restoring it from Mongo if needed."""
    if user is None:
        return session_manager.get_session(case_ref, create=False)
    session = session_manager.get_session(case_ref, create=False)
    if session is not None:
        if not session.user_id:
            _adopt(session, user)
        elif str(session.user_id) != str(getattr(user, "id", user)):
            raise PermissionError("This case belongs to another account.")
        return session
    if not enabled():
        return None
    return restore(user, case_ref)


def _adopt(session: CaseSession, user: Any) -> None:
    """Bind a session that was created before sign-in (the anonymous demo)."""
    bind(session, user)


def list_for_user(user: Any, *, limit: int = 50) -> Optional[List[Dict[str, Any]]]:
    """Sidebar rows for one account: durable cases, newest first.

    Returns None when MongoDB is not usable, so the caller can fall back to the
    live in-memory sessions instead of showing an empty list.
    """
    if user is None or not enabled():
        return None
    try:
        rows = crud.cases.find(crud.user_query(user),
                               sort=[("pinned", -1), ("updated_at", -1)], limit=limit)
    except Exception as exc:  # noqa: BLE001 - listing must not break the UI
        _fail("list_for_user", exc)
        return None
    items: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("archived"):
            continue
        items.append({
            "case_id": str(row.get("runtime_case_id") or f"case_{row['_id']}"),
            "title": row.get("name") or "New case",
            "updated_at": to_iso(row.get("updated_at")),
            "documents": crud.documents.count({"case_id": row["_id"]}),
            "messages": crud.messages.count({"case_id": row["_id"]}),
            "pinned": bool(row.get("pinned")),
        })
    return items


# ---------------------------------------------------------------------------
# sidebar actions: rename, pin, delete
# ---------------------------------------------------------------------------
def _case_row(user: Any, session: CaseSession) -> Optional[Dict[str, Any]]:
    """This account's durable case behind a live session, if persistence is on."""
    if user is None or not enabled():
        return None
    stored = (crud.cases.get(session.sync.get("case_id"))
              if session.sync.get("case_id") else None)
    if stored is None:
        stored = crud.cases.find_one(crud.user_query(user, runtime_case_id=session.session_id))
    return stored


def is_empty(session: CaseSession) -> bool:
    """True while nothing the user could miss has been recorded in the case."""
    with session.lock:
        spoke = any(
            event.get("type") == "message" and event.get("role") == "user"
            and str(event.get("content") or "").strip()
            for event in session.ui_events
        )
        return not spoke and not session.documents and not session.generations


def rename(user: Any, session: CaseSession, name: str) -> Optional[str]:
    """Set the case name by hand; a manual title outranks the derived ones."""
    row = _case_row(user, session)
    if row is None:
        return None
    cleaned = " ".join(str(name or "").split()).strip()[:200]
    if not cleaned:
        return None
    crud.cases.set_by_id(row["_id"], {"name": cleaned})
    with session.lock:
        session.title = cleaned
        session.sync["title"] = cleaned
    return cleaned


def set_pinned(user: Any, session: CaseSession, pinned: bool) -> Optional[bool]:
    row = _case_row(user, session)
    if row is None:
        return None
    crud.cases.set_by_id(row["_id"], {"pinned": bool(pinned)})
    return bool(pinned)


def is_pinned(user: Any, session: CaseSession) -> bool:
    row = _case_row(user, session)
    return bool(row and row.get("pinned"))


def drop(user: Any, session: CaseSession, *, only_if_empty: bool = False) -> Dict[str, Any]:
    """Delete the durable case behind a session together with everything under it."""
    row = _case_row(user, session)
    if row is None:
        return {"deleted": False, "persisted": False}
    stored = {
        "messages": crud.messages.count({"case_id": row["_id"]}),
        "documents": crud.documents.count({"case_id": row["_id"]}),
        "generations": crud.generation_sessions.count({"case_id": row["_id"]}),
    }
    if only_if_empty and (not is_empty(session) or any(stored.values())):
        return {"deleted": False, "persisted": True, "reason": "conversation has content"}
    case_service.delete(user, row["_id"], permanent=True)
    return {"deleted": True, "persisted": True, "removed": stored}


def restore(user: Any, case_ref: str) -> Optional[CaseSession]:
    """Rebuild the runtime session for one of this user's cases."""
    if not enabled():
        return None
    case = _find_case(user, case_ref)
    if case is None:
        return None
    runtime_id = case.get("runtime_case_id") or f"case_{case['_id']}"
    session = session_manager.get_session(runtime_id, create=True)
    if session.user_id and str(session.user_id) != str(getattr(user, "id", user)):
        raise PermissionError("This case belongs to another account.")
    session.user_id = str(getattr(user, "id", user))
    _init_cursors(session, session.user_id)
    session.sync["case_id"] = str(case["_id"])
    session.title = case.get("name") or session.title

    conversation = chat_service.for_case(user, case, runtime_case_id=runtime_id)
    session.sync["conversation_id"] = str(conversation["_id"])

    _restore_documents(user, session, case)
    events_written = _restore_messages(user, session, conversation)
    session.sync["event_cursor"] = events_written
    _restore_facts(user, session, case)
    _restore_generations(user, session, case)
    _restore_generated_documents(user, session, case)
    session.sync["title"] = session.title
    return session


def _find_case(user: Any, case_ref: str) -> Optional[Dict[str, Any]]:
    by_runtime = case_service.link_runtime(user, case_ref)
    if by_runtime is not None:
        return by_runtime
    if ObjectId.is_valid(str(case_ref)):
        return crud.cases.find_one(crud.user_query(user, _id=case_ref))
    return None


def _restore_documents(user: Any, session: CaseSession, case: Dict[str, Any]) -> None:
    owner = str(case["user_id"])
    rows = crud.documents.find({"user_id": owner, "case_id": case["_id"]},
                               sort=[("created_at", 1)])
    tracked = session.sync.setdefault("documents", {})
    for row in rows:
        analysis = crud.analyses.find_one({"user_id": owner, "document_id": row["_id"]},
                                          sort=[("version", -1)])
        if analysis is None:
            continue
        document = session.add_document(
            filename=row.get("filename") or "document",
            extracted_text=analysis.get("extracted_text") or "",
            report=copy.deepcopy(analysis.get("report") or {}),
            document_id=row.get("runtime_document_id") or f"doc_{row['_id']}",
            uploaded_at=to_iso(row.get("created_at")),
        )
        document.original_report = copy.deepcopy(analysis.get("original_report") or {})
        document.edits = copy.deepcopy(analysis.get("edits") or [])
        document.updated_at = to_iso(analysis.get("updated_at"))
        tracked[document.document_id] = {
            "upload_id": str(row["_id"]),
            "analysis_id": str(analysis["_id"]),
            "edits": len(document.edits),
            "report_hash": _report_hash(document.report),
        }


def _restore_messages(user: Any, session: CaseSession,
                      conversation: Dict[str, Any]) -> int:
    from langchain_core.messages import AIMessage, HumanMessage

    owner = str(conversation["user_id"])
    rows = crud.messages.find({"user_id": owner, "conversation_id": conversation["_id"]},
                              sort=[("created_at", 1)])
    session.ui_events = []
    session.history = []
    for row in rows:
        role = str(row.get("role") or MessageRole.ASSISTANT.value)
        content = str(row.get("content") or "")
        event: Dict[str, Any] = {
            "type": "message",
            "role": role,
            "content": content,
            "ts": to_iso(row.get("created_at")),
            "in_history": bool(row.get("include_in_history", True)),
        }
        if row.get("hidden"):
            event["hidden"] = True
        if row.get("source_labels"):
            event["sources"] = list(row["source_labels"])[:40]
        if row.get("tool_called"):
            event["tool_called"] = row["tool_called"]
        if row.get("kind"):
            event["kind"] = row["kind"]
        session.ui_events.append(event)
        if event["in_history"] and content:
            session.history.append(
                HumanMessage(content=content) if role == MessageRole.USER.value
                else AIMessage(content=content)
            )
    return len(rows)


def _restore_facts(user: Any, session: CaseSession, case: Dict[str, Any]) -> None:
    owner = str(case["user_id"])
    rows = crud.case_facts.find({"user_id": owner, "case_id": case["_id"]},
                                sort=[("updated_at", 1)])
    for row in rows:
        if row.get("source") == "drafting":
            session.extra_case_details[row["field_name"]] = row.get("field_value", "")


def _restore_generations(user: Any, session: CaseSession, case: Dict[str, Any]) -> None:
    owner = str(case["user_id"])
    rows = crud.generation_sessions.find({"user_id": owner, "case_id": case["_id"]},
                                         sort=[("created_at", 1)])
    tracked = session.sync.setdefault("generations", {})
    oids = session.sync.setdefault("generation_oids", {})
    for row in rows:
        state = row.get("workflow_state") or {}
        key = str(row.get("session_key") or row["_id"])
        if not state:
            continue
        state.setdefault("id", key)
        state.setdefault("session_id", session.session_id)
        session.generations[key] = state
        tracked[key] = _stamp(state.get("status"), state.get("updated_at"), state.get("values"),
                             state.get("pending_field"), state.get("result"))
        oids[key] = str(row["_id"])
        if str(row.get("status")) in {GenerationStatus.COLLECTING.value,
                                      GenerationStatus.REVIEW.value,
                                      GenerationStatus.ERROR.value}:
            session.active_generation_id = key
    latest = rows[-1] if rows else None
    if latest is not None and session.active_generation_id is None:
        session.active_generation_id = str(latest.get("session_key"))


def _restore_generated_documents(user: Any, session: CaseSession, case: Dict[str, Any]) -> None:
    owner = str(case["user_id"])
    rows = crud.generated_documents.find({"user_id": owner, "case_id": case["_id"]},
                                        sort=[("created_at", 1)])
    tracked = session.sync.setdefault("generated_documents", {})
    for row in rows:
        tracked[str(row["_id"])] = True
        session.generated_documents.append({
            "id": row.get("runtime_document_id") or f"gen_doc_{row['_id']}",
            "generation_id": None,
            "template_name": row.get("template_name") or "",
            "filename": row.get("filename") or "",
            "file_path": row.get("file_path") or "",
            "download_url": row.get("download_url") or "",
            "values": dict(row.get("values") or {}),
            "created_at": to_iso(row.get("created_at")),
        })


