"""Dashboard API tests using FastAPI's TestClient."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.db import (
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_SKIPPED,
    STATUS_SUBMITTED,
    DailyRun,
    JobRecord,
    get_conn,
    insert_daily_run,
    upsert_job,
)


@pytest.fixture
def client(isolated_outputs) -> TestClient:
    return TestClient(app)


def _seed_job(run_id: str, *, job_id: str, fit: float, status: str = STATUS_NEW) -> JobRecord:
    job = JobRecord(
        id=job_id,
        source="fake",
        url=f"https://example.com/jobs/{job_id}",
        title="Senior Backend Engineer",
        company="Acme",
        location="New York, NY",
        jd_full="x" * 400,
        archetype_id="B_fintech_transaction_systems",
        fit_score=fit,
        status=status,
        daily_run_id=run_id,
    )
    with get_conn() as conn:
        run = DailyRun(id=run_id, ran_at=datetime.utcnow(), user_id=1)
        insert_daily_run(conn, run)
        upsert_job(conn, job)
    return job


def test_list_today_returns_seeded_jobs(client: TestClient) -> None:
    run_id = DailyRun.make_id()
    _seed_job(run_id, job_id="jobA", fit=8.1)
    _seed_job(run_id, job_id="jobB", fit=6.0)

    res = client.get("/api/jobs/today")
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == run_id
    ids = [j["id"] for j in body["jobs"]]
    assert ids == ["jobA", "jobB"]  # ordered by fit desc


def test_get_job_returns_screening_and_jd(client: TestClient) -> None:
    run_id = DailyRun.make_id()
    _seed_job(run_id, job_id="jobA", fit=8.1)
    res = client.get("/api/jobs/jobA")
    assert res.status_code == 200
    assert res.json()["id"] == "jobA"
    assert "jd_full" in res.json()


def test_approve_skip_mark_submitted_lifecycle(client: TestClient) -> None:
    run_id = DailyRun.make_id()
    _seed_job(run_id, job_id="jobA", fit=8.1)

    res = client.post("/api/jobs/jobA/approve")
    assert res.status_code == 200 and res.json()["status"] == STATUS_APPROVED

    res = client.post("/api/jobs/jobA/mark-submitted")
    assert res.status_code == 200 and res.json()["status"] == STATUS_SUBMITTED

    # skipping a submitted job is still accepted (stored as skipped), but is
    # unusual. The transition helper doesn't guard it; the dashboard's UI
    # does. We just assert the endpoint works.
    res = client.post("/api/jobs/jobA/skip")
    assert res.status_code == 200 and res.json()["status"] == STATUS_SKIPPED


def test_unknown_job_returns_404(client: TestClient) -> None:
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/approve").status_code == 404


def test_artifact_refuses_unknown_file(client: TestClient) -> None:
    run_id = DailyRun.make_id()
    _seed_job(run_id, job_id="jobA", fit=8.1)
    res = client.get("/api/jobs/jobA/artifact?file=passwd")
    assert res.status_code == 400


def test_get_job_includes_outreach_contacts(client: TestClient, tmp_path: Path) -> None:
    run_id = DailyRun.make_id()
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "outreach_contacts.json").write_text(
        json.dumps([{"title": "Pat Recruiter", "combined_opening": "Hello"}]),
        encoding="utf-8",
    )
    (art / "metadata.json").write_text(
        json.dumps(
            {
                "outreach": {
                    "outreach_written": True,
                    "outreach_contact_count": 1,
                    "outreach_roles": ["recruiter"],
                }
            }
        ),
        encoding="utf-8",
    )
    job = JobRecord(
        id="jobA",
        source="fake",
        url="https://example.com/jobs/jobA",
        title="Senior Backend Engineer",
        company="Acme",
        location="New York, NY",
        jd_full="x" * 400,
        archetype_id="B_fintech_transaction_systems",
        fit_score=8.1,
        status=STATUS_NEW,
        daily_run_id=run_id,
        artifact_dir=str(art),
    )
    with get_conn() as conn:
        run = DailyRun(id=run_id, ran_at=datetime.utcnow(), user_id=1)
        insert_daily_run(conn, run)
        upsert_job(conn, job)
    res = client.get("/api/jobs/jobA")
    assert res.status_code == 200
    body = res.json()
    assert body["outreach"]["contact_count"] == 1
    assert len(body["outreach_contacts"]) == 1


def test_artifact_outreach_contacts_json(client: TestClient, tmp_path: Path) -> None:
    run_id = DailyRun.make_id()
    art = tmp_path / "a2"
    art.mkdir()
    (art / "outreach_contacts.json").write_text("[]", encoding="utf-8")
    job = JobRecord(
        id="jobBout",
        source="fake",
        url="https://example.com/jobs/jobBout",
        title="Engineer",
        company="Beta",
        location="NY",
        jd_full="x" * 400,
        archetype_id="A_general_ai_platform",
        fit_score=7.0,
        status=STATUS_NEW,
        daily_run_id=run_id,
        artifact_dir=str(art),
    )
    with get_conn() as conn:
        run = DailyRun(id=run_id, ran_at=datetime.utcnow(), user_id=1)
        insert_daily_run(conn, run)
        upsert_job(conn, job)
    res = client.get("/api/jobs/jobBout/artifact?file=outreach_contacts.json")
    assert res.status_code == 200


def test_jobs_today_page_serves(client: TestClient) -> None:
    res = client.get("/jobs/today")
    assert res.status_code == 200
    assert "Today's queue" in res.text
