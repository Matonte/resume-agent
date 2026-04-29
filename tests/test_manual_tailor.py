"""Tests for the /api/manual-tailor endpoint and app.services.jd_fetcher."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import jd_fetcher
from app.storage.db import DailyRun, get_conn, load_job


@pytest.fixture
def client(isolated_outputs) -> TestClient:
    return TestClient(app)


# Enough text to pass the 100-char minimum and look like a real JD.
_JD_TEXT = (
    "Stripe is looking for a Senior Backend Engineer to build "
    "high-throughput payment infrastructure across multiple data "
    "centers. You will work on distributed systems, event-driven "
    "pipelines, low-latency APIs, and reliability engineering. "
    "Strong experience with Go, Java, or Python is required, plus "
    "hands-on work with Kafka, Spanner, or equivalent. Bonus: AWS, "
    "Terraform, Kubernetes. 11+ years experience preferred."
)


def test_manual_tailor_get_shows_usage_hints(client):
    resp = client.get("/api/manual-tailor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["method"] == "POST"
    assert data["ui"] == "/tailor"


def test_manual_tailor_alias_path_redirects_to_ui(client):
    resp = client.get("/manual-tailor", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers.get("location") == "/tailor"


def test_manual_tailor_description_only_path(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.manual.advise_for_job_context",
        lambda **kwargs: None,
    )
    resp = client.post(
        "/api/manual-tailor",
        json={
            "description": _JD_TEXT,
            "company": "Stripe",
            "title": "Senior Backend Engineer",
            "location": "New York, NY",
            "use_llm": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["job_id"]
    assert data["title"] == "Senior Backend Engineer"
    assert data["company"] == "Stripe"
    assert data["location"] == "New York, NY"
    assert data["archetype_id"]  # classifier always returns something
    assert data["fit_score"] is not None
    assert data["artifact_urls"]["resume"].endswith("resume.docx")
    assert data["artifact_urls"]["cover_letter"].endswith("cover_letter.docx")
    assert data.get("meeting_advice") is None

    # Persisted to DB?
    with get_conn() as conn:
        record = load_job(conn, data["job_id"])
    assert record is not None
    assert record.source == "manual"
    assert record.artifact_dir
    assert (Path(record.artifact_dir) / "resume.docx").exists()
    assert (Path(record.artifact_dir) / "cover_letter.docx").exists()
    assert (Path(record.artifact_dir) / "screening.json").exists()
    assert (Path(record.artifact_dir) / "metadata.json").exists()

    # And the artifact-download endpoint should serve the files.
    dl = client.get(data["artifact_urls"]["resume"])
    assert dl.status_code == 200
    assert len(dl.content) > 0


def test_manual_tailor_meeting_advice_in_response(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.manual.advise_for_job_context",
        lambda **kwargs: {"advice": {"opening_move": "Hello", "do": ["Be brief"]}},
    )
    resp = client.post(
        "/api/manual-tailor",
        json={
            "description": _JD_TEXT,
            "company": "Stripe",
            "title": "Senior Backend Engineer",
            "use_llm": False,
            "meeting_advisor": True,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["meeting_advice"] and data["meeting_advice"]["advice"]["opening_move"] == "Hello"


def test_manual_tailor_rejects_empty_body(client):
    resp = client.post("/api/manual-tailor", json={})
    assert resp.status_code == 400
    assert "url" in resp.json()["detail"] or "description" in resp.json()["detail"]


def test_manual_tailor_rejects_short_description(client):
    resp = client.post(
        "/api/manual-tailor",
        json={"description": "too short"},
    )
    assert resp.status_code == 422


def test_manual_tailor_url_path_uses_fetcher(monkeypatch, client):
    """When only a URL is provided, we should call jd_fetcher and pull
    the description / title / company from the parsed page."""
    from app.scrapers.base import RawJob

    monkeypatch.setattr(
        "app.routers.manual.advise_for_job_context",
        lambda **kwargs: None,
    )

    def fake_fetch(url, *, timeout=15.0):
        return jd_fetcher.FetchedJob(
            raw=RawJob(
                source="manual",
                url=url,
                title="Backend Engineer",
                company="Acme",
                jd_full=_JD_TEXT,
            ),
            error=None,
        )

    monkeypatch.setattr(jd_fetcher, "fetch_jd", fake_fetch)
    # The endpoint imports fetch_jd lazily, so patch the module-level symbol
    # the endpoint actually resolves:
    import app.routers.manual as manual_mod
    monkeypatch.setattr(jd_fetcher, "fetch_jd", fake_fetch, raising=True)

    resp = client.post(
        "/api/manual-tailor",
        json={"url": "https://example.com/jobs/42", "use_llm": False},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "Backend Engineer"
    assert data["company"] == "Acme"


def test_manual_tailor_url_fetch_failure_without_description(monkeypatch, client):
    """When the URL fetch fails and no description is pasted, we return 422."""
    from app.scrapers.base import RawJob

    def failing_fetch(url, *, timeout=15.0):
        return jd_fetcher.FetchedJob(
            raw=RawJob(source="manual", url=url, title="", company="", jd_full=""),
            error="HTTP 403 from example.com; the page may require login",
        )

    monkeypatch.setattr(jd_fetcher, "fetch_jd", failing_fetch)

    resp = client.post(
        "/api/manual-tailor",
        json={"url": "https://example.com/jobs/42"},
    )
    assert resp.status_code == 422
    assert "description" in resp.json()["detail"].lower()


def test_jd_fetcher_guesses_company_from_url():
    # We call the private helpers directly; no network.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
    assert jd_fetcher._guess_company(soup, "https://boards.greenhouse.io/stripe/jobs/1") == "Stripe"
    assert jd_fetcher._guess_company(soup, "https://jobs.lever.co/Plaid/abc") == "Plaid"
    assert jd_fetcher._guess_company(
        soup,
        "https://www.welcometothejungle.com/en/companies/datadog/jobs/software-engineer",
    ) == "Datadog"
