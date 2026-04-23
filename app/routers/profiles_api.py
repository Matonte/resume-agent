"""Resume profile CRUD (swappable candidate JSON packs)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.storage.accounts import (
    create_extra_profile,
    get_profile_for_user,
    list_profiles,
    set_active_profile,
    update_profile_candidate,
)
from app.storage.db import get_conn

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class CreateProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class UpdateCandidateBody(BaseModel):
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None


def _uid(request: Request) -> int:
    return int(request.session.get("user_id", settings.default_user_id))


@router.get("")
def list_profiles_api(request: Request) -> Any:
    uid = _uid(request)
    with get_conn() as conn:
        profs = list_profiles(conn, uid)
    return {
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "use_builtin": p.use_builtin,
                "candidate_name": p.candidate_name,
                "candidate_email": p.candidate_email,
            }
            for p in profs
        ]
    }


@router.post("")
def create_profile(request: Request, body: CreateProfileBody) -> Any:
    uid = _uid(request)
    with get_conn() as conn:
        p = create_extra_profile(conn, uid, body.name)
    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "use_builtin": p.use_builtin,
    }


@router.post("/{profile_id}/activate")
def activate(request: Request, profile_id: int) -> Any:
    uid = _uid(request)
    with get_conn() as conn:
        set_active_profile(conn, uid, profile_id)
    request.session["profile_id"] = profile_id
    with get_conn() as conn:
        p = get_profile_for_user(conn, uid, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    return {"ok": True, "active_profile_id": profile_id}


@router.patch("/{profile_id}/candidate")
def patch_candidate(
    request: Request, profile_id: int, body: UpdateCandidateBody
) -> Any:
    uid = _uid(request)
    kwargs = {}
    if body.candidate_name is not None:
        kwargs["candidate_name"] = body.candidate_name
    if body.candidate_email is not None:
        kwargs["candidate_email"] = body.candidate_email
    if not kwargs:
        raise HTTPException(status_code=400, detail="no fields to update")
    with get_conn() as conn:
        update_profile_candidate(conn, uid, profile_id, **kwargs)
        p = get_profile_for_user(conn, uid, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    return {
        "id": p.id,
        "candidate_name": p.candidate_name,
        "candidate_email": p.candidate_email,
    }


__all__ = ["router"]
