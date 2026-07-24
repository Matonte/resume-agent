"""Password-reset tokens and email flow."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

TOKEN_TTL = timedelta(hours=1)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_password_reset_token(conn: Any, user_id: int) -> str:
    """Invalidate prior tokens for the user and create a fresh one. Returns raw token."""
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    now = datetime.now(timezone.utc)
    expires = now + TOKEN_TTL
    conn.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
        (now.isoformat(), user_id),
    )
    conn.execute(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, token_hash, expires.isoformat(), now.isoformat()),
    )
    conn.commit()
    return raw


def consume_password_reset_token(conn: Any, raw_token: str) -> Optional[int]:
    """Validate + mark used. Returns user_id or None."""
    token = (raw_token or "").strip()
    if not token or len(token) < 20:
        return None
    token_hash = _hash_token(token)
    row = conn.execute(
        """
        SELECT id, user_id, expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (token_hash,),
    ).fetchone()
    if not row:
        return None
    if isinstance(row, dict) or (hasattr(row, "keys") and "user_id" in row.keys()):
        tid = int(row["id"])
        uid = int(row["user_id"])
        expires_at = row["expires_at"]
        used_at = row["used_at"]
    else:
        tid, uid, expires_at, used_at = int(row[0]), int(row[1]), row[2], row[3]
    if used_at:
        return None
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if exp < datetime.now(timezone.utc):
        return None
    conn.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), tid),
    )
    conn.commit()
    return uid


def reset_link_for_token(raw_token: str) -> str:
    base = (settings.dashboard_base_url or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/account?reset={raw_token}"


def send_password_reset_email(to_email: str, raw_token: str) -> bool:
    """Send reset link via Gmail SMTP. Returns True if sent."""
    from app.notify.email import send_simple_email

    link = reset_link_for_token(raw_token)
    subject = "Reset your Resume Agent password"
    text = (
        "We received a request to reset your Resume Agent password.\n\n"
        f"Open this link (expires in 1 hour):\n{link}\n\n"
        "If you did not request this, you can ignore this email.\n"
    )
    html = (
        "<p>We received a request to reset your Resume Agent password.</p>"
        f'<p><a href="{link}">Choose a new password</a> '
        "(this link expires in 1 hour).</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
    )
    return send_simple_email(to_email, subject, text_body=text, html_body=html)


def request_reset_for_email(conn: Any, email: str) -> Tuple[bool, Optional[str]]:
    """Create a token for the email if the account exists.

    Returns ``(email_sent, raw_token)``. ``raw_token`` is only for tests / debug
    exposure; production API responses should not include it by default.
    """
    from app.storage.accounts import get_user_by_email

    u = get_user_by_email(conn, email.lower().strip())
    if not u or not u.password_hash:
        return False, None
    raw = create_password_reset_token(conn, u.id)
    sent = send_password_reset_email(u.email, raw)
    if not sent:
        logger.warning("Password reset email not sent for user_id=%s (SMTP not configured?)", u.id)
    return sent, raw


__all__ = [
    "TOKEN_TTL",
    "consume_password_reset_token",
    "create_password_reset_token",
    "request_reset_for_email",
    "reset_link_for_token",
    "send_password_reset_email",
]
