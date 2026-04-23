"""Manual tailor endpoint and page.

Purpose:
    Let the user paste a job description (or a URL) outside the daily
    scrape loop - useful for sites the automated scrapers can't reach
    (e.g. Welcome to the Jungle, where bot detection blocks our
    Playwright sessions) or for one-off leads a friend sent.

Endpoints:
    POST /api/manual-tailor
        Body (JSON): {
            "url":         Optional[str],   # if provided, we fetch the JD over HTTP
            "description": Optional[str],   # raw JD text; required if url is absent
            "company":     Optional[str],   # optional overrides if you know better
            "title":       Optional[str],
            "location":    Optional[str],
            "apply_url":   Optional[str],   # defaults to url
            "use_llm":     bool = True,
        }
        Returns the tailored `JobRecord` plus artifact download URLs.

    GET /tailor
        Serves the HTML form (see templates/tailor.html). The template
        is rendered by `app.main` so this router stays JSON-only.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.jobs.preferences import load_preferences
from app.jobs.tailor import tailor_job_from_raw
from app.scrapers.base import RawJob
from app.storage.db import DailyRun, get_conn, insert_daily_run, upsert_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["manual-tailor"])

_MANUAL_SOURCE = "manual"


class ManualTailorRequest(BaseModel):
    url: Optional[str] = None
    description: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    location: Optional[str] = None
    apply_url: Optional[str] = None
    use_llm: bool = True

    def has_jd_source(self) -> bool:
        return bool((self.description and self.description.strip()) or (self.url and self.url.strip()))


class ManualTailorResponse(BaseModel):
    job_id: str
    run_id: str
    title: str
    company: str
    location: Optional[str] = None
    url: str
    archetype_id: Optional[str] = None
    fit_score: Optional[float] = None
    summary: Optional[str] = None
    artifact_urls: Dict[str, str] = Field(default_factory=dict)
    dashboard_url: str
    warning: Optional[str] = None


def _ensure_run_row(run_id: str) -> None:
    """Idempotently insert a DailyRun row so manual jobs satisfy the
    foreign-key expectation that every job belongs to a run."""
    with get_conn() as conn:
        try:
            insert_daily_run(
                conn,
                DailyRun(id=run_id, ran_at=datetime.utcnow(), status="manual"),
            )
        except Exception:
            # Row already exists from the nightly run; that's fine.
            pass


def _artifact_urls(job_id: str) -> Dict[str, str]:
    return {
        "resume": f"/api/jobs/{job_id}/artifact?file=resume.docx",
        "cover_letter": f"/api/jobs/{job_id}/artifact?file=cover_letter.docx",
        "screening": f"/api/jobs/{job_id}/artifact?file=screening.json",
        "metadata": f"/api/jobs/{job_id}/artifact?file=metadata.json",
    }


@router.post("/api/manual-tailor", response_model=ManualTailorResponse)
def manual_tailor(payload: ManualTailorRequest) -> Any:
    if not payload.has_jd_source():
        raise HTTPException(
            status_code=400,
            detail="provide either 'url' or 'description'",
        )

    warning: Optional[str] = None
    description = (payload.description or "").strip()
    fetch_warning: Optional[str] = None
    fetched_title = ""
    fetched_company = ""
    effective_url = (payload.url or "").strip() or "manual://paste"

    if payload.url and not description:
        from app.services.jd_fetcher import fetch_jd  # lazy import
        fetched = fetch_jd(payload.url.strip())
        description = fetched.raw.jd_full
        fetched_title = fetched.raw.title or ""
        fetched_company = fetched.raw.company or ""
        effective_url = fetched.raw.url or payload.url
        if fetched.error:
            fetch_warning = fetched.error
            if not description:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{fetch_warning} "
                        "Paste the job description body into the 'description' field."
                    ),
                )

    if not description or len(description) < 100:
        raise HTTPException(
            status_code=422,
            detail=(
                "Job description too short to tailor against (need at least "
                "100 characters)."
            ),
        )

    raw = RawJob(
        source=_MANUAL_SOURCE,
        url=effective_url,
        title=(payload.title or fetched_title or "Untitled Role").strip(),
        company=(payload.company or fetched_company or "Unknown").strip(),
        jd_full=description,
        location=(payload.location or None),
        apply_url=(payload.apply_url or effective_url),
    )

    prefs = load_preferences()
    run_date = date.today()
    run_id = DailyRun.make_id(run_date)
    _ensure_run_row(run_id)

    try:
        tailored = tailor_job_from_raw(
            raw, prefs, run_id=run_id, run_date=run_date, use_llm=payload.use_llm,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("manual tailor failed")
        raise HTTPException(status_code=500, detail=f"tailor failed: {exc}")

    with get_conn() as conn:
        upsert_job(conn, tailored.record)

    # The warning the user sees is the fetch-side note (if any) - we did still
    # tailor something, so we shouldn't 4xx, but we want them to know we
    # couldn't fully parse the URL.
    warning = fetch_warning

    return ManualTailorResponse(
        job_id=tailored.record.id,
        run_id=run_id,
        title=tailored.record.title,
        company=tailored.record.company,
        location=tailored.record.location,
        url=tailored.record.url,
        archetype_id=tailored.record.archetype_id,
        fit_score=tailored.record.fit_score,
        summary=(tailored.record.jd_full[:400] if tailored.record.jd_full else None),
        artifact_urls=_artifact_urls(tailored.record.id),
        dashboard_url=f"/jobs/today",
        warning=warning,
    )


__all__ = ["router"]
