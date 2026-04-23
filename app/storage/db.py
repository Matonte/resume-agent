"""SQLite storage for the daily job agent + user accounts."""

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


@dataclass
class JobRecord:
    """One scraped + tailored job."""

    id: str
    source: str
    url: str
    title: str
    company: str
    daily_run_id: str
    user_id: int = 1
    external_id: Optional[str] = None
    location: Optional[str] = None
    salary_raw: Optional[str] = None
    posted_at: Optional[datetime] = None
    #: Best URL to start an application (company ATS, etc.); falls back to `url`.
    apply_url: Optional[str] = None
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    jd_full: str = ""
    archetype_id: Optional[str] = None
    fit_score: Optional[float] = None
    artifact_dir: Optional[str] = None
    screening: List[Dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_NEW

    @staticmethod
    def make_id(source: str, url: str, user_id: int = 1) -> str:
        if user_id <= 1:
            raw = f"{source}||{url}"
        else:
            raw = f"{user_id}|{source}|{url}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class DailyRun:
    id: str
    ran_at: datetime = field(default_factory=datetime.utcnow)
    scraped: int = 0
    tailored: int = 0
    email_sent: bool = False
    status: str = "running"
    error: Optional[str] = None
    user_id: int = 1

    @staticmethod
    def make_id(for_date: Optional[date] = None, user_id: int = 1) -> str:
        d = for_date or datetime.utcnow().date()
        if user_id <= 1:
            return d.isoformat()
        return f"{d.isoformat()}__u{user_id}"


def _resolve_db_path(db_path: Optional[Path | str]) -> Path:
    if db_path is not None:
        return Path(db_path)
    out = settings.outputs_path
    out.mkdir(parents=True, exist_ok=True)
    return out / "jobs.sqlite"


def artifact_dir_for(
    job_id: str,
    for_date: Optional[date] = None,
    *,
    user_id: int = 1,
) -> Path:
    """Artifact folder. User 1 keeps legacy flat layout; others nest under u{n}."""
    d = for_date or datetime.utcnow().date()
    day_dir = settings.outputs_path / d.isoformat()
    if user_id <= 1:
        path = day_dir / f"job_{job_id}"
    else:
        path = day_dir / f"u{user_id}" / f"job_{job_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


_BASE_SCHEMA = """
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
    apply_url       TEXT,
    discovered_at   TEXT NOT NULL,
    jd_full         TEXT NOT NULL DEFAULT '',
    archetype_id    TEXT,
    fit_score       REAL,
    artifact_dir    TEXT,
    screening_json  TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'new',
    daily_run_id    TEXT NOT NULL,
    user_id         INTEGER NOT NULL DEFAULT 1
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
    error       TEXT,
    user_id     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL DEFAULT '',
    display_name        TEXT NOT NULL DEFAULT '',
    active_profile_id   INTEGER,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resume_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    use_builtin     INTEGER NOT NULL DEFAULT 0,
    candidate_name  TEXT NOT NULL DEFAULT '',
    candidate_email TEXT NOT NULL DEFAULT '',
    rel_storage     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, slug),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_profiles_user ON resume_profiles(user_id);
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {str(r[1]) for r in cur.fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_BASE_SCHEMA)
    # Upgrade path: old DBs missing columns / tables.
    jcols = _table_columns(conn, "jobs")
    if jcols and "user_id" not in jcols:
        conn.execute("ALTER TABLE jobs ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    rcols = _table_columns(conn, "daily_runs")
    if rcols and "user_id" not in rcols:
        conn.execute("ALTER TABLE daily_runs ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

    jcols2 = _table_columns(conn, "jobs")
    if jcols2 and "user_id" in jcols2:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_user_run ON jobs(user_id, daily_run_id)"
        )

    jcols_apply = _table_columns(conn, "jobs")
    if jcols_apply and "apply_url" not in jcols_apply:
        conn.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT")

    if _table_columns(conn, "users") and _table_columns(conn, "resume_profiles"):
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        if row and row[0] == 0:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, display_name, active_profile_id)
                VALUES (1, 'workspace@local', '', 'Default workspace', NULL)
                """
            )
            conn.execute(
                """
                INSERT INTO resume_profiles (
                    id, user_id, name, slug, use_builtin, candidate_name, candidate_email, rel_storage
                ) VALUES (1, 1, 'Repository data', 'default', 1, '', '', NULL)
                """
            )
            conn.execute(
                "UPDATE users SET active_profile_id = 1 WHERE id = 1"
            )
    conn.commit()


