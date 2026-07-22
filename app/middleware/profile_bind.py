"""Bind per-request candidate `data/` from the signed-in user's profile."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.services.data_context import push_candidate_dir, reset_candidate_token
from app.storage.accounts import get_profile, get_user_by_id
from app.storage.db import get_conn


class ProfileDataMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Health/docs must stay up even if MySQL is mid-migrate or unreachable.
        path = request.url.path
        if path in ("/api/health", "/docs", "/openapi.json", "/redoc") or path.startswith(
            "/docs/"
        ):
            return await call_next(request)

        uid = int(
            request.session.get("user_id", settings.default_user_id)
        )
        prof_dir = None
        try:
            with get_conn() as conn:
                u = get_user_by_id(conn, uid)
                if u and u.active_profile_id:
                    p = get_profile(conn, u.active_profile_id)
                    if p:
                        prof_dir = p.effective_candidate_dir()
        except Exception:
            # Fall through with default candidate dir rather than 500 every page.
            prof_dir = None
        token = push_candidate_dir(prof_dir)
        try:
            return await call_next(request)
        finally:
            reset_candidate_token(token)
