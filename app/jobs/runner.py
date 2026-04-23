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

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Sequence

from app.config import settings
from app.jobs.preferences import Preferences, load_preferences, merge_preferences_candidate
from app.jobs.tailor import tailor_job_from_raw
from app.scrapers.base import RawJob, Scraper
from app.scrapers.registry import get_scraper
from app.services.data_context import candidate_data_dir
from app.storage.accounts import ResumeProfile, get_profile, get_user_by_id
from app.storage.db import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    DailyRun,
    JobRecord,
    get_conn,
    insert_daily_run,
    list_jobs_for_date,
    update_daily_run,
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
    user_id: Optional[int] = None,
    active_profile: Optional[ResumeProfile] = None,
) -> RunSummary:
    uid = user_id if user_id is not None else settings.daily_run_user_id
    prefs = preferences or load_preferences()
    if active_profile is None and uid:
        with get_conn() as conn:
            u = get_user_by_id(conn, uid)
            if u and u.active_profile_id:
                active_profile = get_profile(conn, u.active_profile_id)
    prefs = merge_preferences_candidate(prefs, active_profile)
    prof_dir = (
        active_profile.effective_candidate_dir() if active_profile else None
    )

    def _run() -> RunSummary:
        run_date = for_date or (now.date() if now else datetime.utcnow().date())
        run_id = DailyRun.make_id(run_date, user_id=uid)

        run = DailyRun(
            id=run_id,
            ran_at=now or datetime.utcnow(),
            status="running",
            user_id=uid,
        )
        with get_conn() as conn:
            insert_daily_run(conn, run)

        scraper_list = (
            list(scrapers) if scrapers is not None else _default_scrapers(prefs)
        )

        errors: List[str] = []

        # 0. Auth preflight.
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

        # 3. Tailor + persist.
        tailored: List[_ScoredTailoredJob] = []
        for r in filtered:
            try:
                tailored.append(
                    _tailor_one(
                        r, prefs, run_id, run_date, user_id=uid, use_llm=use_llm
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Tailoring failed for %s", r.url)
                errors.append(
                    f"tailor {r.source}:{r.external_id or r.url}: {exc}"
                )
                tailored.append(_failed_stub(r, run_id, user_id=uid))

        # 4. Rank + cap.
        tailored.sort(
            key=lambda t: (
                t.record.fit_score is None,
                -(t.record.fit_score or 0.0),
            )
        )
        kept = [
            t for t in tailored if t.record.status != STATUS_FAILED
        ][: prefs.daily_cap]
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
                conn,
                run_id,
                scraped=len(raw),
                tailored=sum(
                    1 for t in tailored if t.record.status != STATUS_FAILED
                ),
            )

        # 5. Email digest.
        email_sent = False
        if send_email:
            try:
                from app.notify.email import send_digest  # lazy import
                with get_conn() as conn:
                    jobs_today = [
                        j
                        for j in list_jobs_for_date(
                            conn, run_id, user_id=uid
                        )
                        if j.status
                        not in (STATUS_SKIPPED, STATUS_FAILED)
                    ]
                email_sent = bool(send_digest(jobs_today, run_date))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Email digest failed")
                errors.append(f"email: {exc}")

        # 6. Finalize daily_run row.
        with get_conn() as conn:
            update_daily_run(
                conn,
                run_id,
                email_sent=email_sent,
                status="complete" if not errors else "complete_with_errors",
                error="\n".join(errors) if errors else None,
            )

        return RunSummary(
            run_id=run_id,
            scraped=len(raw),
            filtered=len(filtered),
            tailored=sum(
                1 for t in tailored if t.record.status != STATUS_FAILED
            ),
            kept=len(kept),
            email_sent=email_sent,
            errors=errors,
        )

    with candidate_data_dir(prof_dir):
        return _run()


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
    user_id: int,
    use_llm: bool,
) -> _ScoredTailoredJob:
    """Produce a fully tailored package for a single RawJob.

    Thin wrapper around `app.jobs.tailor.tailor_job_from_raw` so both the
    daily runner and the manual `/tailor` endpoint share exactly the same
    tailoring pipeline.
    """
    tailored = tailor_job_from_raw(
        raw,
        prefs,
        run_id=run_id,
        run_date=run_date,
        user_id=user_id,
        use_llm=use_llm,
    )
    return _ScoredTailoredJob(record=tailored.record)


def _failed_stub(raw: RawJob, run_id: str, *, user_id: int) -> _ScoredTailoredJob:
    """We still persist a row so the user can see *why* a JD was lost."""
    job_id = JobRecord.make_id(raw.source, raw.url, user_id=user_id)
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
            user_id=user_id,
        )
    )


__all__ = ["run_daily", "RunSummary"]
