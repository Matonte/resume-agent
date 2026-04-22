"""Daily job-agent orchestration.

Entry point: `run_daily(scrapers=None, preferences=None, send_email=True)`.

Sequence:
    1. Load preferences (`data/preferences.yaml`).
    2. Open (or reuse) today's `DailyRun` row.
    3. For each enabled source, ask its scraper for up to `per_source_cap`
       `RawJob`s. Scraper errors are caught and logged into the run, never
       propagated.
    4. Filter jobs by `preferences.targets.locations` / `remote_ok` and the
       exclude lists.
    5. For each surviving job: classify, compute fit_score, generate the
       tailored resume + cover letter + screening answers, and persist
       everything into `outputs/<date>/job_<id>/`.
    6. Rank by fit_score, cut to `daily_cap`, mark the rest as `skipped`.
    7. Upsert into SQLite.
    8. Send the email digest (optional).

The runner is fully testable with mocked scrapers and no network.
"""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from app.jobs.preferences import Preferences, load_preferences
from app.packaging.cover_letter import build_cover_letter, write_cover_letter_docx
from app.packaging.screening import answer_questions, extract_questions
from app.scrapers.base import RawJob, Scraper
from app.scrapers.registry import get_scraper
from app.services.classifier import classify_job
from app.services.fit_score import compute_fit_score
from app.services.resume_docx import generate_tailored_resume_bytes
from app.services.resume_tailor import generate_resume_draft
from app.storage.db import (
    STATUS_FAILED,
    STATUS_NEW,
    STATUS_SKIPPED,
    DailyRun,
    JobRecord,
    artifact_dir_for,
    get_conn,
    insert_daily_run,
    list_jobs_for_date,
    update_daily_run,
    update_job_status,
    upsert_job,
)

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """What `run_daily` returns. Useful for the CLI and for tests."""

    run_id: str
    scraped: int
    filtered: int
    tailored: int
    kept: int
    email_sent: bool
    errors: List[str]


# ----------------- public API -----------------


