"""Registration, login, and session for multi-user workspaces."""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.auth.passwords import hash_password, verify_password
from app.config import settings
from app.storage.accounts import (
    User,
    get_profile,
    get_user_by_email,
    get_user_by_id,
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


def _public_user(u: User) -> dict[str, Any]:
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
    return {"ok": True, "user": _public_user(u)}


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
    return {"ok": True, "user": _public_user(fresh)}


@router.post("/logout")
def logout(request: Request) -> Any:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> Any:
    uid = int(request.session.get("user_id", settings.default_user_id))
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    return _public_user(u)


__all__ = ["router"]
