"""Redirect new accounts to /onboarding until they finish setup."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.config import settings
from app.storage.accounts import get_user_by_id, user_must_complete_onboarding
from app.storage.db import get_conn


def _allow_without_onboarding(path: str) -> bool:
    if path.startswith("/onboarding"):
        return True
    if path.startswith("/api/onboarding"):
        return True
    if path.startswith("/account"):
        return True
    if path.startswith("/api/auth"):
        return True
    if path.startswith("/static") or path.startswith("/api/static"):
        return True
    if path in ("/docs", "/openapi.json", "/redoc"):
        return True
    if path.startswith("/docs/"):
        return True
    return False


def _should_redirect_away(path: str) -> bool:
    if path == "/" or path == "":
        return True
    if path.startswith("/tailor"):
        return True
    if path.startswith("/jobs/"):
        return True
    if path.startswith("/manual-tailor"):
        return True
    return False


def _wants_html_navigation(accept: str) -> bool:
    """Browsers and TestClient often send ``*/*`` without ``text/html``."""
    if not accept or "*/*" in accept:
        return True
    return "text/html" in accept


class OnboardingGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method != "GET":
            return await call_next(request)
        path = request.url.path
        if _allow_without_onboarding(path):
            return await call_next(request)
        uid = int(request.session.get("user_id", settings.default_user_id))
        with get_conn() as conn:
            u = get_user_by_id(conn, uid)
        if not u or not user_must_complete_onboarding(
            u, default_user_id=settings.default_user_id
        ):
            return await call_next(request)
        if not _should_redirect_away(path):
            return await call_next(request)
        accept = request.headers.get("accept") or ""
        if not _wants_html_navigation(accept):
            return await call_next(request)
        return RedirectResponse(url="/onboarding", status_code=307)


__all__ = ["OnboardingGateMiddleware"]
