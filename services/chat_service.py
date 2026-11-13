"""Conversations, messages and rolling conversation memory.

Two conversation shapes exist on purpose:

* `case` — attached to a `Case`, it carries the RAG chat about that matter;
* `general` — `case_id` is null, which is how case-less legal questions are
  stored without inventing a throw-away case.

Message rows are the durable replacement for the in-memory LangChain history, so
a restart rebuilds the same prompt context (subject to the token budgets in
`context_budget.py`) instead of losing it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from db import crud
from db.models import Conversation, ConversationMemory, ConversationType, Message, MessageRole
from db.schemas import (
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MemoryRead,
    MemoryUpdate,
    MessageCreate,
    MessageRead,
)

NOT_FOUND = "Conversation not found."


def _oid(user: Any):
    return crud.to_oid(getattr(user, "id", user))


def read(document: Dict[str, Any]) -> Dict[str, Any]:
    payload = ConversationRead.model_validate(document).model_dump(mode="json")
    payload["message_count"] = crud.messages.count({"conversation_id": document["_id"]})
    return payload


def create(user: Any, payload: Optional[ConversationCreate] = None,
           case: Optional[Dict[str, Any]] = None,
           runtime_case_id: str = "") -> Dict[str, Any]:
    owner = _oid(user)
    body = payload or ConversationCreate()
    case_id = case["_id"] if case else (body.case_id or None)
    conversation_type = (
        ConversationType.CASE if case or case_id else body.type or ConversationType.GENERAL
    )
    title = body.title
    if title == "New conversation" and case:
        title = f"{case.get('name') or 'Case'} discussion"[:200]
    document = Conversation(
        user_id=owner,
        case_id=case_id,
        runtime_case_id=(case or {}).get("runtime_case_id", "") or runtime_case_id,
        title=title[:200],
        type=conversation_type,
    )
    conversation_id = crud.conversations.insert(document)
    return crud.conversations.get(conversation_id)


def get(user: Any, conversation_id: Any) -> Dict[str, Any]:
    document = crud.conversations.find_one(crud.user_query(user, _id=conversation_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return document


def for_case(user: Any, case: Dict[str, Any], *, create_if_missing: bool = True,
             runtime_case_id: str = "") -> Optional[Dict[str, Any]]:
    """The case's primary conversation (the one the chat UI replays)."""
    existing = crud.conversations.find_one(
        crud.user_query(user, case_id=case["_id"], type=ConversationType.CASE.value))
    if existing is not None or not create_if_missing:
        return existing
    return create(user, case=case, runtime_case_id=runtime_case_id)


def general_conversation(user: Any, *, create_if_missing: bool = True,
                         title: str = "General legal chat") -> Optional[Dict[str, Any]]:
    existing = crud.conversations.find_one(
        crud.user_query(user, case_id=None, type=ConversationType.GENERAL.value))
    if existing is not None or not create_if_missing:
        return existing
    return create(user, ConversationCreate(title=title, type=ConversationType.GENERAL))


def list_conversations(user: Any, *, page: int = 1, page_size: int = 20, case_id: Any = None,
                       conversation_type: str = "", include_archived: bool = True,
                       unassigned: bool = False) -> Dict[str, Any]:
    query: Dict[str, Any] = crud.user_query(user)
    if unassigned:
        query["case_id"] = None
        query["type"] = ConversationType.GENERAL.value
    elif case_id is not None:
        query["case_id"] = case_id
    if conversation_type:
        query["type"] = conversation_type
    if not include_archived:
        query["archived"] = {"$ne": True}
    result = crud.conversations.paginate(query, page=page, page_size=page_size,
                                         sort=[("updated_at", -1)])
    result["items"] = [read(item) for item in result["items"]]
    return result


def update(user: Any, conversation_id: Any, payload: ConversationUpdate) -> Dict[str, Any]:
    document = get(user, conversation_id)
    changes = {key: value for key, value in payload.model_dump(exclude_unset=True).items()
               if value is not None}
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide at least one field to update.")
    if "case_id" in changes:
        changes["type"] = ConversationType.CASE if changes["case_id"] else ConversationType.GENERAL
    return crud.conversations.update({"_id": document["_id"], "user_id": _oid(user)}, changes)


def delete(user: Any, conversation_id: Any, *, permanent: bool = False) -> Dict[str, Any]:
    """Archive keeps the transcript; permanent removal is opt-in."""
    document = get(user, conversation_id)
    owner = _oid(user)
    if not permanent:
        crud.conversations.set_by_id(document["_id"], {"archived": True})
        return {"ok": True, "permanent": False,
                "detail": "Conversation archived; messages are still stored."}
    deleted = {
        "messages": crud.messages.delete({"user_id": owner, "conversation_id": document["_id"]}),
        "memory": crud.memory.delete({"user_id": owner, "conversation_id": document["_id"]}),
        "generations": crud.generation_sessions.delete(
            {"user_id": owner, "conversation_id": document["_id"]}),
        "conversations": 1 if crud.conversations.delete_by_id(document["_id"]) else 0,
    }
    return {"ok": True, "permanent": True, "deleted": deleted}