def run_daily(
    *,
    scrapers: Optional[Sequence[Scraper]] = None,
    preferences: Optional[Preferences] = None,
    send_email: bool = True,
    use_llm: bool = True,
    check_auth: bool = True,
    for_date: Optional[date] = None,
    now: Optional[datetime] = None,
) -> RunSummary:
    prefs = preferences or load_preferences()
    run_date = for_date or (now.date() if now else datetime.utcnow().date())
    run_id = DailyRun.make_id(run_date)

    run = DailyRun(id=run_id, ran_at=now or datetime.utcnow(), status="running")
    with get_conn() as conn:
        insert_daily_run(conn, run)

    scraper_list = list(scrapers) if scrapers is not None else _default_scrapers(prefs)

    errors: List[str] = []

    # 0. Auth preflight. Any scraper with `requires_auth=True` whose
    #    persistent Playwright profile is signed out gets dropped with a
    #    clear warning into both logs and `daily_runs.error`, so the rest
    #    of the run still produces useful output. Tests and --fake runs
    #    pass `check_auth=False` (or use FakeScrapers which set
    #    requires_auth=False).
    if check_auth:
        scraper_list = _preflight_auth(scraper_list, errors)

    # 1. Scrape.
    raw: List[RawJob] = []
    for scraper in scraper_list:
        try:
            found = scraper.discover(prefs) or []
            raw.extend(found[: prefs.per_source_cap])
        except Exception as exc:  # noqa: BLE001
            msg = f"{scraper.source}: {exc}"
            logger.exception("Scraper %s failed", scraper.source)
            errors.append(msg)

    # 2. Filter.
    filtered = _filter_raw(raw, prefs)

    # 3. Tailor + persist (we persist everything, even the ones we'll skip
    #    at the cap, so a future dashboard can see them).
    tailored: List[_ScoredTailoredJob] = []
    for r in filtered:
        try:
            tailored.append(_tailor_one(r, prefs, run_id, run_date, use_llm=use_llm))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tailoring failed for %s", r.url)
            errors.append(f"tailor {r.source}:{r.external_id or r.url}: {exc}")
            tailored.append(_failed_stub(r, run_id))

    # 4. Rank + cap. Jobs beyond `daily_cap` are marked `skipped` so they
    #    don't pollute the dashboard/email but still exist in the DB.
    tailored.sort(
        key=lambda t: (t.record.fit_score is None, -(t.record.fit_score or 0.0))
    )
    kept = [t for t in tailored if t.record.status != STATUS_FAILED][: prefs.daily_cap]
    kept_ids = {t.record.id for t in kept}

    with get_conn() as conn:
        for t in tailored:
            if t.record.status == STATUS_FAILED:
                upsert_job(conn, t.record)
                continue
            if t.record.id not in kept_ids:
                t.record.status = STATUS_SKIPPED
            upsert_job(conn, t.record)

        update_daily_run(
            conn, run_id,
            scraped=len(raw),
            tailored=sum(1 for t in tailored if t.record.status != STATUS_FAILED),
        )

    # 5. Email digest.
    email_sent = False
    if send_email:
        try:
            from app.notify.email import send_digest  # lazy import
            with get_conn() as conn:
                jobs_today = [
                    j for j in list_jobs_for_date(conn, run_id)
                    if j.status not in (STATUS_SKIPPED, STATUS_FAILED)
                ]
            email_sent = bool(send_digest(jobs_today, run_date))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Email digest failed")
            errors.append(f"email: {exc}")

    # 6. Finalize daily_run row.
    with get_conn() as conn:
        update_daily_run(
            conn, run_id,
            email_sent=email_sent,
            status="complete" if not errors else "complete_with_errors",
            error="\n".join(errors) if errors else None,
        )

    return RunSummary(
        run_id=run_id,
        scraped=len(raw),
        filtered=len(filtered),
        tailored=sum(1 for t in tailored if t.record.status != STATUS_FAILED),
        kept=len(kept),
        email_sent=email_sent,
        errors=errors,
    )


# ----------------- helpers -----------------


@dataclass
class _ScoredTailoredJob:
    record: JobRecord


def _default_scrapers(prefs: Preferences) -> List[Scraper]:
    """Pick a scraper per enabled source via the registry. When a source
    has no real implementation registered yet, the registry returns a
    FakeScraper so the pipeline always produces *something*."""
    return [get_scraper(source) for source in prefs.enabled_sources()]


def _preflight_auth(scraper_list: List[Scraper], errors: List[str]) -> List[Scraper]:
    """Drop scrapers whose persistent profile is signed out. Logs + error-list
    entry per dropped source so the failure is visible in the scheduled task
    log and in `daily_runs.error`."""
    # Lazy import so tests and `--fake` runs don't pay the Playwright import
    # cost or need browser binaries just to instantiate the runner.
    try:
        from app.scrapers.playwright_session import check_login
    except Exception:  # pragma: no cover - only hits when Playwright module is broken
        logger.exception("auth preflight: could not import check_login; skipping")
        return scraper_list

    ok: List[Scraper] = []
    for scraper in scraper_list:
        if not getattr(scraper, "requires_auth", False):
            ok.append(scraper)
            continue
        try:
            status = check_login(scraper.source)
        except Exception as exc:  # noqa: BLE001
            msg = f"{scraper.source}: auth preflight raised: {exc}"
            logger.warning(msg)
            errors.append(msg)
            continue
        if status.get("logged_in"):
            logger.info("auth preflight: %s OK", scraper.source)
            ok.append(scraper)
        else:
            notes = status.get("notes") or status.get("error") or "no session"
            msg = (
                f"{scraper.source}: not logged in ({notes}); dropping source. "
                f"Run: python scripts/login_once.py {scraper.source}"
            )
            logger.warning(msg)
            errors.append(msg)
    return ok


