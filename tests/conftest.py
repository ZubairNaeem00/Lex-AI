"""Shared pytest wiring: a disposable database and a router-only FastAPI app.

The routers are mounted on a bare app on purpose — that keeps the auth, CRUD and
isolation suite independent of the embedding model and FAISS indexes, which take
minutes to load. The AI pipeline itself is exercised against the running server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MONGO_ENABLED"] = "true"
os.environ["MONGO_DB"] = os.environ.get("TEST_MONGO_DB", "ai_law_agent_pytest")
os.environ["JWT_SECRET"] = "pytest-only-secret-not-for-production-use"
os.environ["EXPOSE_AUTH_LINKS"] = "true"
os.environ["REQUIRE_EMAIL_VERIFICATION"] = "false"
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import ALL_ROUTERS  # noqa: E402
from auth.rate_limit import configure as configure_limiter  # noqa: E402
from db import crud  # noqa: E402
from db.config import database, ensure_indexes  # noqa: E402

PASSWORD = "LegalLens123!"


def purge() -> None:
    for repository in crud.ALL_REPOSITORIES.values():
        repository.delete({})


@pytest.fixture(scope="session", autouse=True)
def prepared_database():
    report = ensure_indexes()
    assert report["connected"], f"MongoDB unavailable: {report['errors'] or report}"
    purge()
    yield
    purge()
    database.close()


@pytest.fixture
def app():
    application = FastAPI()
    configure_limiter(application)
    for router in ALL_ROUTERS:
        application.include_router(router)
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def clean(prepared_database):
    purge()
    return True


def signup_and_token(client, email: str, full_name: str = "Test Advocate"):
    response = client.post("/api/auth/register",
                           json={"full_name": full_name, "email": email,
                                 "password": PASSWORD, "role": "Advocate"})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["token"], body["user"]["id"], body


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def account_a(clean, client):
    token, user_id, _ = signup_and_token(client, "advocate.a@example.com", "Advocate One")
    return {"token": token, "id": user_id, "email": "advocate.a@example.com",
            "password": PASSWORD}


@pytest.fixture
def account_b(clean, client):
    token, user_id, _ = signup_and_token(client, "advocate.b@example.com", "Advocate Two")
    return {"token": token, "id": user_id, "email": "advocate.b@example.com",
            "password": PASSWORD}
