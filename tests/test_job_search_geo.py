"""Job search geography preferences + API."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.jobs import preferences as pref_mod
from app.jobs.preferences import (
    DEFAULT_LINKEDIN_JOBS_GEO_ID,
    patch_job_search_geography,
)
from app.main import app


def test_effective_linkedin_geo_id() -> None:
    from app.jobs.preferences import Preferences

    p = Preferences.model_validate({"sources": {"linkedin": {"enabled": True, "geo_id": ""}}})
    assert p.effective_linkedin_geo_id() == DEFAULT_LINKEDIN_JOBS_GEO_ID
    p2 = Preferences.model_validate(
        {"sources": {"linkedin": {"enabled": True, "geo_id": " 90000084 "}}}
    )
    assert p2.effective_linkedin_geo_id() == "90000084"


def test_patch_preserves_unrelated_keys(tmp_path: Path) -> None:
    raw = textwrap.dedent(
        """
        targets:
          locations: ["A"]
          remote_ok: false
        sources:
          linkedin:
            enabled: true
            queries: ["q1"]
        outreach_for_job:
          enabled: true
          max_search_hits: 3
        daily_cap: 7
        """
    )
    path = tmp_path / "preferences.yaml"
    path.write_text(raw, encoding="utf-8")

    patch_job_search_geography(
        locations=["Boston, MA"],
        remote_ok=True,
        linkedin_geo_id="90000084",
        path=path,
    )

    loaded = pref_mod.load_preferences(path)
    assert loaded.targets.locations == ["Boston, MA"]
    assert loaded.targets.remote_ok is True
    assert loaded.sources["linkedin"].geo_id == "90000084"
    assert loaded.sources["linkedin"].queries == ["q1"]
    assert loaded.outreach_for_job.enabled is True
    assert loaded.outreach_for_job.max_search_hits == 3
    assert loaded.daily_cap == 7


def test_api_get_put(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, authed_client: TestClient
) -> None:
    p = tmp_path / "preferences.yaml"
    p.write_text(
        textwrap.dedent(
            """
            targets:
              locations: ["X"]
              remote_ok: false
            sources:
              linkedin:
                enabled: true
                queries: []
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pref_mod, "DEFAULT_PATH", p)
    client = authed_client
    r = client.get("/api/job-search-geography/")
    assert r.status_code == 200
    assert r.json()["locations"] == ["X"]
    assert r.json()["linkedin_effective_geo_id"] == DEFAULT_LINKEDIN_JOBS_GEO_ID

    r2 = client.put(
        "/api/job-search-geography/",
        json={
            "locations": ["NYC", "Remote (US)"],
            "remote_ok": True,
            "linkedin_geo_id": "103644278",
        },
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["ok"] is True
    assert body["locations"] == ["NYC", "Remote (US)"]
    assert body["linkedin_geo_id"] == "103644278"


def test_put_rejects_non_numeric_geo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, authed_client: TestClient
) -> None:
    p = tmp_path / "preferences.yaml"
    p.write_text("targets: { locations: [], remote_ok: true }\n", encoding="utf-8")
    monkeypatch.setattr(pref_mod, "DEFAULT_PATH", p)
    client = authed_client
    r = client.put(
        "/api/job-search-geography/",
        json={"locations": [], "remote_ok": True, "linkedin_geo_id": "US"},
    )
    assert r.status_code == 422
