"""SQLite storage for the daily job agent.

Two tables; everything else we need is derived.

- `jobs`       : each discovered job with its status through the pipeline.
- `daily_runs` : one row per orchestration run, with counters and errors.

The DB file lives at `<outputs_dir>/jobs.sqlite`. The `outputs_dir` comes
from `app.config.settings` so tests can point it at a temp directory by
overriding the env var or passing an explicit `db_path` to `get_conn` /
`init_db`.

Status lifecycle for a job:
    new -> approved -> submitted
     \-> skipped
     \-> failed          (something broke during tailoring)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.config import settings


STATUS_NEW = "new"
STATUS_APPROVED = "approved"
STATUS_SKIPPED = "skipped"
STATUS_SUBMITTED = "submitted"
STATUS_FAILED = "failed"

_VALID_STATUSES = {
    STATUS_NEW, STATUS_APPROVED, STATUS_SKIPPED, STATUS_SUBMITTED, STATUS_FAILED,
}


# ----------------- data classes -----------------


@dataclass
class JobRecord:
    """One scraped + tailored job. `id` is deterministic so re-running the
    scrapers on the same URL is idempotent."""

    id: str
    source: str
    url: str
    title: str
    company: str
    daily_run_id: str
    external_id: Optional[str] = None
    location: Optional[str] = None
    salary_raw: Optional[str] = None
    posted_at: Optional[datetime] = None
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    jd_full: str = ""
    archetype_id: Optional[str] = None
    fit_score: Optional[float] = None
    artifact_dir: Optional[str] = None
    screening: List[Dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_NEW

    @staticmethod
    def make_id(source: str, url: str) -> str:
        return hashlib.sha1(f"{source}||{url}".encode("utf-8")).hexdigest()[:16]


@dataclass
class DailyRun:
    id: str
    ran_at: datetime = field(default_factory=datetime.utcnow)
    scraped: int = 0
    tailored: int = 0
    email_sent: bool = False
    status: str = "running"
    error: Optional[str] = None

    @staticmethod
    def make_id(for_date: Optional[date] = None) -> str:
        d = for_date or datetime.utcnow().date()
        return d.isoformat()


# ----------------- path helpers -----------------


def _resolve_db_path(db_path: Optional[Path | str]) -> Path:
    if db_path is not None:
        return Path(db_path)
    out = settings.outputs_path
    out.mkdir(parents=True, exist_ok=True)
    return out / "jobs.sqlite"


def artifact_dir_for(job_id: str, for_date: Optional[date] = None) -> Path:
    """`outputs/YYYY-MM-DD/job_<id>/` — created if it doesn't exist."""
    d = for_date or datetime.utcnow().date()
    path = settings.outputs_path / d.isoformat() / f"job_{job_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ----------------- schema -----------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    url             TEXT NOT NULL,
    external_id     TEXT,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    salary_raw      TEXT,
    posted_at       TEXT,
    discovered_at   TEXT NOT NULL,
    jd_full         TEXT NOT NULL DEFAULT '',
    archetype_id    TEXT,
    fit_score       REAL,
    artifact_dir    TEXT,
    screening_json  TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'new',
    daily_run_id    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_daily_run ON jobs(daily_run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status    ON jobs(status);

CREATE TABLE IF NOT EXISTS daily_runs (
    id          TEXT PRIMARY KEY,
    ran_at      TEXT NOT NULL,
    scraped     INTEGER NOT NULL DEFAULT 0,
    tailored    INTEGER NOT NULL DEFAULT 0,
    email_sent  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',
    error       TEXT
);
"""


def init_db(db_path: Optional[Path | str] = None) -> Path:
    """Create tables if missing. Safe to call repeatedly."""
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    return path


@contextmanager
def get_conn(db_path: Optional[Path | str] = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection with `sqlite3.Row` row factory and the schema
    already applied. Caller is responsible for commit/rollback semantics;
    this context manager just closes the connection on exit."""
    path = init_db(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ----------------- (de)serialization -----------------


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _iso_to_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _row_to_job(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        source=row["source"],
        url=row["url"],
        external_id=row["external_id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        salary_raw=row["salary_raw"],
        posted_at=_iso_to_dt(row["posted_at"]),
        discovered_at=_iso_to_dt(row["discovered_at"]) or datetime.utcnow(),
        jd_full=row["jd_full"] or "",
        archetype_id=row["archetype_id"],
        fit_score=row["fit_score"],
        artifact_dir=row["artifact_dir"],
        screening=json.loads(row["screening_json"] or "[]"),
        status=row["status"] or STATUS_NEW,
        daily_run_id=row["daily_run_id"],
    )


# ----------------- job CRUD -----------------


def upsert_job(conn: sqlite3.Connection, job: JobRecord) -> None:
    """Insert or update a job by its primary key. We never clobber a
    `submitted`/`approved` status with a re-discovery that still says `new`."""
    if job.status not in _VALID_STATUSES:
        raise ValueError(f"invalid job status: {job.status!r}")
    conn.execute(
        """
        INSERT INTO jobs (
            id, source, url, external_id, title, company, location, salary_raw,
            posted_at, discovered_at, jd_full, archetype_id, fit_score,
            artifact_dir, screening_json, status, daily_run_id
        ) VALUES (
            :id, :source, :url, :external_id, :title, :company, :location, :salary_raw,
            :posted_at, :discovered_at, :jd_full, :archetype_id, :fit_score,
            :artifact_dir, :screening_json, :status, :daily_run_id
        )
        ON CONFLICT(id) DO UPDATE SET
            source         = excluded.source,
            url            = excluded.url,
            external_id    = excluded.external_id,
            title          = excluded.title,
            company        = excluded.company,
            location       = excluded.location,
            salary_raw     = excluded.salary_raw,
            posted_at      = excluded.posted_at,
            jd_full        = excluded.jd_full,
            archetype_id   = excluded.archetype_id,
            fit_score      = excluded.fit_score,
            artifact_dir   = excluded.artifact_dir,
            screening_json = excluded.screening_json,
            daily_run_id   = excluded.daily_run_id,
            -- preserve terminal statuses, only bump new->new or fill blanks
            status         = CASE
                WHEN jobs.status IN ('approved','submitted','skipped')
                    THEN jobs.status
                ELSE excluded.status
            END
        """,
        {
            "id": job.id,
            "source": job.source,
            "url": job.url,
            "external_id": job.external_id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "salary_raw": job.salary_raw,
            "posted_at": _dt_to_iso(job.posted_at),
            "discovered_at": _dt_to_iso(job.discovered_at),
            "jd_full": job.jd_full,
            "archetype_id": job.archetype_id,
            "fit_score": job.fit_score,
            "artifact_dir": job.artifact_dir,
            "screening_json": json.dumps(job.screening or []),
            "status": job.status,
            "daily_run_id": job.daily_run_id,
        },
    )
    conn.commit()


def load_job(conn: sqlite3.Connection, job_id: str) -> Optional[JobRecord]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs_for_date(
    conn: sqlite3.Connection, daily_run_id: str
) -> List[JobRecord]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE daily_run_id = ? ORDER BY fit_score DESC, discovered_at ASC",
        (daily_run_id,),
    ).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_status(
    conn: sqlite3.Connection, job_id: str, status: str
) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid job status: {status!r}")
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()


# ----------------- daily_runs CRUD -----------------


def insert_daily_run(conn: sqlite3.Connection, run: DailyRun) -> None:
    conn.execute(
        """
        INSERT INTO daily_runs (id, ran_at, scraped, tailored, email_sent, status, error)
        VALUES (:id, :ran_at, :scraped, :tailored, :email_sent, :status, :error)
        ON CONFLICT(id) DO UPDATE SET
            ran_at = excluded.ran_at,
            scraped = excluded.scraped,
            tailored = excluded.tailored,
            email_sent = excluded.email_sent,
            status = excluded.status,
            error = excluded.error
        """,
        {
            "id": run.id,
            "ran_at": _dt_to_iso(run.ran_at),
            "scraped": run.scraped,
            "tailored": run.tailored,
            "email_sent": 1 if run.email_sent else 0,
            "status": run.status,
            "error": run.error,
        },
    )
    conn.commit()


def update_daily_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    scraped: Optional[int] = None,
    tailored: Optional[int] = None,
    email_sent: Optional[bool] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    sets: List[str] = []
    params: Dict[str, Any] = {"id": run_id}
    if scraped is not None:
        sets.append("scraped = :scraped")
        params["scraped"] = scraped
    if tailored is not None:
        sets.append("tailored = :tailored")
        params["tailored"] = tailored
    if email_sent is not None:
        sets.append("email_sent = :email_sent")
        params["email_sent"] = 1 if email_sent else 0
    if status is not None:
        sets.append("status = :status")
        params["status"] = status
    if error is not None:
        sets.append("error = :error")
        params["error"] = error
    if not sets:
        return
    conn.execute(f"UPDATE daily_runs SET {', '.join(sets)} WHERE id = :id", params)
    conn.commit()


__all__ = [
    "STATUS_NEW", "STATUS_APPROVED", "STATUS_SKIPPED",
    "STATUS_SUBMITTED", "STATUS_FAILED",
    "JobRecord", "DailyRun",
    "artifact_dir_for",
    "init_db", "get_conn",
    "upsert_job", "load_job", "list_jobs_for_date", "update_job_status",
    "insert_daily_run", "update_daily_run",
]
