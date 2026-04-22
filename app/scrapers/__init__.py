"""Job scrapers.

A scraper implements the `Scraper` protocol in `base.py`. The runner calls
`discover(preferences)` per source and collects `RawJob` dataclasses. Each
scraper runs behind a persistent Playwright profile (see `playwright_session`)
so credentials are never stored in code.

For development and the first green end-to-end run, `fake.FakeScraper`
produces canned jobs so we can exercise the full tailor pipeline without
hitting any real sites. Real scrapers register themselves in the `REGISTRY`
when their modules are imported.
"""

from app.scrapers.base import RawJob, Scraper
from app.scrapers.fake import FakeScraper
from app.scrapers.registry import REGISTRY, get_scraper, register

# Importing the real scraper modules triggers their `register(...)` calls.
# Each import is guarded: a broken module must never take down the whole app.
# The actual Playwright import happens lazily inside `sync_context`, so these
# imports are safe even when the browser binaries aren't installed.
for _mod in ("jobright", "welcome_to_the_jungle", "linkedin"):
    try:
        __import__(f"app.scrapers.{_mod}")
    except Exception:  # pragma: no cover - import-time guard
        import logging

        logging.getLogger(__name__).exception("failed to import scraper %s", _mod)

__all__ = ["RawJob", "Scraper", "FakeScraper", "REGISTRY", "get_scraper", "register"]
