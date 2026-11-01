"""API request/response schemas: input validation and secret-free output models.

The rules here mirror the client-side validation in the frontend so a request that
passes in the browser also passes on the server (and vice versa).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from db.models import (
    AccountStatus,
    AnalysisStatus,
    CaseStatus,
    ConversationType,
    GeneratedDocStatus,
    GenerationStatus,
    MessageRole,
    PyObjectId,
    SourceCitation,
    UserProfile,
    UploadStatus,
    optional_object_id_validator,
)

SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,80}$")
NAME_PATTERN = re.compile(r"^[^0-9\n\t]{1,160}$")


def validate_password_strength(password: str) -> str:
    """Argon2id input policy: long enough, not trivially guessable."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters long.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one number.")
    if re.fullmatch(r"(.)\1*", password):
        raise ValueError("Password must not be a single repeated character.")
    return password


class InputBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class SignupRequest(InputBase):
    """Accepts either `full_name` or the frontend's `username` field."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    username: Optional[str] = Field(default=None, min_length=2, max_length=160)
    email: EmailStr
    password: str
    role: str = Field(default="Advocate", max_length=60)

    @model_validator(mode="after")
    def _resolve_name(self) -> "SignupRequest":
        name = (self.full_name or self.username or "").strip()
        if len(name) < 2:
            raise ValueError("A name is required.")
        if not NAME_PATTERN.match(name):
            raise ValueError("Full name must not start with a digit.")
        self.full_name = name
        return self

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(InputBase):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(InputBase):
    refresh_token: str = Field(min_length=10, max_length=4000)


class OutboundIdentity(InputBase):
    """Never accepted from the client — kept as a marker for docs/lint."""


class TokenPair(BaseModel):
    token: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    user: "UserRead"


class ChangePasswordRequest(InputBase):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class ForgotPasswordRequest(InputBase):
    email: EmailStr


class ResetPasswordRequest(InputBase):
    token: str = Field(min_length=10, max_length=4000)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class VerifyEmailRequest(InputBase):
    token: str = Field(min_length=10, max_length=4000)


class ProfileUpdateRequest(InputBase):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    profile: Optional[UserProfile] = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not NAME_PATTERN.match(value):
            raise ValueError("Full name must not start with a digit.")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    full_name: str
    email: EmailStr
    status: AccountStatus
    email_verified: bool
    profile: UserProfile = Field(default_factory=UserProfile)
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None


TokenPair.model_rebuild()


class AuthenticatedUser(BaseModel):
    """What `auth/deps.py` hands to every protected route."""

    model_config = ConfigDict(populate_by_name=True)

    id: PyObjectId = Field(alias="_id")
    email: EmailStr
    full_name: str
    status: AccountStatus
    token_id: str = ""
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

class CaseCreate(InputBase):
    name: str = Field(min_length=1, max_length=200)
    case_type: str = Field(default="general", max_length=80)
    description: str = Field(default="", max_length=4000)
    status: CaseStatus = CaseStatus.OPEN
    court: str = Field(default="", max_length=200)
    filed_on: Optional[datetime] = None
    runtime_case_id: str = Field(default="", max_length=80)

    @field_validator("runtime_case_id")
    @classmethod
    def _runtime(cls, value: str) -> str:
        if value and not SAFE_ID_PATTERN.match(value):
            raise ValueError("runtime_case_id contains unsupported characters.")
        return value


class CaseUpdate(InputBase):
    """Every field is optional; `case_service.update` rejects an empty patch with 400,
    so no validator belongs here — it would answer 422 instead."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    case_type: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[CaseStatus] = None
    court: Optional[str] = Field(default=None, max_length=200)
    filed_on: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    archived: Optional[bool] = None
    pinned: Optional[bool] = None


class CaseRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_key: str
    runtime_case_id: str = ""
    name: str
    case_type: str
    description: str = ""
    status: CaseStatus
    court: str = ""
    filed_on: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    archived: bool = False
    pinned: bool = False
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    message_count: int = 0


# ---------------------------------------------------------------------------
# Conversations, messages, memory
# ---------------------------------------------------------------------------

class ConversationCreate(InputBase):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    type: ConversationType = ConversationType.GENERAL
    case_id: Optional[str] = None

    @field_validator("case_id")
    @classmethod
    def _case(cls, value: Optional[str]) -> Optional[str]:
        return optional_object_id_validator(value)


class ConversationUpdate(InputBase):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    case_id: Optional[str] = None
    archived: Optional[bool] = None
    type: Optional[ConversationType] = None

    @field_validator("case_id")
    @classmethod
    def _case(cls, value: Optional[str]) -> Optional[str]:
        return optional_object_id_validator(value)


class MessageCreate(InputBase):
    role: MessageRole = MessageRole.USER
    content: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="legal", max_length=40)
    sources: List[SourceCitation] = Field(default_factory=list)
    hidden: bool = False


class MessageRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    conversation_id: PyObjectId
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    role: MessageRole
    content: str
    kind: str = "legal"
    sources: List[SourceCitation] = Field(default_factory=list)
    source_labels: List[str] = Field(default_factory=list)
    tool_called: Optional[str] = None
    hidden: bool = False
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    runtime_case_id: str = ""
    title: str
    type: ConversationType
    archived: bool = False
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MemoryUpdate(InputBase):
    summary: str = Field(default="", max_length=8000)
    key_facts: List[str] = Field(default_factory=list, max_length=100)
    open_questions: List[str] = Field(default_factory=list, max_length=50)
    updated_context: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = Field(default=0, ge=0)
    token_estimate: int = Field(default=0, ge=0)


class MemoryRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    conversation_id: PyObjectId
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    summary: str = ""
    key_facts: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    updated_context: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    token_estimate: int = 0
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Documents, analyses, facts
# ---------------------------------------------------------------------------

class DocumentRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    conversation_id: Optional[PyObjectId] = None
    runtime_case_id: str = ""
    runtime_document_id: str = ""
    filename: str
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    status: UploadStatus
    error: str = ""
    archived: bool = False
    created_at: datetime
    updated_at: datetime


class AnalysisRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    document_id: Optional[PyObjectId] = None
    report: Dict[str, Any] = Field(default_factory=dict)
    editable_data: Dict[str, Any] = Field(default_factory=dict)
    edits: List[Dict[str, Any]] = Field(default_factory=list)
    status: AnalysisStatus
    version: int = 1
    analysis_model: str = ""
    extracted_characters: int = 0
    created_at: datetime
    updated_at: datetime


class AnalysisUpdateRequest(InputBase):
    """Editable analysis data; keys are dotted paths like `filing.fir_number`."""

    edits: List[Dict[str, Any]] = Field(min_length=1, max_length=100)


class CaseFactUpsert(InputBase):
    field_name: str = Field(min_length=1, max_length=200)
    field_value: str = Field(default="", max_length=5000)
    source: str = Field(default="user", max_length=60)
    source_document_id: Optional[str] = None
    value_type: str = Field(default="string", max_length=40)
    corrected: bool = True

    @field_validator("source_document_id")
    @classmethod
    def _doc(cls, value: Optional[str]) -> Optional[str]:
        return optional_object_id_validator(value)


class CaseFactBatchUpsert(InputBase):
    facts: List[CaseFactUpsert] = Field(min_length=1, max_length=300)


class CaseFactRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_id: PyObjectId
    field_name: str
    field_value: str
    source: str
    source_document_id: Optional[PyObjectId] = None
    value_type: str = "string"
    corrected: bool = False
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

class GenerationSessionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    conversation_id: Optional[PyObjectId] = None
    session_key: str
    document_type: str = ""
    template_name: str = ""
    current_step: str = ""
    collected_information: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    status: GenerationStatus
    error: str = ""
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class GenerationSessionUpsert(InputBase):
    session_key: str = Field(min_length=1, max_length=80)
    conversation_id: Optional[str] = None
    document_type: str = Field(default="", max_length=120)
    template_name: str = Field(default="", max_length=200)
    current_step: str = Field(default="", max_length=120)
    collected_information: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list, max_length=200)
    status: GenerationStatus = GenerationStatus.COLLECTING
    error: str = Field(default="", max_length=500)

    @field_validator("conversation_id")
    @classmethod
    def _conversation(cls, value: Optional[str]) -> Optional[str]:
        return optional_object_id_validator(value)


class GeneratedDocumentRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    case_id: Optional[PyObjectId] = None
    generation_session_id: Optional[PyObjectId] = None
    runtime_document_id: str = ""
    document_type: str = ""
    template_name: str = ""
    filename: str
    download_url: str = ""
    values: Dict[str, str] = Field(default_factory=dict)
    status: GeneratedDocStatus
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Activity and notifications
# ---------------------------------------------------------------------------

class ActivityRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: Optional[PyObjectId] = None
    action: str
    resource_type: str = ""
    resource_id: str = ""
    detail: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NotificationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: PyObjectId = Field(alias="_id")
    user_id: PyObjectId
    title: str
    message: str = ""
    kind: str = "info"
    read: bool = False
    read_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NotificationCreate(InputBase):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(default="", max_length=4000)
    kind: str = Field(default="info", max_length=60)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NotificationStatusUpdate(InputBase):
    read: bool = True


# ---------------------------------------------------------------------------
# Pagination envelope
# ---------------------------------------------------------------------------

class Page(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: List[Any]
    page: int
    page_size: int
    total: int
    pages: int
    has_more: bool = False


class OkResponse(BaseModel):
    ok: bool = True
    detail: str = ""


__all__ = [
    "ActivityRead",
    "AnalysisRead",
    "AnalysisStatus",
    "AnalysisUpdateRequest",
    "AuthenticatedUser",
    "CaseCreate",
    "CaseFactBatchUpsert",
    "CaseFactRead",
    "CaseFactUpsert",
    "CaseRead",
    "CaseUpdate",
    "ChangePasswordRequest",
    "ConversationCreate",
    "ConversationRead",
    "ConversationUpdate",
    "DocumentRead",
    "ForgotPasswordRequest",
    "GeneratedDocumentRead",
    "GenerationSessionRead",
    "GenerationSessionUpsert",
    "LoginRequest",
    "MemoryRead",
    "MemoryUpdate",
    "MessageCreate",
    "MessageRead",
    "NotificationCreate",
    "NotificationRead",
    "NotificationStatusUpdate",
    "OkResponse",
    "Page",
    "ProfileUpdateRequest",
    "RefreshRequest",
    "ResetPasswordRequest",
    "SignupRequest",
    "TokenPair",
    "UserRead",
    "validate_password_strength",
]
