"""HTTP client for flask_sample Meeting Advisor ``POST /api/v1/advise``."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def post_meeting_advise(
    *,
    subject_name: str,
    notes: str | None,
    source_hint: str = "",
    context: Dict[str, Any],
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """POST merged K + HOSS + LLM advice. Returns ``(json, error_message)``."""
    url = (settings.meeting_advisor_advise_url or "").strip()
    if not url:
        return None, "MEETING_ADVISOR_URL is not set."

    payload: Dict[str, Any] = {
        "subject_name": (subject_name or "").strip(),
        "source_hint": (source_hint or "").strip(),
        "context": context,
    }
    if notes and notes.strip():
        payload["notes"] = notes.strip()

    try:
        if client is not None:
            r = client.post(url, json=payload)
        else:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as c:
                r = c.post(url, json=payload)
        if r.status_code != 200:
            try:
                body = r.json()
                msg = body.get("error") or body.get("detail") or r.text
            except ValueError:
                msg = r.text
            return None, f"Meeting advisor HTTP {r.status_code}: {msg}"

        data = r.json()
        return (data if isinstance(data, dict) else None), None
    except Exception as exc:
        logger.exception("meeting_advisor POST failed")
        return None, f"Meeting advisor request failed: {exc!s}"


__all__ = ["post_meeting_advise"]
