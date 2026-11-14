"""Auth stack check: signup -> login -> refresh rotation/reuse -> reset -> logout."""

import os
import sys

os.environ["MONGO_DB"] = "ai_law_agent_authcheck"
os.environ["MONGO_ENABLED"] = "true"
os.environ["JWT_SECRET"] = "test-secret-value-for-local-check-only"
os.environ["EXPOSE_AUTH_LINKS"] = "true"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from db.config import database, ensure_indexes  # noqa: E402
from db import crud  # noqa: E402
from db.schemas import (  # noqa: E402
    ForgotPasswordRequest,
    LoginRequest,
    ProfileUpdateRequest,
    ResetPasswordRequest,
    SignupRequest,
)
from services import auth_service  # noqa: E402

FAILED = []


def check(label, condition, extra=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}{(' -> ' + str(extra)) if extra else ''}")
    if not condition:
        FAILED.append(label)


def main():
    ensure_indexes()
    for repo in crud.ALL_REPOSITORIES.values():
        repo.delete({})

    email = "zubar.authcheck@example.com"
    password = "LegalLens123"

    signup = auth_service.signup(
        SignupRequest(username="Zubar Ahmed", email=email.upper(), password=password, role="Advocate"),
        ip="127.0.0.1",
        user_agent="pytest",
    )
    check("signup returns access token", bool(signup.get("token")))
    check("signup returns refresh token", bool(signup.get("refresh_token")))
    check("signup normalises email to lowercase", signup["user"]["email"] == email)
    check("signup never returns password_hash", "password_hash" not in signup["user"])
    check("signup fills full_name from username", signup["user"]["full_name"] == "Zubar Ahmed")
    user_id = signup["user"]["id"]

    stored = crud.users.get(user_id)
    check("password stored as argon2id", stored["password_hash"].startswith("$argon2id$"),
          stored["password_hash"][:20])
    check("password hash != plaintext", password not in stored["password_hash"])
    check("session row created", crud.user_sessions.count({"user_id": user_id}) == 1)
    session_doc = crud.user_sessions.find({"user_id": user_id})[0]
    check("refresh token stored only as digest",
          session_doc["refresh_token_hash"] != signup["refresh_token"]
          and len(session_doc["refresh_token_hash"]) == 64)

    dup = None
    try:
        auth_service.signup(SignupRequest(full_name="Other", email=email, password=password))
    except HTTPException as exc:
        dup = exc
    check("duplicate email rejected with 409", dup is not None and dup.status_code == 409, dup)

    bad_login = None
    try:
        auth_service.login(LoginRequest(email=email, password="WrongPassword1"))
    except HTTPException as exc:
        bad_login = exc
    check("wrong password rejected 401", bad_login is not None and bad_login.status_code == 401)

    unknown_login = None
    try:
        auth_service.login(LoginRequest(email="nobody.here@example.com", password=password))
    except HTTPException as exc:
        unknown_login = exc
    check("unknown email rejected 401", unknown_login is not None and unknown_login.status_code == 401)

    login = auth_service.login(LoginRequest(email=email, password=password), ip="127.0.0.1")
    check("login returns tokens", bool(login["token"]) and bool(login["refresh_token"]))
    check("login marks last_login_at", crud.users.get(user_id).get("last_login_at") is not None)
    login_session = crud.user_sessions.find({"user_id": user_id, "revoked_at": None},
                                            sort=[("login_at", -1)])[0]

    from auth.tokens import decode_token  # noqa: E402

    claims = decode_token(login["token"], "access")
    check("access token subject is the real user id", str(claims["sub"]) == str(user_id))
    check("access token carries session id", bool(claims.get("sid")))

    refreshed = auth_service.refresh(login["refresh_token"], ip="127.0.0.1")
    check("refresh returns a new access token", refreshed["access_token"] != login["access_token"])
    check("refresh rotates the refresh token",
          refreshed["refresh_token"] != login["refresh_token"])
    check("old session marked revoked",
          crud.user_sessions.get(login_session["_id"])["revoked_reason"] == "rotated")

    reuse = None
    try:
        auth_service.refresh(login["refresh_token"], ip="127.0.0.1")
    except HTTPException as exc:
        reuse = exc
    check("refresh reuse rejected 401", reuse is not None and reuse.status_code == 401)
    family = login_session["family_id"]
    live = crud.user_sessions.count({"family_id": family, "revoked_at": None})
    check("reuse revokes the whole family", live == 0, f"live_in_family={live}")

    new_session = crud.user_sessions.find({"user_id": user_id}, sort=[("login_at", -1)])
    check("replacement session kept same family",
          new_session and new_session[0]["family_id"] == family)

    tampered = None
    try:
        auth_service.refresh(refreshed["refresh_token"] + "x", ip="127.0.0.1")
    except HTTPException as exc:
        tampered = exc
    check("tampered refresh rejected", tampered is not None and tampered.status_code == 401)

    wrong_type = None
    try:
        auth_service.refresh(refreshed["access_token"], ip="127.0.0.1")
    except HTTPException as exc:
        wrong_type = exc
    check("access token cannot be used as refresh", wrong_type is not None)

    sessions = auth_service.active_sessions(user_id)
    check("active sessions hide the digest",
          all("refresh_token_hash" not in row for row in sessions), len(sessions))

    reset = auth_service.request_password_reset(ForgotPasswordRequest(email=email))
    check("reset link returned for demo", reset.get("reset_link", "").startswith("http://"))
    ghost = auth_service.request_password_reset(ForgotPasswordRequest(email="ghost.user@example.com"))
    check("unknown email gets the same wording", ghost["detail"] == reset["detail"])
    check("unknown email stores no reset token",
          crud.users.count({"reset_token_hash": {"$ne": None}}) == 1)

    token = reset["reset_link"].split("token=")[-1]
    weak_reset = None
    try:
        auth_service.reset_password(ResetPasswordRequest(token=token, new_password="short"))
    except ValidationError as exc:
        weak_reset = exc
    check("weak reset password rejected by schema", isinstance(weak_reset, ValidationError),
          type(weak_reset).__name__)
    check("weak attempt left the reset token usable",
          crud.users.get(user_id).get("reset_token_hash") is not None)

    new_password = "NewLegal456"
    done = auth_service.reset_password(ResetPasswordRequest(token=token, new_password=new_password))
    check("reset revokes live sessions", done["revoked_sessions"] >= 1, done)
    relogin = auth_service.login(LoginRequest(email=email, password=new_password))
    check("login works with the new password", bool(relogin["token"]))
    check("old password no longer works", crud.users.get(user_id)["password_hash"] != stored["password_hash"])
    old_reset = None
    try:
        auth_service.reset_password(ResetPasswordRequest(token=token, new_password="Another789"))
    except HTTPException as exc:
        old_reset = exc
    check("reset token is single-use", old_reset is not None and old_reset.status_code == 400)

    changed = auth_service.change_password(user_id, new_password, "ThirdLegal789", ip="127.0.0.1")
    check("password change revokes sessions", changed["revoked_sessions"] >= 1, changed)
    wrong_current = None
    try:
        auth_service.change_password(user_id, "NotIt12345", "FourthLegal000")
    except HTTPException as exc:
        wrong_current = exc
    check("wrong current password rejected 400", wrong_current is not None
          and wrong_current.status_code == 400)

    profile = auth_service.update_profile(
        user_id, ProfileUpdateRequest(full_name="Zubar Ahmed Khan")
    )
    check("profile update persists", profile["full_name"] == "Zubar Ahmed Khan")
    empty_update = None
    try:
        auth_service.update_profile(user_id, ProfileUpdateRequest())
    except HTTPException as exc:
        empty_update = exc
    check("empty profile update rejected 400", empty_update is not None
          and empty_update.status_code == 400)

    fresh = auth_service.login(LoginRequest(email=email, password="ThirdLegal789"))
    out = auth_service.logout(user_id, fresh["refresh_token"])
    check("logout revokes the presented session", out["revoked_sessions"] == 1, out)
    after = auth_service.active_sessions(user_id)
    check("no active sessions remain", len(after) == 0, len(after))
    check("logout keeps the audit row", crud.user_sessions.count({"user_id": user_id}) >= 2)

    out_all = auth_service.logout_all(user_id)
    check("logout_all is idempotent", out_all["revoked_sessions"] == 0, out_all)

    logs = auth_service_activity(user_id)
    actions = {row["action"] for row in logs}
    check("activity log covers the lifecycle",
          {"account.signup", "auth.login", "auth.token_refreshed", "auth.logout"} <= actions,
          sorted(actions))
    check("activity log stores no secrets",
          all("password_hash" not in row and "token" not in str(row.get("detail", "")) for row in logs))

    print()
    print(f"database: {database.db().name}")
    for repo in crud.ALL_REPOSITORIES.values():
        repo.delete({})
    print("cleanup: test collections emptied")
    if FAILED:
        print(f"\n{len(FAILED)} CHECKS FAILED: {FAILED}")
        return 1
    print("\nALL AUTH CHECKS PASSED")
    return 0


