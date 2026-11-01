"""Generic CRUD operations on top of the MongoDB collections.

Every write goes through `to_insert()`/`$set` helpers so documents keep their
timestamps, and every read that belongs to a user is filtered by `user_id` in the
database query itself — never by trusting an id supplied by the client.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from db.config import database


class Conflict(Exception):
    """Unique-index violation, reported as a friendly error."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.field = field


MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_oid(value: Any, field: str = "id") -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError) as exc:
        raise ValueError(f"{field} is not a valid ObjectId: {value!r}") from exc


def maybe_oid(value: Any) -> Any:
    """Coerce genuine ObjectIds; pass opaque string ids through unchanged."""
    if value is None or isinstance(value, ObjectId):
        return value
    try:
        return to_oid(value)
    except ValueError:
        return value


def clean_filter(query: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce `*_id` keys to ObjectId so queries match stored values.

    Some `*_id` columns deliberately hold opaque strings (session families,
    runtime case ids); those fail to parse and are left untouched.
    """
    cleaned: Dict[str, Any] = {}
    for key, value in query.items():
        if not key.endswith("_id") or value is None:
            cleaned[key] = value
            continue
        if isinstance(value, dict):
            cleaned[key] = {
                op: [maybe_oid(item) for item in val] if op == "$in" and isinstance(val, list)
                else maybe_oid(val)
                for op, val in value.items()
            }
        elif isinstance(value, list):
            cleaned[key] = [maybe_oid(item) for item in value]
        else:
            cleaned[key] = maybe_oid(value)
    return cleaned


class Repository:
    """A thin, safe wrapper around one collection."""

    def __init__(self, name: str) -> None:
        self.name = name

    # -- connection ---------------------------------------------------------
    def collection(self):
        collection = database.try_collection(self.name)
        if collection is None:
            raise RuntimeError(database.unavailable_reason)
        return collection

    def available(self) -> bool:
        return database.try_collection(self.name) is not None

    # -- writes -------------------------------------------------------------
    def insert(self, document: Any) -> str:
        payload = document.to_insert() if hasattr(document, "to_insert") else dict(document)
        payload.setdefault("created_at", utc_now())
        payload.setdefault("updated_at", utc_now())
        try:
            result = self.collection().insert_one(payload)
        except DuplicateKeyError as exc:
            raise Conflict(self._duplicate_message(exc), self._duplicate_field(exc)) from exc
        return str(result.inserted_id)

    def insert_many(self, documents: Sequence[Any]) -> List[str]:
        payloads = []
        for document in documents:
            payload = document.to_insert() if hasattr(document, "to_insert") else dict(document)
            payload.setdefault("created_at", utc_now())
            payload.setdefault("updated_at", utc_now())
            payloads.append(payload)
        if not payloads:
            return []
        try:
            result = self.collection().insert_many(payloads, ordered=True)
        except DuplicateKeyError as exc:
            raise Conflict(self._duplicate_message(exc), self._duplicate_field(exc)) from exc
        return [str(inserted) for inserted in result.inserted_ids]

    def upsert(self, query: Dict[str, Any], document: Any) -> Tuple[str, Optional[str]]:
        """Insert or replace; returns (action, id)."""
        base = clean_filter(query)
        payload = document.to_insert() if hasattr(document, "to_insert") else dict(document)
        existing_id = payload.pop("_id", None)
        key = dict(base)
        if existing_id is not None:
            key = {"_id": to_oid(existing_id)}
        set_payload = {k: v for k, v in payload.items() if k != "created_at"}
        set_payload["updated_at"] = utc_now()
        result = self.collection().update_one(
            key,
            {"$set": set_payload, "$setOnInsert": {"created_at": payload.get("created_at", utc_now())}},
            upsert=True,
        )
        action = "created" if result.upserted_id is not None else "updated"
        doc_id = str(result.upserted_id) if result.upserted_id is not None else self.find_id(key)
        return action, doc_id

    def update(
        self,
        query: Dict[str, Any],
        set_values: Optional[Dict[str, Any]] = None,
        *,
        push: Optional[Dict[str, Any]] = None,
        inc: Optional[Dict[str, int]] = None,
        set_on_insert: Optional[Dict[str, Any]] = None,
        upsert: bool = False,
        return_document: bool = True,
    ) -> Optional[Dict[str, Any]]:
        base = clean_filter(query)
        operations: Dict[str, Any] = {}
        changes = dict(set_values or {})
        changes["updated_at"] = utc_now()
        operations["$set"] = changes
        if push:
            operations["$push"] = push
        if inc:
            operations["$inc"] = inc
        if set_on_insert:
            operations["$setOnInsert"] = set_on_insert
        if upsert:
            # An upsert can insert; that row needs the same bookkeeping as insert().
            operations["$setOnInsert"] = {
                "created_at": utc_now(),
                **(operations.get("$setOnInsert") or {}),
            }
        try:
            result = self.collection().find_one_and_update(
                base,
                operations,
                return_document=ReturnDocument.AFTER if return_document else ReturnDocument.BEFORE,
                upsert=upsert,
            )
        except DuplicateKeyError as exc:
            raise Conflict(self._duplicate_message(exc), self._duplicate_field(exc)) from exc
        return result

    def set_by_id(self, document_id: Any, set_values: Dict[str, Any], **kwargs: Any) -> Optional[Dict[str, Any]]:
        return self.update({"_id": to_oid(document_id)}, set_values, **kwargs)

    def delete(self, query: Dict[str, Any]) -> int:
        return int(self.collection().delete_many(clean_filter(query)).deleted_count)

    def delete_by_id(self, document_id: Any) -> bool:
        return int(self.collection().delete_one({"_id": to_oid(document_id)}).deleted_count) == 1

    # -- reads --------------------------------------------------------------
    def find_one(self, query: Dict[str, Any],
                 sort: Optional[Sequence[Tuple[str, int]]] = None) -> Optional[Dict[str, Any]]:
        if sort:
            rows = self.find(query, sort=sort, limit=1)
            return rows[0] if rows else None
        return self.collection().find_one(clean_filter(query))

    def find_id(self, query: Dict[str, Any]) -> Optional[str]:
        document = self.collection().find_one(clean_filter(query), {"_id": 1})
        return str(document["_id"]) if document else None

    def get(self, document_id: Any) -> Optional[Dict[str, Any]]:
        if document_id in (None, ""):
            return None
        return self.collection().find_one({"_id": to_oid(document_id)})

    def count(self, query: Optional[Dict[str, Any]] = None) -> int:
        return int(self.collection().count_documents(clean_filter(query or {})))

    def exists(self, query: Dict[str, Any]) -> bool:
        return self.collection().count_documents(clean_filter(query), limit=1) > 0

    def find(
        self,
        query: Optional[Dict[str, Any]] = None,
        *,
        sort: Optional[Sequence[Tuple[str, int]]] = None,
        limit: int = 0,
        projection: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        cursor = self.collection().find(clean_filter(query or {}), projection)
        if sort:
            cursor = cursor.sort(list(sort))
        if limit:
            cursor = cursor.limit(int(limit))
        return list(cursor)

    def paginate(
        self,
        query: Optional[Dict[str, Any]] = None,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort: Optional[Sequence[Tuple[str, int]]] = None,
        projection: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or DEFAULT_PAGE_SIZE)))
        base = clean_filter(query or {})
        total = int(self.collection().count_documents(base))
        cursor = self.collection().find(base, projection)
        if sort:
            cursor = cursor.sort(list(sort))
        items = list(cursor.skip((page - 1) * page_size).limit(page_size))
        pages = max(1, math.ceil(total / page_size)) if total else 0
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": pages,
            "has_more": page < pages,
        }

    # -- errors -------------------------------------------------------------
    @staticmethod
    def _duplicate_field(exc: DuplicateKeyError) -> str:
        details = getattr(exc, "details", None) or {}
        index = details.get("index_details") or {}
        keys = index.get("key_value") or {}
        if isinstance(keys, dict) and keys:
            return str(list(keys.keys())[0])
        message = str(exc)
        for fragment in message.split("index: "):
            if " " in fragment:
                return fragment.strip().split(" ")[0]
        return ""

    @classmethod
    def _duplicate_message(cls, exc: DuplicateKeyError) -> str:
        field = cls._duplicate_field(exc)
        if field == "email" or "email" in str(exc):
            return "An account with this email already exists."
        return f"A record with this {field or 'value'} already exists."


# ---------------------------------------------------------------------------
# Typed repositories
# ---------------------------------------------------------------------------

from db.config import COLLECTIONS  # noqa: E402  (import after helpers to stay readable)

users = Repository(COLLECTIONS.users)
user_sessions = Repository(COLLECTIONS.user_sessions)
cases = Repository(COLLECTIONS.cases)
conversations = Repository(COLLECTIONS.conversations)
messages = Repository(COLLECTIONS.messages)
memory = Repository(COLLECTIONS.conversation_memory)
documents = Repository(COLLECTIONS.documents)
analyses = Repository(COLLECTIONS.document_analyses)
case_facts = Repository(COLLECTIONS.case_facts)
generated_documents = Repository(COLLECTIONS.generated_documents)
generation_sessions = Repository(COLLECTIONS.generation_sessions)
activity_logs = Repository(COLLECTIONS.activity_logs)
notifications = Repository(COLLECTIONS.notifications)

ALL_REPOSITORIES: Dict[str, Repository] = {
    "users": users,
    "user_sessions": user_sessions,
    "cases": cases,
    "conversations": conversations,
    "messages": messages,
    "conversation_memory": memory,
    "uploaded_documents": documents,
    "document_analyses": analyses,
    "case_facts": case_facts,
    "generated_documents": generated_documents,
    "generation_sessions": generation_sessions,
    "activity_logs": activity_logs,
    "notifications": notifications,
}


def owned_or_404(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if record is None:
        raise LookupError("Record not found.")
    return record


def user_query(user: Any, **extra: Any) -> Dict[str, Any]:
    """Pin a database query to one account.

    `user` is either an `AuthenticatedUser` or a raw id: the owning user always
    comes from the JWT, never from the request body.
    """
    owner = getattr(user, "id", user)
    query: Dict[str, Any] = {"user_id": to_oid(owner, "user_id")}
    query.update(extra)
    return query


def escape_regex(value: str) -> str:
    """Safe `$regex` fragment for search boxes."""
    return re.escape(str(value or ""))


def new_object_key(prefix: str = "") -> str:
    """Opaque unique key for a business object (case, generation session)."""
    return f"{prefix}{uuid.uuid4().hex}"
