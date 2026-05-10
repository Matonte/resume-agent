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

# LinkedIn /jobs/search geo filter when ``sources.linkedin.geo_id`` is unset.
DEFAULT_LINKEDIN_JOBS_GEO_ID = "103644278"


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
    #: Drop listings older than this many days when `posted_at` is known.
    #: 0 = no age filter (unknown ages are always kept).
    max_posting_age_days: int = 0


class Exclude(BaseModel):
    companies: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    enabled: bool = True
    queries: List[str] = Field(default_factory=list)
    #: LinkedIn jobs search URL ``geoId`` (numeric). Empty = use
    #: ``DEFAULT_LINKEDIN_JOBS_GEO_ID`` (US). Ignored by other sources.
    geo_id: str = ""


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


class OutreachForJobConfig(BaseModel):
    """After tailoring each job, optionally search the web for recruiter/HM-style
    contacts at the company and write ``outreach_contacts.json`` when found.

    Full SERP path requires ``GOOGLE_CSE_*`` and/or ``BING_SEARCH_KEY``.
    ``MEETING_ADVISOR_URL`` improves notes via the advisor on each hit.

    When ``posting_people`` is true, the job description (and optionally the
    apply URL) is scanned for named people; each yields an extra name+company
    search before enrichment when SERP is configured.

    **Without** web search keys, if ``MEETING_ADVISOR_URL`` is set and
    ``posting_people`` is true, extracted names still get one advisor call each
    and can populate ``outreach_contacts.json`` (no Google/Bing required).
    """

    enabled: bool = False
    max_search_hits: int = 8
    posting_people: bool = True
    fetch_apply_page: bool = True
    max_posting_people: int = 5
    max_followup_queries: int = 6
    include_engineer_contacts: bool = False


class Preferences(BaseModel):
    candidate: CandidateInfo = Field(default_factory=CandidateInfo)
    targets: Targets = Field(default_factory=Targets)
    exclude: Exclude = Field(default_factory=Exclude)
    sources: Dict[str, SourceConfig] = Field(default_factory=dict)
    daily_cap: int = 10
    per_source_cap: int = 15
    scraper: ScraperThrottle = Field(default_factory=ScraperThrottle)
    outreach_for_job: OutreachForJobConfig = Field(default_factory=OutreachForJobConfig)

    def enabled_sources(self) -> List[str]:
        return [name for name, cfg in self.sources.items() if cfg.enabled]

    def queries_for(self, source: str) -> List[str]:
        cfg = self.sources.get(source)
        return list(cfg.queries) if cfg and cfg.enabled else []

    def effective_linkedin_geo_id(self) -> str:
        cfg = self.sources.get("linkedin")
        if not cfg:
            return DEFAULT_LINKEDIN_JOBS_GEO_ID
        g = (cfg.geo_id or "").strip()
        return g or DEFAULT_LINKEDIN_JOBS_GEO_ID

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


def patch_job_search_geography(
    *,
    locations: List[str],
    remote_ok: bool,
    linkedin_geo_id: str,
    path: Optional[Path | str] = None,
) -> Preferences:
    """Update ``targets.locations``, ``targets.remote_ok``, and
    ``sources.linkedin.geo_id`` in ``preferences.yaml``.

    Loads the existing YAML mapping, applies those keys only, validates the
    full document as `Preferences`, then writes it back. Inline comments in
    the file are not preserved (PyYAML limitation).
    """
    resolved = Path(path) if path else DEFAULT_PATH
    if resolved.exists():
        raw_any = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    else:
        raw_any = {}
    if raw_any is None:
        raw_any = {}
    if not isinstance(raw_any, dict):
        raise ValueError("preferences.yaml must be a YAML mapping at the top level")
    raw: Dict[str, Any] = raw_any

    targets = dict(raw.get("targets") or {})
    cleaned = [str(x).strip() for x in locations if str(x).strip()]
    targets["locations"] = cleaned
    targets["remote_ok"] = remote_ok
    raw["targets"] = targets

    sources = dict(raw.get("sources") or {})
    linkedin = dict(sources.get("linkedin") or {})
    gid = (linkedin_geo_id or "").strip()
    if gid:
        linkedin["geo_id"] = gid
    else:
        linkedin.pop("geo_id", None)
    sources["linkedin"] = linkedin
    raw["sources"] = sources

    prefs = Preferences.model_validate(raw)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return prefs


__all__ = [
    "Preferences",
    "CandidateInfo",
    "Targets",
    "Exclude",
    "SourceConfig",
    "ScraperThrottle",
    "OutreachForJobConfig",
    "load_preferences",
    "merge_preferences_candidate",
    "patch_job_search_geography",
    "DEFAULT_PATH",
    "DEFAULT_LINKEDIN_JOBS_GEO_ID",
]
