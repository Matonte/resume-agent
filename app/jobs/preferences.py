"""Load and validate `data/preferences.yaml`.

Preferences drive the daily run: which sources to hit, what to search for,
what to exclude, and how many jobs to keep. Kept deliberately small and
Pydantic-validated so a malformed YAML surfaces early rather than at scrape
time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "preferences.yaml"


class CandidateInfo(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    github_url: str = ""


class Targets(BaseModel):
    titles: List[str] = Field(default_factory=list)
    seniority: str = "senior"
    locations: List[str] = Field(default_factory=list)
    remote_ok: bool = True
    min_base_salary_usd: int = 0


class Exclude(BaseModel):
    companies: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    enabled: bool = True
    queries: List[str] = Field(default_factory=list)


class ScraperThrottle(BaseModel):
    min_delay_ms: int = 1500
    max_delay_ms: int = 4000

    @field_validator("max_delay_ms")
    @classmethod
    def _validate_max(cls, v: int, info) -> int:
        min_val = info.data.get("min_delay_ms", 0)
        if v < min_val:
            raise ValueError("max_delay_ms must be >= min_delay_ms")
        return v


class Preferences(BaseModel):
    candidate: CandidateInfo = Field(default_factory=CandidateInfo)
    targets: Targets = Field(default_factory=Targets)
    exclude: Exclude = Field(default_factory=Exclude)
    sources: Dict[str, SourceConfig] = Field(default_factory=dict)
    daily_cap: int = 10
    per_source_cap: int = 15
    scraper: ScraperThrottle = Field(default_factory=ScraperThrottle)

    def enabled_sources(self) -> List[str]:
        return [name for name, cfg in self.sources.items() if cfg.enabled]

    def queries_for(self, source: str) -> List[str]:
        cfg = self.sources.get(source)
        return list(cfg.queries) if cfg and cfg.enabled else []

    def is_excluded_company(self, company: str) -> bool:
        if not company:
            return False
        low = company.strip().lower()
        return any(low == c.strip().lower() for c in self.exclude.companies)

    def mentions_excluded_keyword(self, text: str) -> bool:
        if not text:
            return False
        low = text.lower()
        return any(k.lower() in low for k in self.exclude.keywords if k)

    def location_is_acceptable(self, location: Optional[str]) -> bool:
        """True iff the posted location matches our target cities or we accept
        remote. A missing location is treated as acceptable (many boards leave
        it blank for remote roles)."""
        if not self.targets.locations and not self.targets.remote_ok:
            return True
        if not location:
            return True
        low = location.lower()
        if self.targets.remote_ok and "remote" in low:
            return True
        for loc in self.targets.locations:
            if loc.lower() in low or low in loc.lower():
                return True
        return False


def merge_preferences_candidate(
    prefs: Preferences,
    profile: Optional[Any],
) -> Preferences:
    """Overlay `profile.candidate_name` / `candidate_email` onto prefs for
    cover letters and packaging when the active resume profile defines them."""
    if profile is None:
        return prefs
    name = (getattr(profile, "candidate_name", None) or "").strip()
    email = (getattr(profile, "candidate_email", None) or "").strip()
    if not name and not email:
        return prefs
    data = prefs.model_dump()
    cand = dict(data.get("candidate") or {})
    if name:
        cand["name"] = name
    if email:
        cand["email"] = email
    data["candidate"] = cand
    return Preferences.model_validate(data)


def load_preferences(path: Optional[Path | str] = None) -> Preferences:
    """Load preferences from YAML. Returns a default-populated `Preferences`
    if the file is missing (useful for tests and first-run setup)."""
    resolved = Path(path) if path else DEFAULT_PATH
    if not resolved.exists():
        return Preferences()
    with resolved.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Preferences.model_validate(raw)


__all__ = [
    "Preferences",
    "CandidateInfo",
    "Targets",
    "Exclude",
    "SourceConfig",
    "ScraperThrottle",
    "load_preferences",
    "merge_preferences_candidate",
    "DEFAULT_PATH",
]
