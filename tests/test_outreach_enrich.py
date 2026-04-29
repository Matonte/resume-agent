"""Tests for outreach enrichment (whoiswhat merge + heuristics)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.services.outreach_enrich import (
    OutreachStakeholderNotes,
    _infer_role_from_title,
    _merge_meeting_advisor_into_dossier,
    _merge_stakeholder,
    _subject_name_from_hit,
    enrich_outreach_hits,
)
from app.services.outreach_search import WebSearchHit


def test_subject_name_from_hit_strips_title_noise() -> None:
    hit = WebSearchHit(
        title="Jane Doe — Senior Engineer | Acme",
        url="https://ex.com",
        snippet="",
        engine="",
        query="",
    )
    assert _subject_name_from_hit(hit) == "Jane Doe"


def test_merge_meeting_advisor_into_dossier() -> None:
    hit = WebSearchHit(
        title="Pat Lee — Engineering Manager",
        url="https://linkedin.com/in/pat",
        snippet="Leads platform team",
        engine="google",
        query="q",
    )
    from app.services.outreach_enrich import _fallback_dossier

    d = _fallback_dossier(hit, "hiring_manager")
    advisor = {
        "id": 1,
        "advice": {
            "risk_level": "low",
            "key_observations": "Direct; values specifics.",
            "do": ["Lead with relevance"],
            "dont": ["Generic flattery"],
            "watchpoints": ["Time pressure"],
            "opening_move": "Custom opening from advisor.",
            "escalation_plan": "Back off politely.",
        },
        "k_profile": {"classification_code": "K2"},
    }
    _merge_meeting_advisor_into_dossier(d, advisor)
    assert d.combined_opening == "Custom opening from advisor."
    assert d.whoiswhat_raw and "meeting_advisor" in d.whoiswhat_raw
    assert any("relevance" in x for x in d.hiring_manager.how_to_talk)


def test_enrich_calls_meeting_advisor_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={
            "meeting_advisor_url": "http://127.0.0.1:5003",
            "whoiswhat_agent_path": "",
            "whoiswhat_enrich_module": "",
        }
    )
    monkeypatch.setattr("app.services.outreach_enrich.settings", s)

    def fake_advisor(hit, company_description, inferred_role, *, client=None):
        return {
            "advice": {
                "opening_move": "Advisor says hi.",
                "key_observations": "Test.",
                "do": ["Do A"],
                "dont": ["Don't B"],
                "watchpoints": [],
                "escalation_plan": "",
            }
        }

    monkeypatch.setattr("app.services.outreach_enrich._call_meeting_advisor", fake_advisor)
    hit = WebSearchHit(
        title="Recruiter", url="https://x.com", snippet="Hiring", engine="", query=""
    )
    out = enrich_outreach_hits([hit], "Backend roles", use_llm=False)
    assert out[0].combined_opening == "Advisor says hi."
    assert out[0].whoiswhat_raw and "meeting_advisor" in out[0].whoiswhat_raw


def test_infer_role_recruiter() -> None:
    assert _infer_role_from_title("Senior Technical Recruiter", "") == "recruiter"


def test_infer_role_engineer() -> None:
    assert _infer_role_from_title("Staff Software Engineer", "") == "engineer"


def test_merge_stakeholder_combines_lists() -> None:
    a = OutreachStakeholderNotes(summary="A", how_to_talk=["one"], what_to_avoid=[])
    b = OutreachStakeholderNotes(summary="Longer B text", how_to_talk=["one", "two"], what_to_avoid=["x"])
    m = _merge_stakeholder(a, b)
    assert m.summary == "Longer B text"
    assert m.how_to_talk == ["one", "two"]
    assert m.what_to_avoid == ["x"]


def test_enrich_with_whoiswhat_stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "agent"
    pkg = root / "whoiswhat"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "enrich.py").write_text(
        """
def enrich_contacts(items, *, company_description=""):
    return [
        {
            "recruiter": {"summary": "From whoiswhat TA", "how_to_talk": ["Mention visa timing"]},
            "hiring_manager": {"summary": "", "how_to_talk": ["Ask about team topology"]},
            "inferred_primary_role": "recruiter",
        }
    ]
""",
        encoding="utf-8",
    )
    s = settings.model_copy(
        update={
            "whoiswhat_agent_path": str(root),
            "whoiswhat_enrich_module": "whoiswhat.enrich",
            "whoiswhat_enrich_callable": "enrich_contacts",
            "meeting_advisor_url": "",
        }
    )
    monkeypatch.setattr("app.services.outreach_enrich.settings", s)

    hit = WebSearchHit(
        title="Jane Doe — Talent Partner",
        url="https://example.com/in/jane",
        snippet="Hiring backend engineers at Acme",
        engine="google",
        query="q",
    )
    out = enrich_outreach_hits([hit], "Backend fintech NYC", use_llm=False)
    assert len(out) == 1
    d = out[0]
    assert "Mention visa timing" in d.recruiter.how_to_talk
    assert any("topology" in x.lower() for x in d.hiring_manager.how_to_talk)
    assert d.whoiswhat_raw is not None
    assert d.llm_applied is False


def test_enrich_without_whoiswhat(monkeypatch: pytest.MonkeyPatch) -> None:
    s = settings.model_copy(
        update={
            "whoiswhat_agent_path": "",
            "whoiswhat_enrich_module": "",
            "meeting_advisor_url": "",
        }
    )
    monkeypatch.setattr("app.services.outreach_enrich.settings", s)
    hit = WebSearchHit(
        title="Engineer",
        url="https://ex.com/x",
        snippet="Builds APIs",
        engine="bing",
        query="q",
    )
    out = enrich_outreach_hits([hit], "API platform", use_llm=False)
    assert out[0].inferred_primary_role == "engineer"
    assert out[0].whoiswhat_raw is None
