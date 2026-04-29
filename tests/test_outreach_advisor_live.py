"""Opt-in live smoke test: resume-agent → flask_sample meeting_advisor.

Prerequisites (flask_sample repo):
  - WhoIsWhat and WhoIsHoss reachable from meeting_advisor (local URLs in its .env)
  - OPENAI_API_KEY set for meeting_advisor’s own process
  - Server running: ``python run_meeting_advisor.py`` (default http://127.0.0.1:5003)

Run (PowerShell from resume-agent repo)::

    $env:MEETING_ADVISOR_URL = "http://127.0.0.1:5003"
    $env:RUN_MEETING_ADVISOR_LIVE = "1"
    pytest tests/test_outreach_advisor_live.py -v

Or one line::

    $env:MEETING_ADVISOR_URL="http://127.0.0.1:5003"; $env:RUN_MEETING_ADVISOR_LIVE="1"; pytest tests/test_outreach_advisor_live.py -v
"""

from __future__ import annotations

import os

import pytest

from app.config import settings
from app.services.outreach_enrich import _call_meeting_advisor, enrich_outreach_hits
from app.services.outreach_search import WebSearchHit

pytestmark = pytest.mark.advisor_live


def _advisor_live_allowed() -> bool:
    return bool(settings.meeting_advisor_url) and os.environ.get(
        "RUN_MEETING_ADVISOR_LIVE", ""
    ).strip().lower() in ("1", "true", "yes")


@pytest.mark.skipif(
    not _advisor_live_allowed(),
    reason="Set MEETING_ADVISOR_URL (e.g. http://127.0.0.1:5003) and RUN_MEETING_ADVISOR_LIVE=1",
)
def test_live_meeting_advisor_http_smoke() -> None:
    """Direct POST to /api/v1/advise; checks JSON shape (slow, real network)."""
    hit = WebSearchHit(
        title="Alex Rivera — Technical Recruiter",
        url="https://example.com/in/alex",
        snippet="Hiring senior backend engineers for a payments team.",
        engine="test",
        query="test query",
    )
    resp = _call_meeting_advisor(
        hit,
        "Series B fintech, payments, NYC or remote US",
        "recruiter",
    )
    assert resp is not None, (
        "No JSON response — is meeting_advisor up? Are WHOISWHAT / WhoIsHoss URLs and "
        "OPENAI_API_KEY configured for that process?"
    )
    assert "advice" in resp, f"Unexpected payload keys: {list(resp.keys())}"
    advice = resp["advice"]
    assert isinstance(advice, dict)
    assert isinstance(advice.get("opening_move"), str)
    assert len((advice.get("opening_move") or "").strip()) > 5


@pytest.mark.skipif(
    not _advisor_live_allowed(),
    reason="Set MEETING_ADVISOR_URL and RUN_MEETING_ADVISOR_LIVE=1",
)
def test_live_enrich_pipeline_without_resume_llm() -> None:
    """Full enrich path with use_llm=False (only meeting_advisor + heuristics)."""
    hit = WebSearchHit(
        title="Jamie Chen | Engineering Manager, Platform",
        url="https://example.com/in/jamie",
        snippet="Leads platform reliability and internal tooling.",
        engine="test",
        query="q",
    )
    dossiers = enrich_outreach_hits(
        [hit],
        "Platform / infra roles, Python and Kubernetes",
        use_llm=False,
    )
    assert len(dossiers) == 1
    d = dossiers[0]
    assert d.whoiswhat_raw and isinstance(d.whoiswhat_raw, dict)
    assert "meeting_advisor" in d.whoiswhat_raw
    ma = d.whoiswhat_raw["meeting_advisor"]
    assert isinstance(ma.get("advice"), dict)
    assert len((d.combined_opening or "").strip()) > 5
