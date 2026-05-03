"""Reject selected API calls until the account finishes /onboarding."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import settings
from app.storage.accounts import get_user_by_id, user_must_complete_onboarding
from app.storage.db import get_conn


def raise_if_onboarding_incomplete(request: Request) -> None:
    """403 when a real user must finish onboarding; no-op for default workspace."""
    uid = int(request.session.get("user_id", settings.default_user_id))
    if uid == settings.default_user_id:
        return
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
    if u and user_must_complete_onboarding(
        u, default_user_id=settings.default_user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Finish account setup first at /onboarding (résumé + job samples).",
        )


__all__ = ["raise_if_onboarding_incomplete"]
