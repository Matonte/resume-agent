"""LinkedIn scraper.

LinkedIn's ToS disallows automated scraping. This scraper exists to support
a *human-paced* review workflow:
- one persistent browser profile you signed into yourself once,
- random delays between every page load (honoring preferences.scraper),
- a small per-run cap (~30 page loads),
- failures return [] rather than raising.

None of this makes it ToS-compliant; it just keeps the blast radius small.
Use at your own risk. If you prefer, disable the linkedin source in
`data/preferences.yaml`.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import List

from app.scrapers.apply_link import guess_external_apply_url
from app.scrapers.base import RawJob
from app.scrapers.playwright_session import human_sleep, sync_context
from app.scrapers.posted_at_heuristic import parse_relative_posted_at
from app.scrapers.registry import register

logger = logging.getLogger(__name__)

BASE = "https://www.linkedin.com"
SEARCH_URL = BASE + "/jobs/search/?keywords={q}&f_TPR=r86400&geoId=103644278"  # last 24h, US


def _search_url(query: str) -> str:
    q = urllib.parse.quote_plus(query or "senior backend engineer")
    return SEARCH_URL.format(q=q)


class LinkedInScraper:
    source = "linkedin"
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
                        logger.exception("linkedin query %r failed", query)
        except Exception:  # noqa: BLE001
            logger.exception("linkedin: Playwright context failed to start")
            return []
        return out[: preferences.per_source_cap]

    def _scrape_query(self, context, query: str, cap: int, prefs) -> List[RawJob]:
        page = context.new_page()
        try:
            page.goto(_search_url(query), wait_until="domcontentloaded", timeout=45000)
            human_sleep(prefs)
            try:
                for _ in range(4):
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(900)
            except Exception:  # pragma: no cover
                pass

            # Job cards in the search results list.
            anchors = page.locator("a[href*='/jobs/view/']").element_handles()
            seen: set[str] = set()
            hits: List[tuple[str, str]] = []
            for a in anchors:
                try:
                    href = a.get_attribute("href") or ""
                    if "/jobs/view/" not in href:
                        continue
                    text = (a.inner_text() or "").strip()
                    # Normalize to the stable /jobs/view/<id>/ form.
                    url = href.split("?")[0]
                    if not url.startswith("http"):
                        url = BASE + url
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
                human_sleep(prefs)  # pace per-card too
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
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            human_sleep(prefs)
            try:
                # Expand "See more" if it's there.
                see_more = page.locator("button:has-text('See more')").first
                if see_more.count() > 0:
                    see_more.click(timeout=2000)
                    page.wait_for_timeout(400)
            except Exception:  # pragma: no cover
                pass

            title = _first_text(page, [
                "h1",
                "h2.top-card-layout__title",
                "[data-test-id='job-details-title']",
            ]) or card_text.split("\n")[0]
            company = _first_text(page, [
                "a.topcard__org-name-link",
                ".topcard__flavor--black-link",
                ".job-details-jobs-unified-top-card__company-name a",
            ]) or ""
            location = _first_text(page, [
                ".topcard__flavor--bullet",
                ".job-details-jobs-unified-top-card__bullet",
            ])
            jd_full = _first_text(page, [
                "div.show-more-less-html__markup",
                "div.jobs-description__content",
                "section.description",
                "main",
            ]) or ""
            if not jd_full or len(jd_full) < 200:
                return None
            page_url = (page.url or url).split("?")[0].rstrip("/")
            posted_blob = _linkedin_posted_blob(page)
            posted_at = parse_relative_posted_at(posted_blob)
            apply = guess_external_apply_url(page, fallback=page_url)
            return RawJob(
                source=self.source,
                url=page_url,
                title=title.strip(),
                company=company.strip() or "Unknown",
                jd_full=jd_full,
                location=(location or "").strip() or None,
                apply_url=apply,
                posted_at=posted_at,
                raw={"card_text": card_text, "posted_blob": posted_blob[:500]},
            )
        except Exception:
            logger.exception("linkedin: detail fetch failed for %s", url)
            return None
        finally:
            try:
                page.close()
            except Exception:  # pragma: no cover
                pass


def _linkedin_posted_blob(page) -> str:
    chunks: List[str] = []
    for sel in (
        ".job-details-jobs-unified-top-card__primary-description",
        ".job-details-jobs-unified-top-card__tertiary-description",
        "span.jobs-unified-top-card__posted-date",
        ".jobs-unified-top-card__subtitle",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            txt = loc.inner_text(timeout=1500)
            if txt and txt.strip():
                chunks.append(txt.strip())
        except Exception:
            continue
    return " ".join(chunks)


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


register("linkedin", LinkedInScraper)


__all__ = ["LinkedInScraper"]
