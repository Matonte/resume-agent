"""End-to-end runner test with mocked scrapers (no network, no Playwright).

Verifies:
    - top-N selection by fit_score,
    - artifact folder + files created,
    - DB rows written + status lifecycle correct,
    - email is skipped (SMTP not configured in tests).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import pytest

from app.jobs.preferences import Preferences
from app.jobs.runner import run_daily
from app.scrapers.base import RawJob
from app.storage.db import (
    STATUS_NEW,
    STATUS_SKIPPED,
    get_conn,
    list_jobs_for_date,
)


class _StubScraper:
    def __init__(self, source: str, jobs: List[RawJob]) -> None:
        self.source = source
        self._jobs = jobs

    def discover(self, preferences) -> List[RawJob]:
        return list(self._jobs)


def _raw(source: str, i: int) -> RawJob:
    return RawJob(
        source=source,
        url=f"https://{source}.test/jobs/{i}",
        title="Senior Backend Engineer, Payments",
        company=f"Acme {i}",
        jd_full=(
            "Senior Backend Engineer for our high-throughput distributed "
            "payments platform. You will build event-driven backend services "
            "on AWS, Kafka, and microservices. Strong fintech and "
            "entitlements background preferred. " * 4
        ),
        location="New York, NY",
        external_id=f"{source}-{i}",
        posted_at=datetime.utcnow(),
    )


def test_run_daily_end_to_end(isolated_outputs: Path) -> None:
    scrapers = [
        _StubScraper("linkedin", [_raw("linkedin", 1), _raw("linkedin", 2)]),
        _StubScraper("wttj", [_raw("wttj", 3), _raw("wttj", 4)]),
        _StubScraper("jobright", [_raw("jobright", 5)]),
    ]
    prefs = Preferences.model_validate({
        "targets": {"locations": ["New York, NY"], "remote_ok": True},
        "sources": {
            "linkedin": {"enabled": True, "queries": ["x"]},
            "wttj": {"enabled": True, "queries": ["x"]},
            "jobright": {"enabled": True, "queries": ["x"]},
        },
        "daily_cap": 3,
        "per_source_cap": 5,
    })

    summary = run_daily(
        scrapers=scrapers,
        preferences=prefs,
        send_email=False,
        use_llm=False,
    )

    assert summary.scraped == 5
    assert summary.filtered == 5
    assert summary.tailored == 5
    assert summary.kept == 3
    assert summary.email_sent is False
    assert summary.errors == []

    # DB reflects both kept and skipped.
    with get_conn() as conn:
        jobs = list_jobs_for_date(conn, summary.run_id)
    statuses = [j.status for j in jobs]
    assert statuses.count(STATUS_NEW) == 3
    assert statuses.count(STATUS_SKIPPED) == 2

    # Artifact folders exist for all 5.
    for j in jobs:
        assert j.artifact_dir, "artifact_dir should be set"
        folder = Path(j.artifact_dir)
        assert (folder / "resume.docx").exists()
        assert (folder / "cover_letter.docx").exists()
        assert (folder / "screening.json").exists()
        assert (folder / "metadata.json").exists()


def test_run_daily_records_scraper_failure(isolated_outputs: Path) -> None:
    class _Broken:
        source = "jobright"

        def discover(self, preferences):
            raise RuntimeError("scraper went boom")

    good = _StubScraper("linkedin", [_raw("linkedin", 1)])
    broken = _Broken()

    prefs = Preferences.model_validate({
        "targets": {"locations": ["New York, NY"], "remote_ok": True},
        "sources": {
            "linkedin": {"enabled": True},
            "jobright": {"enabled": True},
        },
        "daily_cap": 5,
        "per_source_cap": 5,
    })

    summary = run_daily(
        scrapers=[good, broken],
        preferences=prefs,
        send_email=False,
        use_llm=False,
    )

    assert summary.scraped == 1  # only good returned
    assert summary.kept == 1
    assert any("jobright" in e for e in summary.errors)


def test_auth_preflight_drops_logged_out_sources(isolated_outputs: Path, monkeypatch) -> None:
    """A scraper with `requires_auth=True` whose `check_login` reports
    logged-out should be skipped with an error entry, while other sources
    keep running."""

    class _AuthStub:
        requires_auth = True

        def __init__(self, source: str, jobs):
            self.source = source
            self._jobs = jobs
            self.called = False

        def discover(self, preferences):
            self.called = True
            return list(self._jobs)

    def _fake_check_login(site: str, **kwargs) -> dict:
        return {
            "site": site,
            "logged_in": site == "jobright",
            "final_url": "https://example.com",
            "notes": "ok" if site == "jobright" else "redirected to sign-in",
            "error": None,
        }

    # Patch the symbol that `_preflight_auth` imports lazily.
    from app.scrapers import playwright_session

    monkeypatch.setattr(playwright_session, "check_login", _fake_check_login)

    good = _AuthStub("jobright", [_raw("jobright", 1)])
    dead = _AuthStub("linkedin", [_raw("linkedin", 2)])

    prefs = Preferences.model_validate({
        "targets": {"locations": ["New York, NY"], "remote_ok": True},
        "sources": {
            "jobright": {"enabled": True},
            "linkedin": {"enabled": True},
        },
        "daily_cap": 5,
        "per_source_cap": 5,
    })

    summary = run_daily(
        scrapers=[good, dead],
        preferences=prefs,
        send_email=False,
        use_llm=False,
        check_auth=True,
    )

    assert good.called, "logged-in source should still run"
    assert not dead.called, "logged-out source should be dropped"
    assert any("linkedin" in e and "not logged in" in e for e in summary.errors)
    assert summary.kept == 1


def test_run_daily_filters_excluded_company(isolated_outputs: Path) -> None:
    good = _raw("linkedin", 1)
    bad = _raw("linkedin", 2)
    bad.company = "Bad Corp"

    scrapers = [_StubScraper("linkedin", [good, bad])]

    prefs = Preferences.model_validate({
        "targets": {"locations": ["New York, NY"]},
        "exclude": {"companies": ["Bad Corp"]},
        "sources": {"linkedin": {"enabled": True}},
        "daily_cap": 5,
        "per_source_cap": 5,
    })

    summary = run_daily(
        scrapers=scrapers,
        preferences=prefs,
        send_email=False,
        use_llm=False,
    )

    assert summary.scraped == 2
    assert summary.filtered == 1
    assert summary.kept == 1
