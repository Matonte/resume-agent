"""Welcome To The Jungle scraper.

Uses a persistent profile under `.playwright/profile-wttj/`. Log in once
with `python scripts/login_once.py wttj`. Search URL shape follows WTTJ's
English listings.
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

BASE = "https://www.welcometothejungle.com"
SEARCH_TEMPLATE = BASE + "/en/jobs?query={q}&refinementList%5Bcontract_type%5D%5B0%5D=full_time"


def _search_url(query: str) -> str:
    q = urllib.parse.quote_plus(query or "senior backend engineer")
    return SEARCH_TEMPLATE.format(q=q)


class WTTJScraper:
    source = "wttj"
    requires_auth = True

    def discover(self, preferences) -> List[RawJob]:
        queries = preferences.queries_for(self.source) or ["senior backend engineer"]
        cap_per_query = max(1, preferences.per_source_cap // max(1, len(queries)))

        out: List[RawJob] = []
        try:
            with sync_context(self.source, headless=True) as (_pw, context):
                for query in queries:
                    try:
                        found = self._scrape_query(context, query, cap_per_query, preferences)
                        out.extend(found)
                    except Exception:  # noqa: BLE001
                        logger.exception("wttj query %r failed", query)
        except Exception:  # noqa: BLE001
            logger.exception("wttj: Playwright context failed to start")
            return []
        return out[: preferences.per_source_cap]

    def _scrape_query(self, context, query: str, cap: int, prefs) -> List[RawJob]:
        page = context.new_page()
        try:
            page.goto(_search_url(query), wait_until="domcontentloaded", timeout=30000)
            human_sleep(prefs)
            try:
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1000)
            except Exception:  # pragma: no cover
                pass

            anchors = page.locator("a[href*='/companies/'][href*='/jobs/']").element_handles()
            seen: set[str] = set()
            hits: List[tuple[str, str]] = []
            for a in anchors:
                try:
                    href = a.get_attribute("href") or ""
                    if "/companies/" not in href or "/jobs/" not in href:
                        continue
                    text = (a.inner_text() or "").strip()
                    url = href if href.startswith("http") else BASE + href
                    if url in seen:
                        continue
                    seen.add(url)
                    hits.append((url, text))
                except Exception:  # pragma: no cover
                    continue
                if len(hits) >= cap * 3:
                    break

            out: List[RawJob] = []
            for url, card_text in hits:
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
            title = _first_text(page, ["h1", "[data-testid='job-title']"]) or card_text.split("\n")[0]
            company = _first_text(page, [
                "a[href*='/companies/'] h2",
                "header a[href*='/companies/']",
            ]) or ""
            location = _first_text(page, [
                "span:has-text(', ')",
                "[data-testid='job-location']",
            ])
            jd_full = _first_text(page, [
                "[data-testid='job-section-description']",
                "[class*='description']",
                "main",
            ]) or ""
            if not jd_full or len(jd_full) < 200:
                return None
            return RawJob(
                source=self.source,
                url=url,
                title=title.strip(),
                company=company.strip() or "Unknown",
                jd_full=jd_full,
                location=(location or "").strip() or None,
                apply_url=url,
                posted_at=datetime.utcnow(),
                raw={"card_text": card_text},
            )
        except Exception:
            logger.exception("wttj: detail fetch failed for %s", url)
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


register("wttj", WTTJScraper)


__all__ = ["WTTJScraper"]
