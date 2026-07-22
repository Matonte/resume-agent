"""Session helpers: anonymous default workspace vs signed-in account."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import settings


def session_has_login(request: Request) -> bool:
    """True only after /api/auth/login or /register (user_id stored in session)."""
    return "user_id" in request.session


def session_user_id(request: Request) -> int:
    """Active user id: signed-in session, else DEFAULT_USER_ID (anonymous)."""
    if session_has_login(request):
        return int(request.session["user_id"])
    return int(settings.default_user_id)


def require_authenticated_user_id(request: Request) -> int:
    """Require a real login; anonymous DEFAULT_USER_ID binding is not enough."""
    if not session_has_login(request):
        raise HTTPException(
            status_code=403,
            detail="Log in with a registered account to continue.",
        )
    return int(request.session["user_id"])


__all__ = [
    "require_authenticated_user_id",
    "session_has_login",
    "session_user_id",
]
