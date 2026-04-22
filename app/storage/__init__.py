"""Persistence layer for the daily job agent.

A single SQLite file at `outputs/jobs.sqlite` holds:
- `jobs`        : one row per discovered (JD, source) pair.
- `daily_runs`  : one row per morning orchestration run.

Everything under `outputs/` is gitignored and safe to wipe.
"""

from app.storage.db import (
    JobRecord,
    DailyRun,
    artifact_dir_for,
    get_conn,
    init_db,
    insert_daily_run,
    list_jobs_for_date,
    load_job,
    update_daily_run,
    update_job_status,
    upsert_job,
)

__all__ = [
    "JobRecord",
    "DailyRun",
    "artifact_dir_for",
    "get_conn",
    "init_db",
    "insert_daily_run",
    "list_jobs_for_date",
    "load_job",
    "update_daily_run",
    "update_job_status",
    "upsert_job",
]
