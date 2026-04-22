"""Daily-job review dashboard API.

Exposes a small REST surface used by `templates/jobs_today.html`:

    GET  /api/jobs/today                 list today's jobs
    GET  /api/jobs/{id}                  full record + screening answers
    GET  /api/jobs/{id}/artifact?file=   download resume.docx, cover_letter.docx, etc.
    POST /api/jobs/{id}/approve          mark approved
    POST /api/jobs/{id}/skip             mark skipped
    POST /api/jobs/{id}/mark-submitted   mark submitted
    POST /api/jobs/{id}/prepare-apply    launch Playwright form-prefill (semi-auto)

The dashboard HTML itself is served at `/jobs/today` by `app.main`.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.storage.db import (
    STATUS_APPROVED,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    DailyRun,
    JobRecord,
    get_conn,
    list_jobs_for_date,
    load_job,
    update_job_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["daily-jobs"])


# ----------------- serialization -----------------


ALLOWED_ARTIFACTS = {"resume.docx", "cover_letter.docx", "screening.json", "metadata.json"}


def _job_to_dict(j: JobRecord) -> Dict[str, Any]:
    return {
        "id": j.id,
        "source": j.source,
        "url": j.url,
        "external_id": j.external_id,
        "title": j.title,
        "company": j.company,
        "location": j.location,
        "salary_raw": j.salary_raw,
        "archetype_id": j.archetype_id,
        "fit_score": j.fit_score,
        "status": j.status,
        "artifact_dir": j.artifact_dir,
        "daily_run_id": j.daily_run_id,
        "discovered_at": j.discovered_at.isoformat() if j.discovered_at else None,
        "posted_at": j.posted_at.isoformat() if j.posted_at else None,
    }


def _resolve_run_id(run_id: Optional[str]) -> str:
    if run_id:
        return run_id
    return DailyRun.make_id()


# ----------------- endpoints -----------------


@router.get("/today")
def list_today(run_id: Optional[str] = Query(None)) -> JSONResponse:
    target = _resolve_run_id(run_id)
    with get_conn() as conn:
        jobs = list_jobs_for_date(conn, target)
    return JSONResponse({
        "run_id": target,
        "jobs": [_job_to_dict(j) for j in jobs],
    })


@router.get("/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    with get_conn() as conn:
        job = load_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    payload = _job_to_dict(job)
    payload["screening"] = job.screening
    payload["jd_full"] = job.jd_full
    return JSONResponse(payload)


@router.get("/{job_id}/artifact")
def get_artifact(job_id: str, file: str = Query(...)) -> FileResponse:
    if file not in ALLOWED_ARTIFACTS:
        raise HTTPException(status_code=400, detail=f"disallowed file: {file}")
    with get_conn() as conn:
        job = load_job(conn, job_id)
    if not job or not job.artifact_dir:
        raise HTTPException(status_code=404, detail="artifact folder not found")
    path = Path(job.artifact_dir) / file
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"missing file: {file}")
    mime, _ = mimetypes.guess_type(path.name)
    return FileResponse(str(path), media_type=mime or "application/octet-stream", filename=path.name)


@router.post("/{job_id}/approve")
def approve(job_id: str) -> JSONResponse:
    return _transition(job_id, STATUS_APPROVED)


@router.post("/{job_id}/skip")
def skip(job_id: str) -> JSONResponse:
    return _transition(job_id, STATUS_SKIPPED)


@router.post("/{job_id}/mark-submitted")
def mark_submitted(job_id: str) -> JSONResponse:
    return _transition(job_id, STATUS_SUBMITTED)


@router.post("/{job_id}/prepare-apply")
def prepare_apply(job_id: str) -> JSONResponse:
    """Launch a non-headless Playwright window that navigates to the
    apply URL, uploads resume+cover_letter, and pastes screening answers.
    You hit Submit yourself. Returns immediately; the browser window is
    the user-facing side effect.

    Implemented in the `semi-auto-apply` task; until then we validate the
    target and return a 501 so the dashboard shows a clear message."""
    with get_conn() as conn:
        job = load_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        from app.scrapers.apply_session import prepare_apply as _do_prepare  # lazy
    except Exception as exc:  # pragma: no cover - import-time guard
        logger.exception("prepare_apply not yet wired")
        raise HTTPException(
            status_code=501,
            detail=f"semi-auto apply not installed: {exc}",
        )
    try:
        _do_prepare(job)
    except Exception as exc:  # noqa: BLE001
        logger.exception("prepare_apply failed for %s", job_id)
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse({"ok": True, "job_id": job_id})


def _transition(job_id: str, status: str) -> JSONResponse:
    with get_conn() as conn:
        job = load_job(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        update_job_status(conn, job_id, status)
        refreshed = load_job(conn, job_id)
    return JSONResponse(_job_to_dict(refreshed))  # type: ignore[arg-type]


__all__ = ["router"]
