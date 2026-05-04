"""Tests for bundled public profile (people-intel + Meeting Advisor orchestration)."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.person_profile_bundle import (
    PersonProfileBundleParams,
    ProfileSnippet,
    build_person_profile_bundle,
    build_practical_readout,
)

client = TestClient(app)


def test_bundle_rejects_short_name() -> None:
    out = build_person_profile_bundle(PersonProfileBundleParams(name="x"))
    assert out.get("error")


def test_practical_readout_merges_intel_and_meeting() -> None:
    pi = {
        "likely_role": "Engineering Manager",
        "confidence": 0.81,
        "professional_interests": ["platform"],
        "communication_style_signals": ["technical"],
        "safe_outreach_angle": "Mention reliability.",
        "stakeholder_likelihood": {"recruiter": 0.1, "hiring_manager": 0.85, "decision_maker": 0.6},
    }
    ma = {
        "k_profile": {"classification_code": "K2", "classification_label": "Example"},
        "hoss_profile": {"display_label": "Moderate", "hoss_level": 3},
        "advice": {
            "risk_level": "medium",
            "opening_move": "Hello — brief intro.",
            "key_observations": "Direct communicator.",
            "do": ["Be specific"],
        },
    }
    r = build_practical_readout(people_intel=pi, meeting_payload=ma, hit_count=5)
    assert r["prep_dimensions"]["k_code"] == "K2"
    assert r["prep_dimensions"]["hoss_display"] == "Moderate"
    assert r["stakeholder_skew"]["role"] == "hiring_manager"
    assert any("opening" in x.lower() for x in r["highlights_for_prep"])


def test_bundle_with_stub_meeting_advisor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(**kwargs):
        assert kwargs["subject_name"] == "Jane Doe"
        return (
            {
                "k_profile": {"classification_code": "K1"},
                "hoss_profile": {"display_label": "Low", "hoss_level": 1},
                "advice": {"risk_level": "low", "opening_move": "Hi"},
            },
            None,
        )

    monkeypatch.setattr(
        "app.services.person_profile_bundle.post_meeting_advise",
        fake_post,
    )
    s = settings.model_copy(
        update={
            "google_cse_api_key": "",
            "google_cse_cx": "",
            "bing_search_key": "",
            "whoiswhat_service_url": "",
        }
    )
    monkeypatch.setattr("app.services.person_profile_bundle.settings", s)

    out = build_person_profile_bundle(
        PersonProfileBundleParams(
            name="Jane Doe",
            run_web_search=False,
            include_people_intel=False,
            include_meeting_profiles=True,
            extra_snippets=[
                ProfileSnippet(
                    source_label="bio",
                    content="VP Engineering at Acme — backend and infra.",
                )
            ],
        )
    )
    assert out.get("error") is None
    assert out["meeting_advisor"] is not None
    assert out["meeting_advisor"]["k_profile"]["classification_code"] == "K1"
    assert out["practical_readout"]["prep_dimensions"]["k_code"] == "K1"


def test_person_profile_bundle_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.person_profile_bundle.post_meeting_advise",
        lambda **kw: ({"k_profile": {}, "hoss_profile": {}, "advice": {}}, None),
    )
    s = settings.model_copy(
        update={
            "google_cse_api_key": "",
            "google_cse_cx": "",
            "bing_search_key": "",
            "whoiswhat_service_url": "",
        }
    )
    monkeypatch.setattr("app.services.person_profile_bundle.settings", s)

    res = client.post(
        "/api/person-profile-bundle",
        json={
            "name": "Pat Lee",
            "run_web_search": False,
            "include_people_intel": False,
            "include_meeting_profiles": True,
            "extra_snippets": [{"source_label": "x", "content": "Staff engineer"}],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert "disclaimer" in body
    assert body["subject_name"] == "Pat Lee"


def test_person_profile_bundle_endpoint_bad_name() -> None:
    res = client.post(
        "/api/person-profile-bundle",
        json={"name": "y", "run_web_search": False, "include_meeting_profiles": False},
    )
    assert res.status_code == 400
