"""Tests for per-job outreach notes hook."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.jobs.job_outreach_notes import maybe_write_job_outreach_notes, outreach_badge_for_job
from app.jobs.preferences import OutreachForJobConfig, Preferences
from app.scrapers.base import RawJob
from app.storage.db import JobRecord
from app.services.outreach_enrich import OutreachContactDossier, OutreachStakeholderNotes
from app.services.outreach_search import CombinationSearchResult, WebSearchHit


def _raw() -> RawJob:
    return RawJob(
        source="fake",
        url="https://example.com/j/1",
        title="Senior Backend Engineer",
        company="Acme Pay",
        jd_full="We need distributedsystems and payments experience.",
    )


def test_outreach_skipped_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prefs = Preferences(outreach_for_job=OutreachForJobConfig(enabled=False))
    maybe_write_job_outreach_notes(_raw(), tmp_path, prefs, use_llm=False)
    assert not (tmp_path / "outreach_contacts.json").exists()


def test_outreach_skipped_without_search_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={
            "google_cse_api_key": "",
            "google_cse_cx": "",
            "bing_search_key": "",
        }
    )
    monkeypatch.setattr("app.jobs.job_outreach_notes.settings", s)
    prefs = Preferences(outreach_for_job=OutreachForJobConfig(enabled=True))
    maybe_write_job_outreach_notes(_raw(), tmp_path, prefs, use_llm=False)
    assert not (tmp_path / "outreach_contacts.json").exists()


def test_outreach_writes_when_recruiter_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={"google_cse_api_key": "k", "google_cse_cx": "cx", "bing_search_key": ""}
    )
    monkeypatch.setattr("app.jobs.job_outreach_notes.settings", s)

    hit = WebSearchHit(
        title="Jamie Smith — Talent Partner at Acme",
        url="https://linkedin.com/in/jamie",
        snippet="Hiring engineers",
        engine="g",
        query="q",
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.run_combination_search",
        lambda desc: CombinationSearchResult(queries=["q"], hits=[hit], errors=[]),
    )

    dossier = OutreachContactDossier(
        title=hit.title,
        url=hit.url,
        snippet=hit.snippet,
        source_query=hit.query,
        source_engine=hit.engine,
        inferred_primary_role="recruiter",
        recruiter=OutreachStakeholderNotes(summary="TA", how_to_talk=["Say hi"]),
        hiring_manager=OutreachStakeholderNotes(),
        combined_opening="Hello Jamie",
        whoiswhat_raw=None,
        llm_applied=False,
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.enrich_outreach_hits",
        lambda hits, desc, use_llm=True: [dossier],
    )

    meta = {"job_id": "abc", "company": "Acme Pay"}
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    prefs = Preferences(outreach_for_job=OutreachForJobConfig(enabled=True, max_search_hits=5))
    maybe_write_job_outreach_notes(_raw(), tmp_path, prefs, use_llm=False)

    data = json.loads((tmp_path / "outreach_contacts.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["inferred_primary_role"] == "recruiter"
    meta2 = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta2["outreach"]["outreach_written"] is True
    assert meta2["outreach"]["outreach_contact_count"] == 1


def test_outreach_no_file_when_only_engineer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={"google_cse_api_key": "k", "google_cse_cx": "cx", "bing_search_key": ""}
    )
    monkeypatch.setattr("app.jobs.job_outreach_notes.settings", s)
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.run_combination_search",
        lambda desc: CombinationSearchResult(
            queries=["q"],
            hits=[
                WebSearchHit(
                    title="Staff Engineer",
                    url="https://x.com",
                    snippet="I build APIs",
                    engine="g",
                    query="q",
                )
            ],
            errors=[],
        ),
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.enrich_outreach_hits",
        lambda hits, desc, use_llm=True: [
            OutreachContactDossier(
                title="Staff Engineer",
                url="https://x.com",
                snippet="I build APIs",
                inferred_primary_role="engineer",
            )
        ],
    )
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    prefs = Preferences(outreach_for_job=OutreachForJobConfig(enabled=True))
    maybe_write_job_outreach_notes(_raw(), tmp_path, prefs, use_llm=False)
    assert not (tmp_path / "outreach_contacts.json").exists()


def test_outreach_badge_reads_metadata(tmp_path: Path) -> None:
    art = tmp_path / "job1"
    art.mkdir()
    (art / "outreach_contacts.json").write_text(json.dumps([{"title": "TA"}]), encoding="utf-8")
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
        id="z9",
        source="fake",
        url="https://example.com",
        title="T",
        company="C",
        jd_full="j",
        daily_run_id="2026-01-01",
        artifact_dir=str(art),
    )
    badge = outreach_badge_for_job(job)
    assert badge and badge["contact_count"] == 1
    assert badge["roles"] == ["recruiter"]
