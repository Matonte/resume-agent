"""Jobright.ai scraper (lowest TOS risk of the three).

Uses a persistent Playwright profile under `.playwright/profile-jobright/`.
The user is responsible for logging in once via
`python scripts/login_once.py jobright`. After that the profile has a valid
session cookie and this scraper can browse listings.

Heuristics over specific CSS selectors: the job feed is card-based, each
card links to a detail page. We keep selectors deliberately generic so
minor UI tweaks don't take the scraper down completely. On any error, we
log and return [] so the daily run keeps working with the remaining
sources.
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime
from typing import List

from app.scrapers.base import RawJob
from app.scrapers.playwright_session import human_sleep, sync_context
from app.scrapers.registry import register

logger = logging.getLogger(__name__)

BASE = "https://jobright.ai"
SEARCH_URL = BASE + "/jobs/recommend"  # personalized feed; query string optional


def _search_url(query: str) -> str:
    if not query:
        return SEARCH_URL
    return SEARCH_URL + "?" + urllib.parse.urlencode({"q": query})


class JobrightScraper:
    source = "jobright"
    requires_auth = True

    def discover(self, preferences) -> List[RawJob]:
        queries = preferences.queries_for(self.source) or [""]
        cap_per_query = max(1, preferences.per_source_cap // max(1, len(queries)))

        out: List[RawJob] = []
        try:
            with sync_context(self.source, headless=True) as (_pw, context):
                for query in queries:
                    try:
                        found = self._scrape_query(context, query, cap_per_query, preferences)
                        out.extend(found)
                    except Exception:  # noqa: BLE001
                        logger.exception("jobright query %r failed", query)
        except Exception:  # noqa: BLE001
            logger.exception("jobright: Playwright context failed to start")
            return []
        return out[: preferences.per_source_cap]

    def _scrape_query(self, context, query: str, cap: int, prefs) -> List[RawJob]:
        page = context.new_page()
        try:
            page.goto(_search_url(query), wait_until="domcontentloaded", timeout=30000)
            human_sleep(prefs)

            # Expand the feed a bit; ignore failures.
            try:
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1200)
            except Exception:  # pragma: no cover
                pass

            # Generic card selector.
            anchors = page.locator("a[href*='/jobs/']").element_handles()
            seen: set[str] = set()
            candidates: List[tuple[str, str]] = []
            for a in anchors:
                try:
                    href = a.get_attribute("href") or ""
                    if not href or "/jobs/" not in href:
                        continue
                    text = (a.inner_text() or "").strip()
                    if not text:
                        continue
                    url = href if href.startswith("http") else BASE + href
                    if url in seen:
                        continue
                    seen.add(url)
                    candidates.append((url, text))
                except Exception:  # pragma: no cover
                    continue
                if len(candidates) >= cap * 3:
                    break

            out: List[RawJob] = []
            for url, card_text in candidates:
                if len(out) >= cap:
                    break
                job = self._fetch_detail(context, url, card_text, prefs)
                if job:
                    out.append(job)
            return out
        finally:
            try:
                page.close()
            except Exception:  # pragma: no cover
                pass

    def _fetch_detail(self, context, url: str, card_text: str, prefs) -> RawJob | None:
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            human_sleep(prefs)
            # Title is usually in an <h1> near the top.
            title = _first_text(page, ["h1", "header h1", "[data-testid='job-title']"]) or card_text.split("\n")[0]
            company = _first_text(page, [
                "[data-testid='company-name']",
                "a[href*='/companies/']",
                "header h2",
            ]) or ""
            location = _first_text(page, [
                "[data-testid='location']",
                "span:has-text(', ')",
            ])
            salary = _first_text(page, ["[data-testid='salary']"])
            jd_full = _first_text(page, [
                "[data-testid='job-description']",
                "section:has-text('Description')",
                "main",
            ]) or ""
            if not jd_full or len(jd_full) < 200:
                return None
            return RawJob(
                source=self.source,
                url=url,
                title=title.strip() or "Senior Backend Engineer",
                company=company.strip() or "Unknown",
                jd_full=jd_full,
                location=(location or "").strip() or None,
                salary_raw=(salary or "").strip() or None,
                apply_url=url,
                posted_at=datetime.utcnow(),
                raw={"card_text": card_text},
            )
        except Exception:
            logger.exception("jobright: detail fetch failed for %s", url)
            return None
        finally:
            try:
                page.close()
            except Exception:  # pragma: no cover
                pass


def _first_text(page, selectors: List[str]) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            txt = loc.inner_text(timeout=2000)
            if txt and txt.strip():
                return txt.strip()
        except Exception:
            continue
    return None


register("jobright", JobrightScraper)


__all__ = ["JobrightScraper"]
