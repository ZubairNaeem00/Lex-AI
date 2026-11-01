"""MongoDB connection settings, collection names, and index definitions.

Everything is driven by environment variables so the same code runs against the
local demo database (`ai_law_agent`) and the test database. The client is lazy:
importing this module never blocks, and the app still serves AI features when
MongoDB is unreachable (see `mongo_status`).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

DEFAULT_MONGO_URI = "mongodb://localhost:27017/"
DEFAULT_DB_NAME = "ai_law_agent"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Collections:
    users: str = "users"
    user_sessions: str = "user_sessions"
    cases: str = "cases"
    conversations: str = "conversations"
    messages: str = "messages"
    conversation_memory: str = "conversation_memory"
    documents: str = "uploaded_documents"
    document_analyses: str = "document_analyses"
    case_facts: str = "case_facts"
    generated_documents: str = "generated_documents"
    generation_sessions: str = "generation_sessions"
    activity_logs: str = "activity_logs"
    notifications: str = "notifications"


COLLECTIONS = Collections()


@dataclass(frozen=True)
class MongoSettings:
    uri: str
    db_name: str
    enabled: bool
    connect_timeout_ms: int

    @classmethod
    def from_env(cls) -> "MongoSettings":
        return cls(
            uri=os.getenv("MONGO_URI", DEFAULT_MONGO_URI).strip() or DEFAULT_MONGO_URI,
            db_name=os.getenv("MONGO_DB", DEFAULT_DB_NAME).strip() or DEFAULT_DB_NAME,
            enabled=_env_bool("MONGO_ENABLED", True),
            connect_timeout_ms=_env_int("MONGO_CONNECT_TIMEOUT_MS", 3000),
        )


class Database:
    """Process-wide MongoDB handle with a lazily created client."""

    def __init__(self) -> None:
        self._client: Optional[MongoClient] = None
        self._lock = threading.RLock()
        self._last_error: Optional[str] = None
        self._settings = MongoSettings.from_env()

    @property
    def settings(self) -> MongoSettings:
        return self._settings

    def configure(self, **overrides: Any) -> None:
        """Re-point the database (used by tests) and drop the cached client."""
        with self._lock:
            self.close()
            merged = {**asdict(self._settings), **overrides}
            self._settings = MongoSettings(**merged)

    def client(self) -> Optional[MongoClient]:
        if not self._settings.enabled:
            return None
        with self._lock:
            if self._client is None:
                try:
                    self._client = MongoClient(
                        self._settings.uri,
                        serverSelectionTimeoutMS=self._settings.connect_timeout_ms,
                        connectTimeoutMS=self._settings.connect_timeout_ms,
                        tz_aware=True,
                        appname="ai-law-agent",
                    )
                    self._client.admin.command("ping")
                    self._last_error = None
                except PyMongoError as exc:
                    self._client = None
                    self._last_error = f"{type(exc).__name__}: {exc}"
            return self._client

    def db(self):
        client = self.client()
        if client is None:
            raise RuntimeError(self.unavailable_reason)
        return client[self._settings.db_name]

    def collection(self, name: str):
        return self.db()[name]

    def try_collection(self, name: str):
        """Return the collection, or None when MongoDB is not usable."""
        if not self._settings.enabled:
            return None
        try:
            return self.db()[name]
        except Exception as exc:  # unreachable server, bad auth, ...
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            return None

    @property
    def unavailable_reason(self) -> str:
        if not self._settings.enabled:
            return "MongoDB persistence is disabled (MONGO_ENABLED=false)."
        return f"MongoDB is unavailable ({self._last_error or 'not connected'})."

    def status(self) -> Dict[str, Any]:
        if not self._settings.enabled:
            return {"enabled": False, "connected": False, "reason": self.unavailable_reason,
                    "database": self._settings.db_name}
        client = self.client()
        if client is None:
            return {"enabled": True, "connected": False, "reason": self.unavailable_reason,
                    "database": self._settings.db_name}
        try:
            info = client.server_info()
            collections = sorted(client[self._settings.db_name].list_collection_names())
            return {
                "enabled": True,
                "connected": True,
                "database": self._settings.db_name,
                "server_version": info.get("version"),
                "collections": collections,
            }
        except PyMongoError as exc:
            return {"enabled": True, "connected": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "database": self._settings.db_name}

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None


database = Database()


# ---------------------------------------------------------------------------
# Index definitions
# ---------------------------------------------------------------------------

def _index_spec() -> List[Dict[str, Any]]:
    c = COLLECTIONS
    return [
        {
            "collection": c.users,
            "indexes": [
                {"keys": [("email", 1)], "unique": True, "name": "uniq_email"},
                {"keys": [("created_at", -1)], "name": "created_at_desc"},
                {"keys": [("status", 1), ("created_at", -1)], "name": "status_created"},
            ],
        },
        {
            "collection": c.user_sessions,
            "indexes": [
                {"keys": [("refresh_token_hash", 1)], "unique": True, "name": "uniq_refresh_hash"},
                {"keys": [("user_id", 1), ("revoked_at", 1)], "name": "user_active"},
                {"keys": [("expires_at", 1)], "name": "expiry_ttl",
                 "options": {"expireAfterSeconds": 0}},
            ],
        },
        {
            "collection": c.cases,
            "indexes": [
                {"keys": [("case_key", 1)], "unique": True, "name": "uniq_case_key"},
                {"keys": [("user_id", 1), ("updated_at", -1)], "name": "user_updated"},
                {"keys": [("user_id", 1), ("status", 1)], "name": "user_status"},
                {"keys": [("user_id", 1), ("runtime_case_id", 1)], "name": "user_runtime"},
            ],
        },
        {
            "collection": c.conversations,
            "indexes": [
                {"keys": [("user_id", 1), ("updated_at", -1)], "name": "user_updated"},
                {"keys": [("case_id", 1), ("updated_at", -1)], "name": "case_updated"},
            ],
        },
        {
            "collection": c.messages,
            "indexes": [
                {"keys": [("conversation_id", 1), ("created_at", 1)], "name": "conversation_order"},
                {"keys": [("user_id", 1), ("created_at", -1)], "name": "user_created"},
                {"keys": [("case_id", 1)], "name": "case_id"},
            ],
        },
        {
            "collection": c.conversation_memory,
            "indexes": [
                {"keys": [("conversation_id", 1)], "unique": True, "name": "uniq_conversation"},
                {"keys": [("user_id", 1)], "name": "user_id"},
            ],
        },
        {
            "collection": c.documents,
            "indexes": [
                {"keys": [("user_id", 1), ("case_id", 1), ("created_at", -1)], "name": "user_case"},
                {"keys": [("case_id", 1), ("status", 1)], "name": "case_status"},
                {"keys": [("user_id", 1), ("sha256", 1)], "name": "user_checksum"},
            ],
        },
        {
            "collection": c.document_analyses,
            "indexes": [
                {"keys": [("user_id", 1), ("case_id", 1)], "name": "user_case"},
                {"keys": [("document_id", 1), ("version", -1)], "name": "document_version"},
            ],
        },
        {
            "collection": c.case_facts,
            "indexes": [
                {"keys": [("case_id", 1), ("field_name", 1)], "unique": True, "name": "uniq_case_field"},
                {"keys": [("user_id", 1)], "name": "user_id"},
            ],
        },
        {
            "collection": c.generated_documents,
            "indexes": [
                {"keys": [("user_id", 1), ("case_id", 1), ("created_at", -1)], "name": "user_case"},
                {"keys": [("generation_session_id", 1)], "name": "generation_session"},
            ],
        },
        {
            "collection": c.generation_sessions,
            "indexes": [
                {"keys": [("user_id", 1), ("case_id", 1), ("updated_at", -1)], "name": "user_case"},
                {"keys": [("conversation_id", 1)], "name": "conversation_id"},
                {"keys": [("session_key", 1)], "unique": True, "name": "uniq_session_key"},
            ],
        },
        {
            "collection": c.activity_logs,
            "indexes": [
                {"keys": [("user_id", 1), ("created_at", -1)], "name": "user_created"},
                {"keys": [("resource_type", 1), ("resource_id", 1)], "name": "resource"},
            ],
        },
        {
            "collection": c.notifications,
            "indexes": [
                {"keys": [("user_id", 1), ("created_at", -1)], "name": "user_created"},
                {"keys": [("user_id", 1), ("read", 1)], "name": "user_read"},
            ],
        },
    ]


def ensure_indexes() -> Dict[str, Any]:
    """Create every index. Safe to call repeatedly; reports per collection."""
    if not database.settings.enabled:
        return {"created": [], "skipped": [], "errors": [], "connected": False}
    created: List[str] = []
    errors: List[str] = []
    for spec in _index_spec():
        collection = database.try_collection(spec["collection"])
        if collection is None:
            return {"created": created, "skipped": [],
                    "errors": [database.unavailable_reason], "connected": False}
        for index in spec["indexes"]:
            keys = index["keys"]
            name = index.get("name")
            options = {k: v for k, v in index.items() if k in {"unique", "expireAfterSeconds", "sparse"}}
            options.update(index.get("options") or {})
            try:
                collection.create_index(keys, name=name, background=True, **options)
                created.append(f"{spec['collection']}.{name}")
            except PyMongoError as exc:
                errors.append(f"{spec['collection']}.{name}: {exc.codeName or exc}")
    return {"created": created, "skipped": [], "errors": errors, "connected": not errors}
