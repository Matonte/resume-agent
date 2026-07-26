"""Resume profile CRUD (swappable candidate JSON packs) + post-onboarding uploads."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.services.candidate_profile_io import (
    load_profile_truth,
    profile_review_payload,
    truth_path,
)
from app.services.evidence_schema import normalize_truth_model
from app.services.onboarding_bootstrap import (
    load_resume_texts_for_profile,
    merge_profile_from_resumes,
)
from app.services.resume_rag import rebuild_profile_rag
from app.storage.accounts import (
    count_assets_for_profile,
    create_extra_profile,
    ensure_profile_upload_dir,
    get_profile_for_user,
    list_assets_for_profile,
    list_profiles,
    insert_onboarding_asset,
    profile_upload_rel_prefix,
    set_active_profile,
    update_profile_candidate,
)
from app.storage.db import get_conn

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

_MAX_BYTES = 5 * 1024 * 1024
_ALLOWED_RESUME = {".docx", ".txt", ".pdf"}


class CreateProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class UpdateCandidateBody(BaseModel):
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None


class ProcessResumesBody(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")


class AchievementEdit(BaseModel):
    id: Optional[str] = None
    text: str = Field(min_length=1, max_length=2000)
    status: str = "user_confirmed"
    evidence_source: Optional[str] = None
    confidence: Optional[float] = None
    technologies: Optional[List[str]] = None


class RoleEdit(BaseModel):
    id: Optional[str] = None
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    is_current: Optional[bool] = None
    tech: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    achievements: List[AchievementEdit] = Field(default_factory=list)
    core_facts: List[str] = Field(default_factory=list)


class CandidateEdit(BaseModel):
    preferred_name: str = ""
    headline: str = ""
    years_experience: int = 0
    skills: Dict[str, Any] = Field(default_factory=dict)


class ProfileTruthUpdateBody(BaseModel):
    candidate: CandidateEdit
    roles: List[RoleEdit] = Field(default_factory=list)
    inferred_profile: List[Any] = Field(default_factory=list)


def _uid(request: Request) -> int:
    from app.auth.session_user import session_user_id

    return session_user_id(request)


def _require_real_user(request: Request) -> int:
    from app.auth.session_user import require_authenticated_user_id

    return require_authenticated_user_id(request)


def _owned_disk_profile(conn, uid: int, profile_id: int):
    p = get_profile_for_user(conn, uid, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="profile not found")
    if p.use_builtin:
        raise HTTPException(
            status_code=400,
            detail="Built-in workspace profile has no per-user upload store.",
        )
    candir = p.effective_candidate_dir()
    if not candir:
        raise HTTPException(status_code=400, detail="Profile storage not ready")
    return p, candir


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


@router.post("/{profile_id}/rag/rebuild")
def rebuild_profile_rag_endpoint(request: Request, profile_id: int) -> Any:
    uid = _uid(request)
    with get_conn() as conn:
        p = get_profile_for_user(conn, uid, profile_id)
        if not p:
            raise HTTPException(status_code=404, detail="profile not found")
        if p.use_builtin:
            raise HTTPException(
                status_code=400,
                detail="Built-in workspace profile has no per-user RAG store.",
            )
        n = rebuild_profile_rag(conn, profile_id, uid)
    return {"ok": True, "chunks_written": n}


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


@router.get("/{profile_id}/resumes")
def list_profile_resumes(request: Request, profile_id: int) -> Any:
    uid = _require_real_user(request)
    with get_conn() as conn:
        _owned_disk_profile(conn, uid, profile_id)
        rows = list_assets_for_profile(
            conn, profile_id, kinds=("resume", "profile_resume")
        )
    return {
        "ok": True,
        "resumes": [
            {
                "id": int(r["id"]),
                "kind": r["kind"],
                "original_name": r["original_name"] or "",
                "byte_size": int(r["byte_size"] or 0),
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


@router.post("/{profile_id}/resumes")
async def upload_profile_resume(
    request: Request,
    profile_id: int,
    file: UploadFile = File(...),
    process: bool = Query(
        False,
        description="If true, merge into truth model and rebuild RAG after upload.",
    ),
    mode: str = Query("merge", pattern="^(merge|replace)$"),
) -> Any:
    """Upload a résumé into this profile's isolated pack (kind=profile_resume)."""
    uid = _require_real_user(request)
    with get_conn() as conn:
        _prof, candir = _owned_disk_profile(conn, uid, profile_id)
        name = (file.filename or "resume").strip()
        suf = ""
        if "." in name:
            suf = "." + name.rsplit(".", 1)[-1].lower()
        if suf not in _ALLOWED_RESUME:
            raise HTTPException(
                status_code=400,
                detail="Résumé must be .docx, .txt, or .pdf",
            )
        n = count_assets_for_profile(conn, profile_id, "profile_resume") + 1
        safe = f"resume_{n}{suf}"
        disk = ensure_profile_upload_dir(uid, profile_id)
        dest = disk / safe
        data = await file.read()
        if len(data) > _MAX_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 5MB)")
        dest.write_bytes(data)
        rel = f"{profile_upload_rel_prefix(uid, profile_id)}/{safe}"
        asset_id = insert_onboarding_asset(
            conn,
            user_id=uid,
            profile_id=profile_id,
            kind="profile_resume",
            rel_path=rel,
            original_name=name,
            byte_size=len(data),
        )
        result: Dict[str, Any] = {
            "ok": True,
            "saved_as": safe,
            "asset_id": asset_id,
            "rel_path": rel,
        }
        from app.services.onboarding_bootstrap import read_resume_file

        try:
            extracted = read_resume_file(dest)
        except ValueError as exc:
            dest.unlink(missing_ok=True)
            conn.execute(
                "DELETE FROM user_onboarding_assets WHERE id = ?",
                (asset_id,),
            )
            conn.commit()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            conn.execute(
                "DELETE FROM user_onboarding_assets WHERE id = ?",
                (asset_id,),
            )
            conn.commit()
            raise HTTPException(
                status_code=400,
                detail=f"Could not extract text from this file: {exc}",
            ) from exc
        result["extracted_chars"] = len(extracted)
        result["extracted_preview"] = extracted[:4000]
        result["needs_review"] = True
        if process:
            processed = _process_profile_resumes(
                conn, uid=uid, profile_id=profile_id, candir=candir, mode=mode
            )
            result["processed"] = processed
    return result