def append_message(user: Any, conversation: Dict[str, Any], payload: MessageCreate,
                   *, case_id: Any = None, include_in_history: bool = True,
                   tool_called: Optional[str] = None,
                   source_labels: Optional[List[str]] = None,
                   meta: Optional[Dict[str, Any]] = None,
                   created_at: Optional[datetime] = None) -> Dict[str, Any]:
    owner = _oid(user)
    document = Message(
        conversation_id=conversation["_id"],
        user_id=owner,
        case_id=conversation.get("case_id") if case_id is None else case_id,
        role=payload.role,
        content=payload.content,
        kind=payload.kind,
        sources=payload.sources,
        source_labels=list(source_labels or [item.label for item in payload.sources]),
        tool_called=tool_called,
        hidden=payload.hidden,
        include_in_history=include_in_history,
        meta=dict(meta or {}),
        created_at=created_at or crud.utc_now(),
    )
    message_id = crud.messages.insert(document)
    crud.conversations.set_by_id(conversation["_id"], {
        "last_message_at": crud.utc_now(),
        "updated_at": crud.utc_now(),
    })
    bump_memory(user, conversation, role=payload.role, content=payload.content)
    return crud.messages.get(message_id)


def list_messages(user: Any, conversation_id: Any, *, page: int = 1, page_size: int = 50,
                  include_hidden: bool = False) -> Dict[str, Any]:
    conversation = get(user, conversation_id)
    query: Dict[str, Any] = {"user_id": _oid(user), "conversation_id": conversation["_id"]}
    if not include_hidden:
        query["hidden"] = False
    result = crud.messages.paginate(query, page=page, page_size=page_size,
                                   sort=[("created_at", 1)])
    result["items"] = [
        MessageRead.model_validate(item).model_dump(mode="json") for item in result["items"]
    ]
    return result


def langchain_history(user: Any, conversation_id: Any, *, limit: int = 60) -> List[BaseMessage]:
    """Rebuild the model-facing history, newest first then reversed."""
    rows = crud.messages.find(
        {"user_id": _oid(user), "conversation_id": conversation_id,
         "hidden": False, "include_in_history": True},
        sort=[("created_at", -1)],
        limit=limit,
    )
    history: List[BaseMessage] = []
    for row in reversed(rows):
        text = str(row.get("content") or "")
        if not text:
            continue
        history.append(
            HumanMessage(content=text) if row.get("role") == MessageRole.USER.value
            else AIMessage(content=text)
        )
    return history


def memory(user: Any, conversation_id: Any) -> Dict[str, Any]:
    conversation = get(user, conversation_id)
    document = crud.memory.find_one(
        {"user_id": _oid(user), "conversation_id": conversation["_id"]})
    if document is None:
        return {
            "conversation_id": str(conversation["_id"]),
            "case_id": str(conversation["case_id"]) if conversation.get("case_id") else None,
            "summary": "",
            "key_facts": [],
            "open_questions": [],
            "updated_context": {},
            "message_count": crud.messages.count({"conversation_id": conversation["_id"]}),
            "token_estimate": 0,
            "version": 0,
        }
    return MemoryRead.model_validate(document).model_dump(mode="json")


def update_memory(user: Any, conversation_id: Any, payload: MemoryUpdate) -> Dict[str, Any]:
    conversation = get(user, conversation_id)
    owner = _oid(user)
    current = crud.memory.find_one({"user_id": owner, "conversation_id": conversation["_id"]})
    document = ConversationMemory(
        conversation_id=conversation["_id"],
        user_id=owner,
        case_id=conversation.get("case_id"),
        summary=payload.summary,
        key_facts=payload.key_facts,
        open_questions=payload.open_questions,
        updated_context=payload.updated_context,
        message_count=payload.message_count,
        token_estimate=payload.token_estimate,
        version=int((current or {}).get("version", 0)) + 1,
    )
    _, memory_id = crud.memory.upsert(
        {"user_id": owner, "conversation_id": conversation["_id"]}, document)
    saved = crud.memory.get(memory_id) or {}
    return MemoryRead.model_validate(saved).model_dump(mode="json")


def bump_memory(user: Any, conversation: Dict[str, Any], *, role: Any, content: str) -> None:
    """Keep the rolling memory row in step with the transcript (best effort)."""
    owner = _oid(user)
    query = {"user_id": owner, "conversation_id": conversation["_id"]}
    existing = crud.memory.find_one(query)
    changes: Dict[str, Any] = {"message_count": int((existing or {}).get("message_count", 0)) + 1}
    if role == MessageRole.USER.value and content:
        facts = list((existing or {}).get("key_facts") or [])
        summary_line = content.strip().replace("\n", " ")[:160]
        if summary_line and summary_line not in facts:
            facts.append(summary_line)
        changes["key_facts"] = facts[-25:]
    crud.memory.update(query, changes, set_on_insert={
        "conversation_id": conversation["_id"],
        "user_id": owner,
        "case_id": conversation.get("case_id"),
        "summary": "",
    }, upsert=True, return_document=False)