def _filter_raw(raw: List[RawJob], prefs: Preferences) -> List[RawJob]:
    out: List[RawJob] = []
    seen: set[str] = set()
    for r in raw:
        if not r.url or not r.title or not r.jd_full:
            continue
        key = f"{r.source}||{r.url}"
        if key in seen:
            continue
        seen.add(key)
        if prefs.is_excluded_company(r.company):
            continue
        if prefs.mentions_excluded_keyword(r.title) or prefs.mentions_excluded_keyword(r.jd_full):
            continue
        if not prefs.location_is_acceptable(r.location):
            continue
        out.append(r)
    return out


def _tailor_one(
    raw: RawJob,
    prefs: Preferences,
    run_id: str,
    run_date: date,
    *,
    use_llm: bool,
) -> _ScoredTailoredJob:
    """Produce a fully tailored package for a single RawJob: resume draft,
    resume.docx, cover_letter.docx, screening.json, metadata.json."""
    classification = classify_job(raw.jd_full)
    archetype_id = classification.archetype_id

    fit = compute_fit_score(raw.jd_full)

    draft = generate_resume_draft(
        job_description=raw.jd_full,
        archetype_id=archetype_id,
        use_llm=use_llm,
    )

    job_id = JobRecord.make_id(raw.source, raw.url)
    job_dir = artifact_dir_for(job_id, run_date)

    resume_bytes = generate_tailored_resume_bytes(
        archetype_id=archetype_id,
        job_description=raw.jd_full,
        use_llm=use_llm,
    )
    (job_dir / "resume.docx").write_bytes(resume_bytes)

    cover_text = build_cover_letter(
        candidate_name=prefs.candidate.name,
        company=raw.company,
        title=raw.title,
        archetype_id=archetype_id,
        job_description=raw.jd_full,
        use_llm=use_llm,
    )
    write_cover_letter_docx(cover_text, job_dir / "cover_letter.docx")

    questions = extract_questions(raw.jd_full)
    screening = answer_questions(questions, archetype_id=archetype_id, use_llm=use_llm)
    (job_dir / "screening.json").write_text(
        json.dumps(screening, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    metadata = {
        "job_id": job_id,
        "source": raw.source,
        "url": raw.url,
        "apply_url": raw.apply_url or raw.url,
        "title": raw.title,
        "company": raw.company,
        "location": raw.location,
        "salary_raw": raw.salary_raw,
        "archetype_id": archetype_id,
        "fit_score": fit.score,
        "fit_band": fit.band,
        "summary": draft.get("summary"),
        "selected_bullets": draft.get("selected_bullets"),
        "draft_notes": draft.get("notes"),
        "llm_applied": draft.get("llm_applied", False),
        "discovered_at": raw.posted_at.isoformat() if raw.posted_at else None,
        "cover_letter_preview": cover_text[:400],
    }
    (job_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    record = JobRecord(
        id=job_id,
        source=raw.source,
        url=raw.url,
        external_id=raw.external_id,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        salary_raw=raw.salary_raw,
        posted_at=raw.posted_at,
        jd_full=raw.jd_full,
        archetype_id=archetype_id,
        fit_score=fit.score,
        artifact_dir=str(job_dir),
        screening=screening,
        status=STATUS_NEW,
        daily_run_id=run_id,
    )
    return _ScoredTailoredJob(record=record)


def _failed_stub(raw: RawJob, run_id: str) -> _ScoredTailoredJob:
    """We still persist a row so the user can see *why* a JD was lost."""
    job_id = JobRecord.make_id(raw.source, raw.url)
    return _ScoredTailoredJob(
        record=JobRecord(
            id=job_id,
            source=raw.source,
            url=raw.url,
            external_id=raw.external_id,
            title=raw.title or "(failed)",
            company=raw.company or "(unknown)",
            location=raw.location,
            salary_raw=raw.salary_raw,
            jd_full=raw.jd_full,
            status=STATUS_FAILED,
            daily_run_id=run_id,
        )
    )


__all__ = ["run_daily", "RunSummary"]