@router.post("/{profile_id}/resumes/process")
def process_profile_resumes(
    request: Request,
    profile_id: int,
    body: Optional[ProcessResumesBody] = None,
) -> Any:
    """Merge uploaded résumés into the profile truth model and rebuild RAG."""
    uid = _require_real_user(request)
    mode = (body.mode if body is not None else "merge") or "merge"
    with get_conn() as conn:
        _prof, candir = _owned_disk_profile(conn, uid, profile_id)
        return _process_profile_resumes(
            conn, uid=uid, profile_id=profile_id, candir=candir, mode=mode
        )


def _process_profile_resumes(
    conn, *, uid: int, profile_id: int, candir, mode: str
) -> Dict[str, Any]:
    resume_texts = load_resume_texts_for_profile(conn, profile_id)
    if not resume_texts:
        raise HTTPException(
            status_code=400,
            detail="No résumé files on this profile. Upload a .docx or .txt first.",
        )
    ok, msg = merge_profile_from_resumes(
        profile_dir=candir,
        resume_texts=resume_texts,
        mode=mode,
    )
    if not ok:
        raise HTTPException(status_code=422, detail=msg)
    chunks = rebuild_profile_rag(conn, profile_id, uid)
    return {
        "ok": True,
        "message": msg,
        "mode": mode,
        "resume_files_read": len(resume_texts),
        "chunks_written": chunks,
        "profile": profile_review_payload(candir),
    }


@router.get("/{profile_id}/truth")
def get_profile_truth(request: Request, profile_id: int) -> Any:
    uid = _require_real_user(request)
    with get_conn() as conn:
        _prof, candir = _owned_disk_profile(conn, uid, profile_id)
    return {"ok": True, "profile": profile_review_payload(candir)}


@router.put("/{profile_id}/truth")
def put_profile_truth(
    request: Request, profile_id: int, body: ProfileTruthUpdateBody
) -> Any:
    """Save user corrections to the active profile truth model."""
    uid = _require_real_user(request)
    with get_conn() as conn:
        _prof, candir = _owned_disk_profile(conn, uid, profile_id)

    existing = load_profile_truth(candir)
    roles_payload = []
    for role in body.roles:
        achievements = [a.model_dump() for a in role.achievements]
        if not achievements and role.core_facts:
            achievements = [
                {"text": t, "status": "user_confirmed"} for t in role.core_facts if t.strip()
            ]
        for a in achievements:
            a["status"] = "user_confirmed"
        roles_payload.append(
            {
                "id": role.id,
                "company": role.company,
                "title": role.title,
                "location": role.location,
                "start": role.start,
                "end": role.end,
                "is_current": role.is_current,
                "tech": role.tech,
                "themes": role.themes,
                "achievements": achievements,
            }
        )

    merged = {
        **existing,
        "candidate": {
            **(existing.get("candidate") if isinstance(existing.get("candidate"), dict) else {}),
            "preferred_name": body.candidate.preferred_name,
            "headline": body.candidate.headline,
            "years_experience": body.candidate.years_experience,
            "skills": body.candidate.skills,
        },
        "roles": roles_payload,
        "profile_layers": {
            **(
                existing.get("profile_layers")
                if isinstance(existing.get("profile_layers"), dict)
                else {}
            ),
            "inferred_profile": body.inferred_profile,
            "user_preferences": (
                (existing.get("profile_layers") or {}).get("user_preferences")
                if isinstance(existing.get("profile_layers"), dict)
                else {}
            )
            or {},
        },
    }
    truth = normalize_truth_model(merged, default_source="user_review")
    truth_path(candir).write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return {"ok": True, "profile": profile_review_payload(candir)}


__all__ = ["router"]
