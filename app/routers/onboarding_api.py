"""First-login onboarding: uploads, profile bootstrap, and review/confirm."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.services.candidate_profile_io import (
    has_reviewable_roles,
    load_profile_truth,
    profile_review_payload,
    truth_path,
)
from app.services.evidence_schema import normalize_truth_model
from app.services.onboarding_bootstrap import (
    load_upload_texts_for_user,
    merge_onboarding_profile,
)
from app.services.profile_conflicts import detect_profile_conflicts
from app.services.resume_rag import rebuild_profile_rag
from app.storage.accounts import (
    count_onboarding_assets,
    ensure_onboarding_upload_dir,
    get_profile_for_user,
    get_user_by_id,
    insert_onboarding_asset,
    mark_onboarding_complete,
    onboarding_upload_rel_prefix,
    user_must_complete_onboarding,
)
from app.storage.db import get_conn

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

_MAX_BYTES = 5 * 1024 * 1024
_ALLOWED_RESUME = {".docx", ".txt"}


def _session_uid(request: Request) -> int:
    from app.auth.session_user import session_user_id

    return session_user_id(request)


def _require_real_user(request: Request) -> int:
    from app.auth.session_user import require_authenticated_user_id

    return require_authenticated_user_id(request)


@router.get("/status")
def onboarding_status(request: Request) -> Any:
    uid = _session_uid(request)
    awaiting_review = False
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        resume_n = count_onboarding_assets(conn, uid, "resume")
        job_n = count_onboarding_assets(conn, uid, "job_sample")
        need = user_must_complete_onboarding(u, default_user_id=settings.default_user_id)
        pid = u.active_profile_id
        if need and pid:
            prof = get_profile_for_user(conn, uid, pid)
            if prof and prof.effective_candidate_dir():
                truth = load_profile_truth(prof.effective_candidate_dir())
                awaiting_review = has_reviewable_roles(truth)
    return {
        "needs_onboarding": need,
        "requires_onboarding": u.requires_onboarding,
        "onboarding_completed_at": (
            u.onboarding_completed_at.isoformat() if u.onboarding_completed_at else None
        ),
        "resume_count": resume_n,
        "job_sample_count": job_n,
        "min_resumes": settings.onboarding_min_resumes,
        "min_job_samples": settings.onboarding_min_job_samples,
        "active_profile_id": pid,
        "llm_configured": settings.llm_configured,
        "allow_finish_without_llm": settings.onboarding_allow_finish_without_llm,
        "awaiting_review": awaiting_review,
    }


@router.post("/resume")
async def upload_resume(request: Request, file: UploadFile = File(...)) -> Any:
    uid = _require_real_user(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u or not u.active_profile_id:
            raise HTTPException(status_code=400, detail="No active profile")
        pid = u.active_profile_id
        prof = get_profile_for_user(conn, uid, pid)
        if not prof or not prof.effective_candidate_dir():
            raise HTTPException(status_code=400, detail="Profile storage not ready")
        name = (file.filename or "resume").strip()
        suf = ""
        if "." in name:
            suf = "." + name.rsplit(".", 1)[-1].lower()
        if suf not in _ALLOWED_RESUME:
            raise HTTPException(
                status_code=400,
                detail="Résumé must be .docx or .txt",
            )
        n = count_onboarding_assets(conn, uid, "resume") + 1
        safe = f"resume_{n}{suf}"
        disk = ensure_onboarding_upload_dir(uid, pid)
        dest = disk / safe
        data = await file.read()
        if len(data) > _MAX_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 5MB)")
        dest.write_bytes(data)
        rel = f"{onboarding_upload_rel_prefix(uid, pid)}/{safe}"
        insert_onboarding_asset(
            conn,
            user_id=uid,
            profile_id=pid,
            kind="resume",
            rel_path=rel,
            original_name=name,
            byte_size=len(data),
        )
    return {"ok": True, "saved_as": safe}


class JobSampleBody(BaseModel):
    text: str = Field(min_length=80, max_length=80_000)


@router.post("/job-sample")
def add_job_sample(request: Request, body: JobSampleBody) -> Any:
    uid = _require_real_user(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u or not u.active_profile_id:
            raise HTTPException(status_code=400, detail="No active profile")
        pid = u.active_profile_id
        prof = get_profile_for_user(conn, uid, pid)
        if not prof or not prof.effective_candidate_dir():
            raise HTTPException(status_code=400, detail="Profile storage not ready")
        n = count_onboarding_assets(conn, uid, "job_sample") + 1
        safe = f"job_sample_{n}.txt"
        disk = ensure_onboarding_upload_dir(uid, pid)
        dest = disk / safe
        raw = body.text.strip()
        dest.write_text(raw, encoding="utf-8")
        rel = f"{onboarding_upload_rel_prefix(uid, pid)}/{safe}"
        insert_onboarding_asset(
            conn,
            user_id=uid,
            profile_id=pid,
            kind="job_sample",
            rel_path=rel,
            original_name=safe,
            byte_size=len(raw.encode("utf-8")),
        )
    return {"ok": True, "saved_as": safe}


@router.post("/finish")
def finish_onboarding(request: Request) -> Any:
    """Generate the candidate profile draft. Does not unlock the app — call /confirm."""
    uid = _require_real_user(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u or not u.active_profile_id:
            raise HTTPException(status_code=400, detail="No active profile")
        if not user_must_complete_onboarding(u, default_user_id=settings.default_user_id):
            return {"ok": True, "already_complete": True, "message": "Onboarding already finished."}
        pid = u.active_profile_id
        prof = get_profile_for_user(conn, uid, pid)
        if not prof:
            raise HTTPException(status_code=400, detail="Profile not found")
        candir = prof.effective_candidate_dir()
        if not candir:
            raise HTTPException(status_code=400, detail="Profile storage not ready")

        if count_onboarding_assets(conn, uid, "resume") < settings.onboarding_min_resumes:
            raise HTTPException(
                status_code=400,
                detail=f"Add at least {settings.onboarding_min_resumes} résumé file(s).",
            )
        if count_onboarding_assets(conn, uid, "job_sample") < settings.onboarding_min_job_samples:
            raise HTTPException(
                status_code=400,
                detail=f"Add at least {settings.onboarding_min_job_samples} job description samples.",
            )

        resume_texts, job_texts = load_upload_texts_for_user(conn, uid)
        if len(resume_texts) < settings.onboarding_min_resumes:
            raise HTTPException(status_code=400, detail="Could not read résumé files.")
        if len(job_texts) < settings.onboarding_min_job_samples:
            raise HTTPException(status_code=400, detail="Could not read job samples.")

        ok, msg = merge_onboarding_profile(
            profile_dir=candir,
            resume_texts=resume_texts,
            job_sample_texts=job_texts,
        )
        if not ok:
            raise HTTPException(status_code=422, detail=msg)

        rebuild_profile_rag(conn, pid, uid)
        payload = profile_review_payload(candir)

    return {
        "ok": True,
        "message": msg,
        "needs_review": True,
        "profile": payload,
    }


@router.get("/profile")
def get_onboarding_profile(request: Request) -> Any:
    uid = _require_real_user(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u or not u.active_profile_id:
            raise HTTPException(status_code=400, detail="No active profile")
        prof = get_profile_for_user(conn, uid, u.active_profile_id)
        if not prof or not prof.effective_candidate_dir():
            raise HTTPException(status_code=400, detail="Profile storage not ready")
        candir = prof.effective_candidate_dir()
    return {"ok": True, "profile": profile_review_payload(candir)}


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


class ProfileUpdateBody(BaseModel):
    candidate: CandidateEdit
    roles: List[RoleEdit] = Field(default_factory=list)
    inferred_profile: List[Any] = Field(default_factory=list)


@router.put("/profile")
def put_onboarding_profile(request: Request, body: ProfileUpdateBody) -> Any:
    """Save user corrections before confirm. Marks achievements as user_confirmed."""
    uid = _require_real_user(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u or not u.active_profile_id:
            raise HTTPException(status_code=400, detail="No active profile")
        if not user_must_complete_onboarding(u, default_user_id=settings.default_user_id):
            raise HTTPException(status_code=400, detail="Onboarding already complete.")
        prof = get_profile_for_user(conn, uid, u.active_profile_id)
        if not prof or not prof.effective_candidate_dir():
            raise HTTPException(status_code=400, detail="Profile storage not ready")
        candir = prof.effective_candidate_dir()

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


@router.post("/confirm")
def confirm_onboarding(request: Request) -> Any:
    """User approved the reviewed profile — unlock the rest of the app."""
    uid = _require_real_user(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u or not u.active_profile_id:
            raise HTTPException(status_code=400, detail="No active profile")
        if not user_must_complete_onboarding(u, default_user_id=settings.default_user_id):
            return {"ok": True, "already_complete": True, "message": "Onboarding already finished."}
        pid = u.active_profile_id
        prof = get_profile_for_user(conn, uid, pid)
        if not prof or not prof.effective_candidate_dir():
            raise HTTPException(status_code=400, detail="Profile storage not ready")
        candir = prof.effective_candidate_dir()
        truth = load_profile_truth(candir)
        # Allow confirm even with empty roles in LLM-off / raw-text mode.
        mark_onboarding_complete(conn, uid)
        rebuild_profile_rag(conn, pid, uid)
    return {
        "ok": True,
        "message": "Profile confirmed. Workspace unlocked.",
        "has_roles": has_reviewable_roles(truth),
        "conflicts_remaining": detect_profile_conflicts(truth),
    }


__all__ = ["router"]
