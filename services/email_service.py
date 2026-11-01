"""Email delivery for verification and password-reset links.

With no SMTP configuration the message is recorded in `OUTBOX` and printed, which is
what the local demo needs; the tokens are never stored in plain text in MongoDB.
"""

from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

OUTBOX: List[Dict[str, Any]] = []
MAX_OUTBOX = 200


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER"))


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

    if _smtp_configured():
        try:
            outgoing = EmailMessage()
            outgoing["From"] = os.getenv("SMTP_FROM", os.environ["SMTP_USER"])
            outgoing["To"] = to
            outgoing["Subject"] = subject
            outgoing.set_content(f"{body}\n\n{link}" if link else body)
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as server:
                server.starttls()
                server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                server.send_message(outgoing)
            message["mode"] = "smtp"
        except Exception as exc:  # pragma: no cover - network dependent
            message["mode"] = "failed"
            message["error"] = f"{type(exc).__name__}: {exc}"

    if message["mode"] != "rejected":
        OUTBOX.append(message)
        del OUTBOX[:-MAX_OUTBOX]
        print(f"[Email] {message['mode']} to={to} subject={subject!r} link={link}", flush=True)
    return message


def public_link(path: str, token: str) -> str:
    base = os.getenv("PUBLIC_APP_URL", "http://localhost:3000").rstrip("/")
    return f"{base}{path}?token={token}"


def show_links_enabled() -> bool:
    return os.getenv("EXPOSE_AUTH_LINKS", "true").strip().lower() in {"1", "true", "yes", "on"}
