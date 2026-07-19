"""API for editing job search geography in ``data/preferences.yaml``."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.jobs.preferences import (
    DEFAULT_LINKEDIN_JOBS_GEO_ID,
    load_preferences,
    patch_job_search_geography,
    preferences_path,
)

router = APIRouter(prefix="/api/job-search-geography", tags=["job-search-geography"])


class JobSearchGeographyPayload(BaseModel):
    locations: List[str] = Field(default_factory=list)
    remote_ok: bool = True
    linkedin_geo_id: str = ""

    @field_validator("linkedin_geo_id")
    @classmethod
    def _geo_numeric(cls, v: str) -> str:
        s = (v or "").strip()
        if s and not s.isdigit():
            raise ValueError("LinkedIn geo id must be numeric (digits only)")
        return s


def _response_dict(prefs) -> Dict[str, Any]:
    cfg = prefs.sources.get("linkedin")
    stored = (cfg.geo_id if cfg else "") or ""
    stored = stored.strip()
    path = preferences_path()
    return {
        "locations": list(prefs.targets.locations),
        "remote_ok": prefs.targets.remote_ok,
        "linkedin_geo_id": stored,
        "linkedin_effective_geo_id": prefs.effective_linkedin_geo_id(),
        "linkedin_default_geo_id": DEFAULT_LINKEDIN_JOBS_GEO_ID,
        "preferences_path": str(path),
        "save_note": (
            "Saving rewrites the active profile preferences.yaml "
            f"({path.name}); YAML comments are not preserved (PyYAML)."
        ),
    }


@router.get("/")
def get_job_search_geography() -> JSONResponse:
    prefs = load_preferences()
    return JSONResponse(_response_dict(prefs))


@router.put("/")
def put_job_search_geography(payload: JobSearchGeographyPayload) -> JSONResponse:
    try:
        prefs = patch_job_search_geography(
            locations=payload.locations,
            remote_ok=payload.remote_ok,
            linkedin_geo_id=payload.linkedin_geo_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, **_response_dict(prefs)})


__all__ = ["router"]
