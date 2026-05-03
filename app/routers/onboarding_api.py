"""First-login onboarding: uploads + profile bootstrap."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.services.onboarding_bootstrap import (
    load_upload_texts_for_user,
    merge_onboarding_profile,
)
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
    return int(request.session.get("user_id", settings.default_user_id))


def _require_real_user(request: Request) -> int:
    uid = _session_uid(request)
    if uid == settings.default_user_id:
        raise HTTPException(
            status_code=403,
            detail="Log in with a registered account to use onboarding.",
        )
    return uid


@router.get("/status")
def onboarding_status(request: Request) -> Any:
    uid = _session_uid(request)
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        resume_n = count_onboarding_assets(conn, uid, "resume")
        job_n = count_onboarding_assets(conn, uid, "job_sample")
        need = user_must_complete_onboarding(u, default_user_id=settings.default_user_id)
        pid = u.active_profile_id
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

        mark_onboarding_complete(conn, uid)

    return {"ok": True, "message": msg}


__all__ = ["router"]
