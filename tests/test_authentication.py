"""Authentication and authorization over HTTP.

Covers: registration validation, duplicate email, login, protected routes, token
rotation and reuse detection, password reset, profile guards, and rate limiting.
"""

from __future__ import annotations

from conftest import PASSWORD, auth_header, signup_and_token

from db import crud


def test_register_creates_account_with_hashed_password(client, clean):
    token, user_id, body = signup_and_token(client, "new.advocate@example.com")

    assert token
    assert body["user"]["email"] == "new.advocate@example.com"
    assert "password" not in body["user"] and "password_hash" not in body["user"]

    stored = crud.users.get(user_id)
    assert stored["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in stored["password_hash"]


def test_register_rejects_weak_password_and_bad_email(client, clean):
    weak = client.post("/api/auth/register", json={
        "full_name": "Weak Person", "email": "weak@example.com", "password": "short"})
    assert weak.status_code == 422

    no_digit = client.post("/api/auth/register", json={
        "full_name": "Weak Person", "email": "weak2@example.com", "password": "lettersonly"})
    assert no_digit.status_code == 422

    bad_email = client.post("/api/auth/register", json={
        "full_name": "Bad Email", "email": "not-an-email", "password": PASSWORD})
    assert bad_email.status_code == 422


def test_register_rejects_unknown_extra_field(client, clean):
    response = client.post("/api/auth/register", json={
        "full_name": "Extra", "email": "extra@example.com", "password": PASSWORD,
        "role": "Advocate", "user_id": "000000000000000000000001"})
    assert response.status_code == 422


def test_duplicate_email_is_rejected(client, account_a):
    second = client.post("/api/auth/register", json={
        "full_name": "Impostor", "email": account_a["email"], "password": PASSWORD})
    assert second.status_code == 409


def test_login_returns_token_pair_and_records_activity(client, account_a):
    response = client.post("/api/auth/login",
                           json={"email": account_a["email"], "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token"] and body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"

    actions = {row["action"] for row in crud.activity_logs.find({})}
    assert {"account.signup", "auth.login"} <= actions


def test_login_rejects_wrong_password_and_unknown_email(client, account_a):
    wrong = client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": "WrongPassword1"})
    assert wrong.status_code == 401

    unknown = client.post("/api/auth/login",
                          json={"email": "nobody@example.com", "password": PASSWORD})
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_protected_routes_require_a_valid_token(client, account_a):
    assert client.get("/api/users/me").status_code == 401
    assert client.get("/api/cases").status_code == 401

    garbage = client.get("/api/users/me", headers=auth_header("not.a.jwt"))
    assert garbage.status_code == 401

    good = client.get("/api/users/me", headers=auth_header(account_a["token"]))
    assert good.status_code == 200
    assert good.json()["email"] == account_a["email"]


def test_access_token_cannot_be_used_as_refresh(client, account_a):
    response = client.post("/api/auth/refresh", json={"refresh_token": account_a["token"]})
    assert response.status_code == 401


def test_refresh_rotates_and_reuse_revokes_the_family(client, account_a):
    session_row = crud.user_sessions.find_one({"user_id": account_a["id"]})
    login = client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": PASSWORD})
    refresh_token = login.json()["refresh_token"]

    rotated = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200
    new_tokens = rotated.json()
    assert new_tokens["refresh_token"] != refresh_token
    assert new_tokens["access_token"] != login.json()["access_token"]

    reuse = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401

    family = session_row["family_id"]
    live = crud.user_sessions.count({"family_id": family, "revoked_at": None})
    assert live == 0, "reuse must revoke every session in the family"


def test_logout_revokes_only_the_presented_session(client, account_a):
    other = client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": PASSWORD})
    mine = client.post("/api/auth/login",
                       json={"email": account_a["email"], "password": PASSWORD})

    response = client.post("/api/auth/logout",
                           headers=auth_header(mine.json()["token"]),
                           json={"refresh_token": mine.json()["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["revoked_sessions"] == 1

    assert client.get("/api/users/me", headers=auth_header(other.json()["token"])).status_code == 200


def test_expired_or_revoked_access_token_is_refused(client, account_a):
    login = client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": PASSWORD})
    token = login.json()["token"]
    refresh_token = login.json()["refresh_token"]

    client.post("/api/auth/logout-all", headers=auth_header(token), json={})
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh_token}).status_code == 401


def test_password_reset_flow(client, account_a):
    forgot = client.post("/api/auth/forgot-password", json={"email": account_a["email"]})
    assert forgot.status_code == 200
    link = forgot.json()["reset_link"]
    token = link.split("token=")[-1]

    reset = client.post("/api/auth/reset-password",
                        json={"token": token, "new_password": "RotatedPass9"})
    assert reset.status_code == 200
    assert reset.json()["revoked_sessions"] >= 1

    old = client.post("/api/auth/login",
                      json={"email": account_a["email"], "password": PASSWORD})
    assert old.status_code == 401
    new = client.post("/api/auth/login",
                      json={"email": account_a["email"], "password": "RotatedPass9"})
    assert new.status_code == 200

    replay = client.post("/api/auth/reset-password",
                         json={"token": token, "new_password": "ThirdPass123"})
    assert replay.status_code == 400


def test_password_reset_does_not_reveal_accounts(client, account_a):
    known = client.post("/api/auth/forgot-password", json={"email": account_a["email"]})
    unknown = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert known.json()["detail"] == unknown.json()["detail"]
    assert "reset_link" not in unknown.json()
    assert crud.users.count({"reset_token_hash": {"$ne": None}}) == 1


def test_change_password_requires_the_current_one(client, account_a):
    login = client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": PASSWORD})
    headers = auth_header(login.json()["token"])

    bad = client.post("/api/users/me/password", headers=headers,
                      json={"current_password": "NotIt12345", "new_password": "FreshPass123"})
    assert bad.status_code == 400

    good = client.post("/api/users/me/password", headers=headers,
                       json={"current_password": PASSWORD, "new_password": "FreshPass123"})
    assert good.status_code == 200
    assert good.json()["revoked_sessions"] >= 1
    assert client.get("/api/users/me", headers=headers).status_code == 401


def test_session_listing_hides_token_digests(client, account_a):
    response = client.get("/api/users/me/sessions", headers=auth_header(account_a["token"]))
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all("refresh_token_hash" not in row for row in items)

    revoked = client.delete(f"/api/users/me/sessions/{items[0]['id']}",
                            headers=auth_header(account_a["token"]))
    assert revoked.status_code == 200
    assert revoked.json()["ok"] is True


def test_profile_update_and_validation(client, account_a):
    headers = auth_header(account_a["token"])
    updated = client.patch("/api/users/me", headers=headers,
                           json={"full_name": "Updated Name",
                                 "profile": {"jurisdiction": "Lahore High Court"}})
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Updated Name"
    assert updated.json()["profile"]["jurisdiction"] == "Lahore High Court"

    empty = client.patch("/api/users/me", headers=headers, json={})
    assert empty.status_code == 400


def test_rate_limit_blocks_repeated_login(app, client, account_a):
    from auth.config import AUTH_SETTINGS
    from auth.rate_limit import limiter

    limiter.enabled = True
    object.__setattr__(AUTH_SETTINGS, "rate_limit_enabled", True)
    try:
        statuses = [
            client.post("/api/auth/login",
                        json={"email": account_a["email"], "password": "WrongPass123"}).status_code
            for _ in range(15)
        ]
    finally:
        limiter.enabled = False
        object.__setattr__(AUTH_SETTINGS, "rate_limit_enabled", False)

    assert 429 in statuses, statuses
    limiter.reset()


def test_auth_status_reports_configuration(client, clean):
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ai_law_agent_pytest"
    assert body["database_connected"] is True
    assert body["require_email_verification"] is False
