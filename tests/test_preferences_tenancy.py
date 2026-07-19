"""Per-profile preferences tenancy."""

from __future__ import annotations

from pathlib import Path

from app.jobs import preferences as pref_mod
from app.jobs.preferences import (
    load_preferences,
    patch_job_search_geography,
    preferences_path,
)
from app.services.data_context import candidate_data_dir


def test_preferences_path_uses_tenant_dir(tmp_path: Path) -> None:
    with candidate_data_dir(tmp_path):
        assert preferences_path() == tmp_path / "preferences.yaml"


def test_tenant_patch_writes_profile_file_not_shared(
    tmp_path: Path, monkeypatch
) -> None:
    shared = tmp_path / "shared" / "preferences.yaml"
    shared.parent.mkdir(parents=True)
    shared.write_text(
        "targets:\n  locations: [SharedCity]\n  remote_ok: false\n"
        "sources:\n  linkedin:\n    enabled: true\n    queries: [q]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pref_mod, "DEFAULT_PATH", shared)

    tenant = tmp_path / "tenant"
    tenant.mkdir()
    with candidate_data_dir(tenant):
        prefs = patch_job_search_geography(
            locations=["Tenant City"],
            remote_ok=True,
            linkedin_geo_id="90000084",
        )
        assert prefs.targets.locations == ["Tenant City"]
        assert (tenant / "preferences.yaml").is_file()
        # Shared defaults unchanged.
        shared_prefs = load_preferences(shared)
        assert shared_prefs.targets.locations == ["SharedCity"]


def test_load_falls_back_to_shared_when_tenant_missing(
    tmp_path: Path, monkeypatch
) -> None:
    shared = tmp_path / "shared" / "preferences.yaml"
    shared.parent.mkdir(parents=True)
    shared.write_text(
        "targets:\n  locations: [FromShared]\n  remote_ok: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pref_mod, "DEFAULT_PATH", shared)
    tenant = tmp_path / "empty_tenant"
    tenant.mkdir()
    with candidate_data_dir(tenant):
        prefs = load_preferences()
        assert prefs.targets.locations == ["FromShared"]
