"""Require a signed-in session before using product pages and APIs."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.auth.session_user import session_has_login
from app.config import settings


def _allow_anonymous(path: str) -> bool:
    if path.startswith("/account"):
        return True
    if path.startswith("/api/auth"):
        return True
    if path.startswith("/static") or path.startswith("/api/static"):
        return True
    if path in ("/docs", "/openapi.json", "/redoc", "/favicon.ico"):
        return True
    if path.startswith("/docs/"):
        return True
    if path == "/api/health":
        return True
    return False


def _wants_html_navigation(accept: str, path: str) -> bool:
    if path.startswith("/api/"):
        return False
    if not accept or "*/*" in accept:
        return True
    return "text/html" in accept


class LoginGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.require_login:
            return await call_next(request)
        path = request.url.path
        if _allow_anonymous(path):
            return await call_next(request)
        if session_has_login(request):
            return await call_next(request)

        accept = request.headers.get("accept") or ""
        if _wants_html_navigation(accept, path) and request.method in ("GET", "HEAD"):
            return RedirectResponse(url="/account", status_code=307)
        return JSONResponse(
            {"detail": "Log in to continue."},
            status_code=401,
        )


__all__ = ["LoginGateMiddleware"]
