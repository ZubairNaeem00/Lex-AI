"""Password recovery over HTTP, plus the email provider wiring.

The suite never sends real mail: RESEND_API_KEY is cleared in conftest and the
Resend call is mocked here. Covers hashed single-use tokens, the 20-minute
expiry, refusal of expired/replaced links, and signing every device out.
"""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import timedelta

from conftest import PASSWORD, auth_header

from auth.config import AUTH_SETTINGS
from db import crud
from db.crud import utc_now
from services import email_service

NEW_PASSWORD = "RecoveredPass9!"


def request_link(client, email: str) -> dict:
    response = client.post("/api/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()


def token_from(body: dict) -> str:
    return body["reset_link"].split("token=")[-1]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def capture_resend(monkeypatch, payload=None, error=None):
    """Replace urlopen and record every outgoing request."""
    sent = []

    def fake_urlopen(request, timeout=None):
        sent.append({
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "body": json.loads(request.data.decode("utf-8")),
            "timeout": timeout,
        })
        if error is not None:
            raise error
        return FakeResponse(payload or {"id": "email-id-123"})

    monkeypatch.setattr(email_service.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_not_real")
    monkeypatch.setattr(email_service, "OUTBOX", [])
    return sent


# ── Tokens ────────────────────────────────────────────────────────────────

def test_reset_token_is_hashed_and_expires_in_twenty_minutes(client, account_a):
    body = request_link(client, account_a["email"])
    raw = token_from(body)

    stored = crud.users.get(account_a["id"])
    assert stored["reset_token_hash"] != raw
    assert raw not in json.dumps(stored, default=str)
    assert AUTH_SETTINGS.reset_ttl_minutes == 20

    remaining = stored["reset_expires_at"] - utc_now()
    assert timedelta(minutes=19) < remaining <= timedelta(minutes=20)


def test_expired_reset_link_is_refused(client, account_a):
    raw = token_from(request_link(client, account_a["email"]))
    crud.users.set_by_id(account_a["id"], {"reset_expires_at": utc_now() - timedelta(minutes=1)})

    response = client.post("/api/auth/reset-password",
                           json={"token": raw, "new_password": NEW_PASSWORD})
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]
    assert crud.users.get(account_a["id"])["reset_token_hash"] is not None


def test_a_new_request_replaces_the_previous_link(client, account_a):
    first = token_from(request_link(client, account_a["email"]))
    second = token_from(request_link(client, account_a["email"]))
    assert first != second

    stale = client.post("/api/auth/reset-password",
                        json={"token": first, "new_password": NEW_PASSWORD})
    assert stale.status_code == 400

    fresh = client.post("/api/auth/reset-password",
                        json={"token": second, "new_password": NEW_PASSWORD})
    assert fresh.status_code == 200


def test_reset_signs_out_every_device(client, account_a):
    devices = [
        client.post("/api/auth/login",
                    json={"email": account_a["email"], "password": PASSWORD}).json()
        for _ in range(2)
    ]
    raw = token_from(request_link(client, account_a["email"]))

    reset = client.post("/api/auth/reset-password",
                        json={"token": raw, "new_password": NEW_PASSWORD})
    assert reset.status_code == 200
    assert reset.json()["revoked_sessions"] >= 2
    assert crud.user_sessions.count({"user_id": account_a["id"], "revoked_at": None}) == 0

    for session in devices:
        assert client.get("/api/users/me", headers=auth_header(session["token"])).status_code == 401
        assert client.post("/api/auth/refresh",
                           json={"refresh_token": session["refresh_token"]}).status_code == 401

    assert crud.users.count({"reset_token_hash": {"$ne": None}}) == 0
    stored = crud.users.get(account_a["id"])
    assert stored["password_hash"].startswith("$argon2id$")
    assert NEW_PASSWORD not in json.dumps(stored, default=str)

    login = client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": NEW_PASSWORD})
    assert login.status_code == 200


def test_reset_rejects_a_weak_new_password(client, account_a):
    raw = token_from(request_link(client, account_a["email"]))
    response = client.post("/api/auth/reset-password",
                           json={"token": raw, "new_password": "NoSpecial123"})
    assert response.status_code == 422
    assert "special character" in response.text

    still_works = client.post("/api/auth/login",
                              json={"email": account_a["email"], "password": PASSWORD})
    assert still_works.status_code == 200


# ── Delivery ──────────────────────────────────────────────────────────────

def test_resend_uses_the_project_sender_and_keeps_the_key_server_side(monkeypatch):
    sent = capture_resend(monkeypatch)
    link = "http://localhost:3000/reset-password?token=abc123"

    result = email_service.send_email("counsel@example.com", "Reset your password", "Body text", link)

    assert result["mode"] == "resend"
    assert result["provider_id"] == "email-id-123"
    assert len(sent) == 1
    assert sent[0]["url"] == "https://api.resend.com/emails"
    assert sent[0]["body"]["from"] == "AI Law Agent <onboarding@resend.dev>"
    assert sent[0]["body"]["to"] == ["counsel@example.com"]
    assert link in sent[0]["body"]["text"]
    assert sent[0]["headers"]["Authorization"] == "Bearer re_test_key_not_real"
    assert "re_test_key_not_real" not in json.dumps(result)
    assert "re_test_key_not_real" not in json.dumps(email_service.OUTBOX)


def test_resend_refusal_is_reported_and_does_not_break_the_request(monkeypatch):
    refusal = urllib.error.HTTPError(
        "https://api.resend.com/emails", 403, "Forbidden", {},
        io.BytesIO(b'{"message":"You can only send testing emails to your own email address."}'),
    )
    sent = capture_resend(monkeypatch, error=refusal)

    result = email_service.send_email("someone.else@example.com", "Reset", "Body", "http://link")

    assert len(sent) == 1
    assert result["mode"] == "failed"
    assert "403" in result["error"]


def test_without_a_provider_the_message_is_logged(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setattr(email_service, "OUTBOX", [])

    result = email_service.send_email("counsel@example.com", "Reset", "Body", "http://link")

    assert result["mode"] == "log"
    assert email_service.OUTBOX[-1]["link"] == "http://link"


def test_invalid_address_is_rejected_before_sending(monkeypatch):
    sent = capture_resend(monkeypatch)

    result = email_service.send_email("not-an-address", "Reset", "Body")

    assert result["mode"] == "rejected"
    assert sent == []
    assert email_service.OUTBOX == []


def test_forgot_password_sends_the_reset_link_through_resend(client, account_a, monkeypatch):
    sent = capture_resend(monkeypatch)

    body = request_link(client, account_a["email"])

    assert body["ok"] is True
    assert body["detail"] == "If that email is registered, a reset link has been sent."
    assert len(sent) == 1
    assert sent[0]["body"]["to"] == [account_a["email"]]
    assert sent[0]["body"]["from"] == "AI Law Agent <onboarding@resend.dev>"
    assert "/reset-password?token=" in sent[0]["body"]["text"]
    assert "20 minutes" in sent[0]["body"]["text"]
    assert token_from(body) in sent[0]["body"]["text"]


def test_unknown_address_sends_nothing_but_answers_the_same(client, clean, monkeypatch):
    sent = capture_resend(monkeypatch)

    body = request_link(client, "ghost@example.com")

    assert body["detail"] == "If that email is registered, a reset link has been sent."
    assert "reset_link" not in body
    assert sent == []