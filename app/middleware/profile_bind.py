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
        uid = int(
            request.session.get("user_id", settings.default_user_id)
        )
        prof_dir = None
        with get_conn() as conn:
            u = get_user_by_id(conn, uid)
            if u and u.active_profile_id:
                p = get_profile(conn, u.active_profile_id)
                if p:
                    prof_dir = p.effective_candidate_dir()
        token = push_candidate_dir(prof_dir)
        try:
            return await call_next(request)
        finally:
            reset_candidate_token(token)
