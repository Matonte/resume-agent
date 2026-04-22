"""Scraper protocol and the raw-job dataclass.

A scraper is "anything that, given preferences, emits `RawJob` instances."
Keeping this interface small makes it easy to swap real Playwright-backed
scrapers for deterministic fakes in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable


@dataclass
class RawJob:
    """What a scraper returns before classification + tailoring runs.

    `id` is derived from (source, url) so rediscoveries are idempotent.
    `jd_full` should already contain the job description body; if a scraper
    can only get it via a second page load, it is expected to do that inside
    `discover` so the runner doesn't need to fan out again.
    """

    source: str
    url: str
    title: str
    company: str
    jd_full: str
    location: Optional[str] = None
    salary_raw: Optional[str] = None
    external_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    apply_url: Optional[str] = None
    raw: dict = field(default_factory=dict)


@runtime_checkable
class Scraper(Protocol):
    """Contract each site-specific scraper must satisfy."""

    source: str

    def discover(self, preferences) -> List[RawJob]:  # pragma: no cover - protocol
        """Return up to `preferences.per_source_cap` raw jobs. Honors the
        `targets`, `exclude`, and `sources[<source>].queries` sections of
        preferences. Must never raise on transient failures; return [] and
        log instead so a single broken source doesn't fail the whole run."""
        ...
