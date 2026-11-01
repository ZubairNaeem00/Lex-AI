"""Database-backed API routers, kept separate from the AI pipeline.

`ALL_ROUTERS` is what `main.py` mounts; the test suite builds the same router set
on a bare FastAPI app, so route behaviour is verified without loading the
embedding model or FAISS indexes.
"""

from __future__ import annotations

from typing import List

from api import activity, auth, cases, conversations, documents, generation, notifications, users
from fastapi import APIRouter

ALL_ROUTERS: List[APIRouter] = [
    auth.router,
    users.router,
    cases.router,
    conversations.router,
    documents.router,
    documents.facts_router,
    generation.router,
    activity.router,
    notifications.router,
]

__all__ = ["ALL_ROUTERS", "activity", "auth", "cases", "conversations", "documents",
           "generation", "notifications", "users"]
