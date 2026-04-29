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
from app.services.outreach_posting_people import PostingPerson
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


def test_outreach_supplementary_hits_first_in_enrich_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Name+company search hits are merged before broad SERP hits for enrich."""
    s = settings.model_copy(
        update={"google_cse_api_key": "k", "google_cse_cx": "cx", "bing_search_key": ""}
    )
    monkeypatch.setattr("app.jobs.job_outreach_notes.settings", s)

    main_hit = WebSearchHit(
        title="Generic careers",
        url="https://example.com/careers",
        snippet="We are hiring",
        engine="g",
        query="broad",
    )
    named_hit = WebSearchHit(
        title="Pat Lee — Talent at Acme",
        url="https://linkedin.com/in/pat",
        snippet="Recruiting engineers",
        engine="g",
        query="named",
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.run_combination_search",
        lambda desc: CombinationSearchResult(queries=["broad"], hits=[main_hit], errors=[]),
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.run_supplementary_outreach_searches",
        lambda queries, results_per_query=8: CombinationSearchResult(
            queries=list(queries),
            hits=[named_hit],
            errors=[],
        ),
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.extract_people_from_posting_corpus",
        lambda *a, **k: [PostingPerson(name="Pat Lee")],
    )
    monkeypatch.setattr(
        "app.jobs.job_outreach_notes.merge_posting_corpus",
        lambda raw, fetch_apply_page=True: "noop",
    )

    seen: list = []

    def enrich(hits, desc, use_llm=True):
        seen.extend(hits)
        return [
            OutreachContactDossier(
                title=named_hit.title,
                url=named_hit.url,
                snippet=named_hit.snippet,
                inferred_primary_role="recruiter",
            )
        ]

    monkeypatch.setattr("app.jobs.job_outreach_notes.enrich_outreach_hits", enrich)

    meta = {"job_id": "abc", "company": "Acme Pay"}
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    prefs = Preferences(
        outreach_for_job=OutreachForJobConfig(
            enabled=True,
            max_search_hits=8,
            posting_people=True,
            max_followup_queries=6,
        )
    )
    maybe_write_job_outreach_notes(_raw(), tmp_path, prefs, use_llm=False)
    assert seen and seen[0].url == named_hit.url
    assert (tmp_path / "outreach_contacts.json").is_file()


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
