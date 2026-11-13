"""Pydantic document models for every MongoDB collection.

Ids are real `bson.ObjectId` values; relationships between collections are stored
as ObjectId references (`user_id`, `case_id`, `conversation_id`, `document_id`,
`generation_session_id`). Timestamps are timezone-aware UTC datetimes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic_core import core_schema

OID_REGEX = re.compile(r"^[0-9a-fA-F]{24}$")


def coerce_object_id(value: Any) -> Any:
    if value is None or isinstance(value, ObjectId):
        return value
    text = str(value).strip()
    if OID_REGEX.match(text):
        return ObjectId(text)
    raise ValueError("Invalid MongoDB ObjectId")


class _ObjectIdSchema:
    """Teach Pydantic about bson.ObjectId once, so no model needs extra config."""

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: Any) -> Any:
        return core_schema.no_info_after_validator_function(
            coerce_object_id,
            core_schema.any_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: str(value) if value is not None else None,
                when_used="json",
            ),
        )


PyObjectId = Annotated[ObjectId, _ObjectIdSchema()]
OptionalObjectId = Annotated[Optional[ObjectId], _ObjectIdSchema()]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def optional_object_id_validator(value: Optional[str]) -> Optional[str]:
    """Accept blank or a 24-hex ObjectId; anything else is a validation error."""
    if value in (None, ""):
        return value
    if not OID_REGEX.match(str(value)):
        raise ValueError("Expected a 24-character MongoDB ObjectId")
    return str(value)


class BaseDoc(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True,
                              str_strip_whitespace=True)

    id: OptionalObjectId = Field(default=None, alias="_id")
    created_at: datetime = Field(default_factory=utc_now)

    def to_insert(self) -> Dict[str, Any]:
        data = self.model_dump(by_alias=True)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class CaseStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_COURT = "pending_court"
    CLOSED = "closed"
    ARCHIVED = "archived"


class ConversationType(str, Enum):
    GENERAL = "general"
    CASE = "case"
    GENERATION = "generation"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class UploadStatus(str, Enum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    ANALYZED = "analyzed"
    FAILED = "failed"


class AnalysisStatus(str, Enum):
    DRAFT = "draft"
    COMPLETE = "complete"
    EDITED = "edited"
    FAILED = "failed"


class GenerationStatus(str, Enum):
    COLLECTING = "collecting"
    REVIEW = "review"
    GENERATING = "generating"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class GeneratedDocStatus(str, Enum):
    GENERATED = "generated"
    DOWNLOADED = "downloaded"
    SUPERSEDED = "superseded"
    MISSING_FILE = "missing_file"


# ---------------------------------------------------------------------------
# Users and sessions
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    occupation: str = ""
    phone: str = ""
    address: str = ""
    jurisdiction: str = ""
    bar_registration: str = ""
    organisation: str = ""
    avatar_url: str = ""


class User(BaseDoc):
    full_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    password_hash: str = Field(min_length=8)
    profile: UserProfile = Field(default_factory=UserProfile)
    status: AccountStatus = AccountStatus.PENDING
    email_verified: bool = False
    verification_token_hash: Optional[str] = None
    verification_expires_at: Optional[datetime] = None
    reset_token_hash: Optional[str] = None
    reset_expires_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("full_name must not be blank")
        return value


class UserSession(BaseDoc):
    user_id: PyObjectId
    refresh_token_hash: str = Field(min_length=8)
    family_id: Optional[str] = None
    access_jti: Optional[str] = None
    ip_address: str = ""
    user_agent: str = ""
    login_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_reason: str = ""

    updated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Cases, conversations, messages, memory
# ---------------------------------------------------------------------------

class Case(BaseDoc):
    user_id: PyObjectId
    case_key: str = Field(min_length=1, max_length=80)
    runtime_case_id: str = Field(default="", max_length=80)
    name: str = Field(default="New case", min_length=1, max_length=200)
    case_type: str = Field(default="general", max_length=80)
    description: str = Field(default="", max_length=4000)
    status: CaseStatus = CaseStatus.OPEN
    court: str = Field(default="", max_length=200)
    filed_on: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    archived: bool = False
    pinned: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


class Conversation(BaseDoc):
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    runtime_case_id: str = Field(default="", max_length=80)
    title: str = Field(default="New conversation", max_length=200)
    type: ConversationType = ConversationType.GENERAL
    archived: bool = False
    last_message_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)


class SourceCitation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(default="", max_length=400)
    kind: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=300)
    citation: str = Field(default="", max_length=300)
    score: Optional[float] = None


class Message(BaseDoc):
    conversation_id: PyObjectId
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    role: MessageRole
    content: str = Field(min_length=1)
    kind: str = Field(default="legal", max_length=40)
    sources: List[SourceCitation] = Field(default_factory=list)
    source_labels: List[str] = Field(default_factory=list)
    tool_called: Optional[str] = None
    hidden: bool = False
    # False for turns that are shown in the chat but must not be replayed to the
    # model: document-drafting answers belong to the generation session.
    include_in_history: bool = True
    meta: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class ConversationMemory(BaseDoc):
    conversation_id: PyObjectId
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    summary: str = Field(default="", max_length=8000)
    key_facts: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    updated_context: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    token_estimate: int = 0
    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Documents, analyses, facts
# ---------------------------------------------------------------------------

class UploadedDocument(BaseDoc):
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    conversation_id: OptionalObjectId = None
    runtime_case_id: str = Field(default="", max_length=80)
    runtime_document_id: str = Field(default="", max_length=80)
    filename: str = Field(min_length=1, max_length=300)
    stored_path: str = Field(default="", max_length=1000)
    content_type: str = Field(default="", max_length=120)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = Field(default="", max_length=80)
    status: UploadStatus = UploadStatus.PENDING
    error: str = Field(default="", max_length=500)
    archived: bool = False
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("filename")
    @classmethod
    def _safe_filename(cls, value: str) -> str:
        name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name or name in {".", ".."}:
            raise ValueError("Invalid filename")
        return name[:300]


class DocumentAnalysis(BaseDoc):
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    document_id: OptionalObjectId = None
    extracted_text: str = Field(default="")
    report: Dict[str, Any] = Field(default_factory=dict)
    original_report: Dict[str, Any] = Field(default_factory=dict)
    editable_data: Dict[str, Any] = Field(default_factory=dict)
    edits: List[Dict[str, Any]] = Field(default_factory=list)
    status: AnalysisStatus = AnalysisStatus.COMPLETE
    version: int = Field(default=1, ge=1)
    analysis_model: str = Field(default="", max_length=120)
    updated_at: datetime = Field(default_factory=utc_now)


class CaseFact(BaseDoc):
    user_id: PyObjectId
    case_id: PyObjectId
    field_name: str = Field(min_length=1, max_length=200)
    field_value: str = Field(default="", max_length=5000)
    source: str = Field(default="user", max_length=60)
    source_document_id: OptionalObjectId = None
    value_type: str = Field(default="string", max_length=40)
    corrected: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------

class GeneratedDocument(BaseDoc):
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    generation_session_id: OptionalObjectId = None
    conversation_id: OptionalObjectId = None
    runtime_document_id: str = Field(default="", max_length=80)
    document_type: str = Field(default="", max_length=120)
    template_name: str = Field(default="", max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    file_path: str = Field(default="", max_length=1000)
    download_url: str = Field(default="", max_length=600)
    values: Dict[str, str] = Field(default_factory=dict)
    status: GeneratedDocStatus = GeneratedDocStatus.GENERATED
    version: int = Field(default=1, ge=1)
    supersedes_id: OptionalObjectId = None
    updated_at: datetime = Field(default_factory=utc_now)


class GenerationSession(BaseDoc):
    user_id: PyObjectId
    case_id: OptionalObjectId = None
    conversation_id: OptionalObjectId = None
    session_key: str = Field(min_length=1, max_length=80)
    document_type: str = Field(default="", max_length=120)
    template_name: str = Field(default="", max_length=200)
    current_step: str = Field(default="", max_length=120)
    collected_information: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    # Exact runtime workflow state, so a restart can resume the same conversation
    # (answers, locked fields and the outstanding question) instead of re-asking.
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
    status: GenerationStatus = GenerationStatus.COLLECTING
    error: str = Field(default="", max_length=500)
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Activity and notifications
# ---------------------------------------------------------------------------

class ActivityLog(BaseDoc):
    user_id: OptionalObjectId = None
    action: str = Field(min_length=1, max_length=120)
    resource_type: str = Field(default="", max_length=80)
    resource_id: str = Field(default="", max_length=120)
    detail: str = Field(default="", max_length=1000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    ip_address: str = Field(default="", max_length=80)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("action")
    @classmethod
    def _action_slug(cls, value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_")
        if not re.match(r"^[a-z0-9_.:-]{1,120}$", cleaned):
            raise ValueError("action must be a short slug")
        return cleaned


class Notification(BaseDoc):
    user_id: PyObjectId
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(default="", max_length=4000)
    kind: str = Field(default="info", max_length=60)
    read: bool = False
    read_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


MODEL_BY_COLLECTION: Dict[str, type[BaseDoc]] = {
    "users": User,
    "user_sessions": UserSession,
    "cases": Case,
    "conversations": Conversation,
    "messages": Message,
    "conversation_memory": ConversationMemory,
    "uploaded_documents": UploadedDocument,
    "document_analyses": DocumentAnalysis,
    "case_facts": CaseFact,
    "generated_documents": GeneratedDocument,
    "generation_sessions": GenerationSession,
    "activity_logs": ActivityLog,
    "notifications": Notification,
}
