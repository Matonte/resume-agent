"""Registration, login, and session for multi-user workspaces."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.auth.passwords import hash_password, verify_password
from app.auth.session_user import session_has_login, session_user_id
from app.config import settings
from app.storage.accounts import (
    User,
    get_profile,
    get_user_by_email,
    get_user_by_id,
    user_must_complete_onboarding,
)
from app.storage.db import get_conn

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESERVED_EMAILS = frozenset(
    {
        "workspace@local",
        "owner@local",
    }
)


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class ContributionsOptInBody(BaseModel):
    enabled: bool


def _public_user(u: User, *, authenticated: bool) -> dict[str, Any]:
    prof = None
    with get_conn() as conn:
        if u.active_profile_id:
            prof = get_profile(conn, u.active_profile_id)
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "active_profile_id": u.active_profile_id,
        "active_profile_name": prof.name if prof else None,
        "requires_onboarding": u.requires_onboarding,
        "onboarding_completed_at": (
            u.onboarding_completed_at.isoformat() if u.onboarding_completed_at else None
        ),
        "needs_onboarding": user_must_complete_onboarding(
            u, default_user_id=settings.default_user_id
        ),
        "contribute_learning_opt_in": bool(u.contribute_learning_opt_in),
        "authenticated": authenticated,
        "use_builtin_profile": bool(prof.use_builtin) if prof else True,
    }


@router.post("/register")
def register(request: Request, body: RegisterBody) -> Any:
    email = body.email.lower().strip()
    if email in RESERVED_EMAILS:
        raise HTTPException(
            status_code=400,
            detail="That email is reserved for the default workspace.",
        )
    from app.storage.accounts import create_user_with_profile

    try:
        with get_conn() as conn:
            uid, pid = create_user_with_profile(
                conn,
                email=email,
                password_hash=hash_password(body.password),
                display_name=body.display_name or email.split("@")[0],
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email already registered")

    request.session["user_id"] = uid
    request.session["profile_id"] = pid
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
    assert u is not None
    return {"ok": True, "user": _public_user(u, authenticated=True)}


@router.post("/login")
def login(request: Request, body: LoginBody) -> Any:
    with get_conn() as conn:
        u = get_user_by_email(conn, body.email.lower().strip())
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not u.password_hash:
        raise HTTPException(status_code=403, detail="This account cannot log in")
    request.session["user_id"] = u.id
    if u.active_profile_id:
        request.session["profile_id"] = u.active_profile_id
    with get_conn() as conn:
        fresh = get_user_by_id(conn, u.id)
    assert fresh is not None
    return {"ok": True, "user": _public_user(fresh, authenticated=True)}


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordBody) -> Any:
    """Start a password reset. Always returns the same message (no email oracle)."""
    from app.auth.password_reset import request_reset_for_email

    sent = False
    raw_token: Optional[str] = None
    with get_conn() as conn:
        sent, raw_token = request_reset_for_email(conn, str(body.email))
    payload: dict[str, Any] = {
        "ok": True,
        "message": (
            "If that email is registered and mail is configured, "
            "a reset link is on its way. Check your inbox."
        ),
        "email_configured": settings.email_configured,
        "email_sent": bool(sent),
    }
    if settings.expose_password_reset_token and raw_token:
        payload["dev_reset_token"] = raw_token
    return payload


@router.post("/reset-password")
def reset_password(request: Request, body: ResetPasswordBody) -> Any:
    from app.auth.password_reset import consume_password_reset_token

    with get_conn() as conn:
        uid = consume_password_reset_token(conn, body.token)
        if not uid:
            raise HTTPException(
                status_code=400,
                detail="This reset link is invalid or has expired. Request a new one.",
            )
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(body.password), uid),
        )
        conn.commit()
        u = get_user_by_id(conn, uid)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    request.session["user_id"] = u.id
    if u.active_profile_id:
        request.session["profile_id"] = u.active_profile_id
    return {"ok": True, "user": _public_user(u, authenticated=True)}


@router.post("/logout")
def logout(request: Request) -> Any:
    request.session.clear()
    return {"ok": True}


@router.patch("/me/contributions-opt-in")
def patch_contributions_opt_in(request: Request, body: ContributionsOptInBody) -> Any:
    if not session_has_login(request):
        raise HTTPException(
            status_code=400,
            detail="Sign in to change contribution preferences.",
        )
    uid = session_user_id(request)
    with get_conn() as conn:
        u_check = get_user_by_id(conn, uid)
        if u_check and u_check.email in RESERVED_EMAILS:
            raise HTTPException(
                status_code=400,
                detail="The default workspace cannot change contribution preferences.",
            )
        conn.execute(
            "UPDATE users SET contribute_learning_opt_in = ? WHERE id = ?",
            (1 if body.enabled else 0, uid),
        )
        conn.commit()
        u = get_user_by_id(conn, uid)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    return {"ok": True, "user": _public_user(u, authenticated=True)}


@router.get("/me")
def me(request: Request) -> Any:
    authenticated = session_has_login(request)
    uid = session_user_id(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    return _public_user(u, authenticated=authenticated)


__all__ = ["router"]
