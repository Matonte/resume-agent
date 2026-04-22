"""Storage CRUD tests against an ephemeral SQLite file."""

from __future__ import annotations

from datetime import datetime

from app.storage.db import (
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    DailyRun,
    JobRecord,
    artifact_dir_for,
    get_conn,
    insert_daily_run,
    list_jobs_for_date,
    load_job,
    update_daily_run,
    update_job_status,
    upsert_job,
)


def _sample_job(run_id: str = "2026-04-22", source: str = "fake") -> JobRecord:
    return JobRecord(
        id=JobRecord.make_id(source, "https://example.com/jobs/1"),
        source=source,
        url="https://example.com/jobs/1",
        title="Senior Backend Engineer",
        company="Acme",
        location="New York, NY",
        jd_full="lorem ipsum " * 40,
        archetype_id="B_fintech_transaction_systems",
        fit_score=8.4,
        daily_run_id=run_id,
    )


def test_insert_and_load_job(isolated_outputs) -> None:
    job = _sample_job()
    with get_conn() as conn:
        upsert_job(conn, job)
        loaded = load_job(conn, job.id)

    assert loaded is not None
    assert loaded.id == job.id
    assert loaded.fit_score == 8.4
    assert loaded.status == STATUS_NEW


def test_list_jobs_for_date_ranks_by_fit(isolated_outputs) -> None:
    run_id = "2026-04-22"
    low = _sample_job(run_id=run_id)
    low.fit_score = 5.0
    high = JobRecord(
        id=JobRecord.make_id("fake", "https://example.com/jobs/2"),
        source="fake",
        url="https://example.com/jobs/2",
        title="Staff Engineer",
        company="Acme",
        jd_full="x " * 40,
        fit_score=9.1,
        daily_run_id=run_id,
    )
    with get_conn() as conn:
        upsert_job(conn, low)
        upsert_job(conn, high)
        rows = list_jobs_for_date(conn, run_id)

    assert [r.fit_score for r in rows] == [9.1, 5.0]


def test_update_job_status_and_guard(isolated_outputs) -> None:
    job = _sample_job()
    with get_conn() as conn:
        upsert_job(conn, job)
        update_job_status(conn, job.id, STATUS_APPROVED)
        loaded = load_job(conn, job.id)

    assert loaded is not None and loaded.status == STATUS_APPROVED


def test_upsert_preserves_terminal_status(isolated_outputs) -> None:
    """Re-discovering a job that we've already submitted must not reset its
    status back to `new`."""
    run_id = "2026-04-22"
    job = _sample_job(run_id=run_id)

    with get_conn() as conn:
        upsert_job(conn, job)
        update_job_status(conn, job.id, STATUS_SUBMITTED)

        # Scraper rediscovers it tomorrow with status=new.
        job.daily_run_id = "2026-04-23"
        job.status = STATUS_NEW
        upsert_job(conn, job)

        refreshed = load_job(conn, job.id)
    assert refreshed is not None
    assert refreshed.status == STATUS_SUBMITTED


def test_daily_run_crud(isolated_outputs) -> None:
    run = DailyRun(id="2026-04-22", ran_at=datetime.utcnow())
    with get_conn() as conn:
        insert_daily_run(conn, run)
        update_daily_run(conn, run.id, scraped=12, tailored=10, email_sent=True, status="complete")

        row = conn.execute("SELECT * FROM daily_runs WHERE id=?", (run.id,)).fetchone()

    assert row["scraped"] == 12
    assert row["tailored"] == 10
    assert row["email_sent"] == 1
    assert row["status"] == "complete"


def test_artifact_dir_for_creates_folder(isolated_outputs) -> None:
    path = artifact_dir_for("abc123")
    assert path.exists() and path.is_dir()
    assert path.name == "job_abc123"
