"""Preferences loader tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.jobs.preferences import Preferences, load_preferences


def test_load_preferences_missing_file_returns_defaults(tmp_path: Path) -> None:
    prefs = load_preferences(tmp_path / "nope.yaml")
    assert isinstance(prefs, Preferences)
    assert prefs.daily_cap == 10
    assert prefs.targets.remote_ok is True


def test_load_preferences_parses_expected_fields(tmp_path: Path) -> None:
    raw = textwrap.dedent(
        """
        targets:
          titles: ["Senior Backend Engineer"]
          locations: ["New York, NY"]
          remote_ok: false
          min_base_salary_usd: 200000
        exclude:
          companies: ["Bad Corp"]
          keywords: ["intern"]
        sources:
          jobright:
            enabled: true
            queries: ["senior backend"]
          linkedin:
            enabled: false
            queries: ["senior backend"]
        daily_cap: 12
        """
    )
    path = tmp_path / "prefs.yaml"
    path.write_text(raw, encoding="utf-8")

    prefs = load_preferences(path)

    assert prefs.daily_cap == 12
    assert prefs.targets.min_base_salary_usd == 200000
    assert prefs.targets.remote_ok is False
    assert prefs.enabled_sources() == ["jobright"]
    assert prefs.queries_for("jobright") == ["senior backend"]
    assert prefs.queries_for("linkedin") == []  # disabled


def test_is_excluded_company_case_insensitive() -> None:
    prefs = Preferences.model_validate({"exclude": {"companies": ["Bad Corp"]}})
    assert prefs.is_excluded_company("bad corp")
    assert not prefs.is_excluded_company("Great Corp")


def test_mentions_excluded_keyword() -> None:
    prefs = Preferences.model_validate({"exclude": {"keywords": ["intern"]}})
    assert prefs.mentions_excluded_keyword("Looking for an intern")
    assert not prefs.mentions_excluded_keyword("Senior role")


def test_location_acceptance_prefers_remote() -> None:
    prefs = Preferences.model_validate({
        "targets": {"locations": ["New York, NY"], "remote_ok": True},
    })
    assert prefs.location_is_acceptable("Remote (US)")
    assert prefs.location_is_acceptable("New York, NY")
    assert prefs.location_is_acceptable(None)  # blank == acceptable
    assert not prefs.location_is_acceptable("Paris, France")


def test_throttle_validation_rejects_inverted_window() -> None:
    with pytest.raises(ValueError):
        Preferences.model_validate({
            "scraper": {"min_delay_ms": 5000, "max_delay_ms": 1000},
        })