def init_db(db_path: Optional[Path | str] = None) -> Path:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _migrate(conn)
    return path


@contextmanager
def get_conn(db_path: Optional[Path | str] = None) -> Iterator[sqlite3.Connection]:
    path = init_db(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


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
    uid = row["user_id"] if "user_id" in row.keys() else 1
    apply_u = row["apply_url"] if "apply_url" in row.keys() else None
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
        apply_url=apply_u if apply_u else None,
        discovered_at=_iso_to_dt(row["discovered_at"]) or datetime.utcnow(),
        jd_full=row["jd_full"] or "",
        archetype_id=row["archetype_id"],
        fit_score=row["fit_score"],
        artifact_dir=row["artifact_dir"],
        screening=json.loads(row["screening_json"] or "[]"),
        status=row["status"] or STATUS_NEW,
        daily_run_id=row["daily_run_id"],
        user_id=int(uid),
    )


def upsert_job(conn: sqlite3.Connection, job: JobRecord) -> None:
    if job.status not in _VALID_STATUSES:
        raise ValueError(f"invalid job status: {job.status!r}")
    conn.execute(
        """
        INSERT INTO jobs (
            id, source, url, external_id, title, company, location, salary_raw,
            posted_at, apply_url, discovered_at, jd_full, archetype_id, fit_score,
            artifact_dir, screening_json, status, daily_run_id, user_id
        ) VALUES (
            :id, :source, :url, :external_id, :title, :company, :location, :salary_raw,
            :posted_at, :apply_url, :discovered_at, :jd_full, :archetype_id, :fit_score,
            :artifact_dir, :screening_json, :status, :daily_run_id, :user_id
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
            apply_url      = excluded.apply_url,
            jd_full        = excluded.jd_full,
            archetype_id   = excluded.archetype_id,
            fit_score      = excluded.fit_score,
            artifact_dir   = excluded.artifact_dir,
            screening_json = excluded.screening_json,
            daily_run_id   = excluded.daily_run_id,
            user_id        = excluded.user_id,
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
            "apply_url": job.apply_url,
            "discovered_at": _dt_to_iso(job.discovered_at),
            "jd_full": job.jd_full,
            "archetype_id": job.archetype_id,
            "fit_score": job.fit_score,
            "artifact_dir": job.artifact_dir,
            "screening_json": json.dumps(job.screening or []),
            "status": job.status,
            "daily_run_id": job.daily_run_id,
            "user_id": job.user_id,
        },
    )
    conn.commit()


def load_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    user_id: Optional[int] = None,
) -> Optional[JobRecord]:
    if user_id is not None:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs_for_date(
    conn: sqlite3.Connection,
    daily_run_id: str,
    *,
    user_id: Optional[int] = None,
) -> List[JobRecord]:
    if user_id is not None:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE daily_run_id = ? AND user_id = ?
            ORDER BY fit_score DESC, discovered_at ASC
            """,
            (daily_run_id, user_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE daily_run_id = ? ORDER BY fit_score DESC, discovered_at ASC",
            (daily_run_id,),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    user_id: Optional[int] = None,
) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid job status: {status!r}")
    if user_id is not None:
        conn.execute(
            "UPDATE jobs SET status = ? WHERE id = ? AND user_id = ?",
            (status, job_id, user_id),
        )
    else:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()


def insert_daily_run(conn: sqlite3.Connection, run: DailyRun) -> None:
    conn.execute(
        """
        INSERT INTO daily_runs (id, ran_at, scraped, tailored, email_sent, status, error, user_id)
        VALUES (:id, :ran_at, :scraped, :tailored, :email_sent, :status, :error, :user_id)
        ON CONFLICT(id) DO UPDATE SET
            ran_at = excluded.ran_at,
            scraped = excluded.scraped,
            tailored = excluded.tailored,
            email_sent = excluded.email_sent,
            status = excluded.status,
            error = excluded.error,
            user_id = excluded.user_id
        """,
        {
            "id": run.id,
            "ran_at": _dt_to_iso(run.ran_at),
            "scraped": run.scraped,
            "tailored": run.tailored,
            "email_sent": 1 if run.email_sent else 0,
            "status": run.status,
            "error": run.error,
            "user_id": run.user_id,
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
