"""Conversations: the durable chat transcript behind the RAG agent.

`case_id` may be null — that is how case-less general legal questions are stored
without inventing a throw-away case.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status

from auth.deps import AuthenticatedUser, get_current_user
from db.schemas import (
    ConversationCreate,
    ConversationUpdate,
    MemoryUpdate,
    MessageCreate,
    MessageRead,
)
from services import case_service, chat_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

PAGE = Query(default=1, ge=1, le=100000)
SIZE = Query(default=20, ge=1, le=200)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start a conversation")
def create_conversation(payload: ConversationCreate,
                        user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    case = case_service.get(user, payload.case_id) if payload.case_id else None
    return chat_service.read(chat_service.create(user, payload, case=case))


@router.get("", summary="List my conversations")
def list_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    page: int = PAGE,
    page_size: int = SIZE,
    case_id: Optional[str] = Query(default=None, max_length=80),
    conversation_type: Optional[str] = Query(default=None, alias="type", max_length=40),
    include_archived: bool = Query(default=True),
    unassigned: bool = Query(default=False, description="Only case-less conversations"),
) -> Dict[str, Any]:
    return chat_service.list_conversations(user, page=page, page_size=page_size,
                                           case_id=case_id,
                                           conversation_type=conversation_type or "",
                                           include_archived=include_archived,
                                           unassigned=unassigned)


@router.get("/{conversation_id}", summary="One conversation")
def get_conversation(conversation_id: str,
                     user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return chat_service.read(chat_service.get(user, conversation_id))


@router.patch("/{conversation_id}", summary="Rename, move or archive a conversation")
def update_conversation(conversation_id: str, payload: ConversationUpdate,
                        user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    if payload.case_id:
        case_service.get(user, payload.case_id)
    return chat_service.read(chat_service.update(user, conversation_id, payload))


@router.delete("/{conversation_id}", summary="Archive, or permanently delete")
def delete_conversation(conversation_id: str,
                        permanent: bool = Query(default=False),
                        user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return chat_service.delete(user, conversation_id, permanent=permanent)


@router.get("/{conversation_id}/messages", summary="Transcript (oldest first)")
def get_messages(conversation_id: str,
                 user: AuthenticatedUser = Depends(get_current_user),
                 page: int = PAGE,
                 page_size: int = Query(default=50, ge=1, le=200),
                 include_hidden: bool = Query(default=False)) -> Dict[str, Any]:
    return chat_service.list_messages(user, conversation_id, page=page, page_size=page_size,
                                      include_hidden=include_hidden)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED,
             summary="Append a message to the transcript")
def append_message(conversation_id: str, payload: MessageCreate,
                   user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    conversation = chat_service.get(user, conversation_id)
    document = chat_service.append_message(user, conversation, payload)
    return MessageRead.model_validate(document).model_dump(mode="json")


@router.get("/{conversation_id}/memory", summary="Rolling conversation memory")
def get_memory(conversation_id: str,
               user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return chat_service.memory(user, conversation_id)


@router.put("/{conversation_id}/memory", summary="Replace conversation memory")
def put_memory(conversation_id: str, payload: MemoryUpdate,
               user: AuthenticatedUser = Depends(get_current_user)) -> Dict[str, Any]:
    return chat_service.update_memory(user, conversation_id, payload)