def auth_service_activity(user_id):
    from services import activity_service  # noqa: E402

    return crud.activity_logs.find({"user_id": user_id})


def verification_flow():
    """Second pass with email verification turned on (signup must not hand out tokens)."""
    from auth.config import AUTH_SETTINGS

    print()
    print("--- email verification required ---")
    # The settings object is a frozen dataclass shared by every auth module.
    object.__setattr__(AUTH_SETTINGS, "require_email_verification", True)
    try:
        email = "verified.user@example.com"
        result = auth_service.signup(
            SignupRequest(full_name="Verified User", email=email, password="LegalLens123")
        )
        check("verification signup returns no token", not result.get("token"))
        check("verification signup flags the requirement", result.get("verification_required"))
        check("verification signup returns a link", result.get("verification_link", "").startswith("http://"))
        account = crud.users.find_one({"email": email})
        check("account starts pending", account["status"] == "pending", account["status"])
        check("verification token stored as digest",
              len(account.get("verification_token_hash") or "") == 64)

        blocked = None
        try:
            auth_service.login(LoginRequest(email=email, password="LegalLens123"))
        except HTTPException as exc:
            blocked = exc
        check("login before verification rejected 403",
              blocked is not None and blocked.status_code == 403, blocked)

        link = result["verification_link"]
        raw = link.split("token=")[-1]
        bad = None
        try:
            auth_service.verify_email("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        except HTTPException as exc:
            bad = exc
        check("unknown verification token rejected", bad is not None and bad.status_code == 400)

        verified = auth_service.verify_email(raw)
        check("verification activates the account", verified["user"]["status"] == "active",
              verified["user"]["status"])
        check("verification clears the token",
              crud.users.find_one({"email": email}).get("verification_token_hash") is None)
        replay = None
        try:
            auth_service.verify_email(raw)
        except HTTPException as exc:
            replay = exc
        check("verification link is single-use", replay is not None and replay.status_code == 400)

        after = auth_service.login(LoginRequest(email=email, password="LegalLens123"))
        check("login works once verified", bool(after["token"]))
    finally:
        object.__setattr__(AUTH_SETTINGS, "require_email_verification", False)
        for repo in crud.ALL_REPOSITORIES.values():
            repo.delete({})


if __name__ == "__main__":
    code = main()
    if code == 0:
        verification_flow()
    raise SystemExit(code)
