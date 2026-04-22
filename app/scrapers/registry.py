"""Scraper registry.

Real scraper modules call `register("linkedin", LinkedInScraper)` at import
time. Before a real implementation exists for a source, `get_scraper` falls
back to a `FakeScraper` so the runner can always produce *something* in a
dev environment.
"""

from __future__ import annotations

from typing import Callable, Dict

from app.scrapers.base import Scraper
from app.scrapers.fake import FakeScraper

# Factory per source id; source id matches `preferences.sources.<key>`.
REGISTRY: Dict[str, Callable[[], Scraper]] = {}


def register(source: str, factory: Callable[[], Scraper]) -> None:
    REGISTRY[source] = factory


def get_scraper(source: str, *, fake: bool = False) -> Scraper:
    """Return a scraper instance for `source`.

    `fake=True` always yields a FakeScraper. Otherwise we honor the registry
    and fall back to a fake when a real scraper hasn't been wired up yet
    (so `daily_run.py` always works end-to-end, even mid-implementation).
    """
    if fake:
        return FakeScraper(source)
    factory = REGISTRY.get(source)
    if factory is None:
        return FakeScraper(source)
    return factory()
