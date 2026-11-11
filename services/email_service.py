"""Email delivery for verification and password-reset links.

Provider order: Resend (RESEND_API_KEY), then SMTP, then a local log. The log mode
records the message in `OUTBOX` and prints it, which is what the demo needs when no
provider is configured; tokens are never stored in plain text in MongoDB.

Resend only delivers to the address that owns the account until a domain is
verified, so a refused send is reported as `failed` rather than raised — the
request stays generic and, with EXPOSE_AUTH_LINKS on, the link is still returned
to the caller for local testing.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, List

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

OUTBOX: List[Dict[str, Any]] = []
MAX_OUTBOX = 200

RESEND_ENDPOINT = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS = 15
DEFAULT_SENDER = "AI Law Agent <onboarding@resend.dev>"


def _resend_key() -> str:
    return os.getenv("RESEND_API_KEY", "").strip()


def _sender() -> str:
    return os.getenv("EMAIL_FROM", "").strip() or DEFAULT_SENDER


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER"))


def _send_via_resend(to: str, subject: str, text: str) -> Dict[str, Any]:
    payload = json.dumps({"from": _sender(), "to": [to], "subject": subject, "text": text}).encode("utf-8")
    outgoing = urllib.request.Request(
        RESEND_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {_resend_key()}",
            "Content-Type": "application/json",
            "User-Agent": "ai-law-agent/1.0",
        },
    )
    try:
        with urllib.request.urlopen(outgoing, timeout=RESEND_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        return {"mode": "resend", "provider_id": result.get("id", "")}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {"mode": "failed", "error": f"Resend {exc.code}: {detail}"}
    except Exception as exc:
        return {"mode": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _send_via_smtp(to: str, subject: str, text: str) -> Dict[str, Any]:
    outgoing = EmailMessage()
    outgoing["From"] = os.getenv("SMTP_FROM", os.environ["SMTP_USER"])
    outgoing["To"] = to
    outgoing["Subject"] = subject
    outgoing.set_content(text)
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as server:
            server.starttls()
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            server.send_message(outgoing)
        return {"mode": "smtp"}
    except Exception as exc:  # pragma: no cover - network dependent
        return {"mode": "failed", "error": f"{type(exc).__name__}: {exc}"}


def send_email(to: str, subject: str, body: str, link: str = "") -> Dict[str, Any]:
    message: Dict[str, Any] = {
        "to": to,
        "subject": subject,
        "body": body,
        "link": link,
        "mode": "log",
    }
    if not EMAIL_REGEX.match(to or ""):
        message["mode"] = "rejected"
        return message

    text = f"{body}\n\n{link}" if link else body
    if _resend_key():
        message.update(_send_via_resend(to, subject, text))
    elif _smtp_configured():
        message.update(_send_via_smtp(to, subject, text))

    OUTBOX.append(message)
    del OUTBOX[:-MAX_OUTBOX]
    print(f"[Email] {message['mode']} to={to} subject={subject!r} link={link}", flush=True)
    if message.get("error"):
        print(f"[Email] {message['error']}", flush=True)
    return message


def public_link(path: str, token: str) -> str:
    base = os.getenv("PUBLIC_APP_URL", "http://localhost:3000").rstrip("/")
    return f"{base}{path}?token={token}"


def show_links_enabled() -> bool:
    return os.getenv("EXPOSE_AUTH_LINKS", "true").strip().lower() in {"1", "true", "yes", "on"}