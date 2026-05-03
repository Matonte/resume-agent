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
            "meeting_advisor": bool = True,
            "advisor_subject_name": Optional[str],
            "extract_posting_people": bool = True,
        }
        Returns the tailored `JobRecord` plus artifact download URLs, and when
        ``meeting_advisor`` is true and ``MEETING_ADVISOR_URL`` is set, includes
        ``meeting_advice`` (generic advisor JSON), optional
        ``meeting_advisor_people`` (one dossier per name found in the posting),
        and/or ``meeting_advisor_note``.

    GET /tailor
        Serves the HTML form (see templates/tailor.html). The template
        is rendered by `app.main` so this router stays JSON-only.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.onboarding_guard import raise_if_onboarding_incomplete
from app.config import settings
from app.jobs.job_outreach_notes import maybe_write_job_outreach_notes
from app.jobs.preferences import load_preferences, merge_preferences_candidate
from app.jobs.tailor import tailor_job_from_raw
from app.scrapers.base import RawJob
from app.services.outreach_enrich import advise_for_job_context, advise_posting_people_dossiers
from app.services.outreach_posting_people import (
    extract_people_from_posting_corpus,
    merge_posting_corpus,
)
from app.storage.accounts import get_profile, get_user_by_id
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
    #: Call ``MEETING_ADVISOR_URL`` /api/v1/advise with this JD (in addition to outreach when configured).
    meeting_advisor: bool = True
    advisor_subject_name: Optional[str] = None
    #: Extract named people from the posting text and run advisor once per name (LLM when ``use_llm``).
    #: If none are found, returns a single generic ``meeting_advice`` block instead.
    extract_posting_people: bool = True

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
    meeting_advice: Optional[Dict[str, Any]] = None
    meeting_advisor_people: Optional[List[Dict[str, Any]]] = None
    meeting_advisor_note: Optional[str] = None


def _session_uid(request: Request) -> int:
    return int(request.session.get("user_id", settings.default_user_id))


def _ensure_run_row(run_id: str, user_id: int) -> None:
    """Idempotently insert a DailyRun row so manual jobs satisfy the
    foreign-key expectation that every job belongs to a run."""
    with get_conn() as conn:
        try:
            insert_daily_run(
                conn,
                DailyRun(
                    id=run_id,
                    ran_at=datetime.utcnow(),
                    status="manual",
                    user_id=user_id,
                ),
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
        "outreach_contacts": f"/api/jobs/{job_id}/artifact?file=outreach_contacts.json",
    }


@router.get("/api/manual-tailor")
def manual_tailor_get() -> JSONResponse:
    """Opening this URL in a browser sends GET; return a hint instead of 405."""
    return JSONResponse(
        {
            "message": "Use POST with JSON body (url and/or description).",
            "ui": "/tailor",
            "method": "POST",
            "example_body": {
                "url": "https://boards.greenhouse.io/example/jobs/123",
                "description": None,
                "company": None,
                "title": None,
                "use_llm": True,
                "meeting_advisor": True,
                "advisor_subject_name": None,
                "extract_posting_people": True,
            },
        }
    )


@router.post("/api/manual-tailor", response_model=ManualTailorResponse)
def manual_tailor(request: Request, payload: ManualTailorRequest) -> Any:
    raise_if_onboarding_incomplete(request)
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

    uid = _session_uid(request)
    prefs = load_preferences()
    with get_conn() as conn:
        u = get_user_by_id(conn, uid)
        prof = None
        if u and u.active_profile_id:
            prof = get_profile(conn, u.active_profile_id)
    prefs = merge_preferences_candidate(prefs, prof)

    run_date = date.today()
    run_id = DailyRun.make_id(run_date, user_id=uid)
    _ensure_run_row(run_id, uid)

    try:
        tailored = tailor_job_from_raw(
            raw,
            prefs,
            run_id=run_id,
            run_date=run_date,
            user_id=uid,
            use_llm=payload.use_llm,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("manual tailor failed")
        raise HTTPException(status_code=500, detail=f"tailor failed: {exc}")

    with get_conn() as conn:
        upsert_job(conn, tailored.record)

    try:
        maybe_write_job_outreach_notes(
            raw,
            Path(tailored.artifact_dir),
            prefs,
            use_llm=payload.use_llm,
        )
    except Exception:  # noqa: BLE001
        logger.exception("manual tailor: outreach notes failed")

    meeting_advice = None
    meeting_people: Optional[List[Dict[str, Any]]] = None
    meeting_note: Optional[str] = None
    if payload.meeting_advisor:
        if not settings.meeting_advisor_configured:
            meeting_note = "MEETING_ADVISOR_URL is not set."
        else:
            tried_extract = False
            people_rows: Optional[List[Dict[str, Any]]] = None
            if payload.extract_posting_people:
                tried_extract = True
                corpus = merge_posting_corpus(
                    raw,
                    fetch_apply_page=prefs.outreach_for_job.fetch_apply_page,
                )
                extracted = extract_people_from_posting_corpus(
                    corpus,
                    (tailored.record.company or "").strip(),
                    max_people=max(0, prefs.outreach_for_job.max_posting_people),
                    use_llm=payload.use_llm,
                )
                if extracted:
                    dossiers = advise_posting_people_dossiers(
                        extracted,
                        company=tailored.record.company or "",
                        title=tailored.record.title or "",
                        job_description_excerpt=description,
                        listing_url=tailored.record.url or effective_url,
                        use_llm=payload.use_llm,
                    )
                    dumped = [d.model_dump(mode="json") for d in dossiers]
                    if dumped:
                        people_rows = dumped
            if people_rows:
                meeting_people = people_rows
                meeting_note = (
                    f"Named people in posting ({len(meeting_people)}): per-person prep below."
                )
            else:
                meeting_advice = advise_for_job_context(
                    subject_name=(payload.advisor_subject_name or "").strip(),
                    company=tailored.record.company or "",
                    title=tailored.record.title or "",
                    job_description_excerpt=description,
                    listing_url=tailored.record.url or effective_url,
                )
                if tried_extract and meeting_advice is not None:
                    meeting_note = (
                        "No named contacts found in the posting (or LLM extraction off); "
                        "showing general hiring-team prep."
                    )
                elif meeting_advice is None and not meeting_note:
                    meeting_note = "Meeting advisor returned no response (check server logs)."
    elif settings.meeting_advisor_configured:
        meeting_note = (
            "Meeting advisor was not used — the “Meeting advisor” checkbox was off. "
            "Enable it above and run again, or open the Advisor page from the header."
        )
    else:
        meeting_note = (
            "MEETING_ADVISOR_URL is not set. Add e.g. MEETING_ADVISOR_URL=http://127.0.0.1:5003 "
            "to .env, restart Resume Agent, and run flask_sample run_meeting_advisor.py."
        )

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
        meeting_advice=meeting_advice,
        meeting_advisor_people=meeting_people,
        meeting_advisor_note=meeting_note,
    )


__all__ = ["router"]
