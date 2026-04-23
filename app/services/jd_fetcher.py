"""Fetch and parse a public job-description URL into a RawJob.

This is used by the manual `/tailor` endpoint. The daily scrapers each
handle their own site-specific flow via Playwright; this helper is the
"paste any URL and we'll do our best" path, which means we try to be
forgiving and heuristic rather than exhaustive.

We deliberately:
  - Use `requests` (not Playwright), so this is fast and cheap.
  - Decline gracefully when the page renders its JD with JS (we return
    a RawJob with jd_full="" and the caller decides what to do).
  - Never raise on network errors; return an explanatory error string
    alongside the RawJob so the endpoint can surface it to the user.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from app.scrapers.base import RawJob

logger = logging.getLogger(__name__)

# Reasonable desktop UA so job boards don't 403 us for being a bot.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_MIN_JD_CHARS = 250  # Below this a "JD" is probably a nav stub or redirect.

# Selectors we try in order to find the JD body. The first hit that yields
# at least _MIN_JD_CHARS of visible text wins. Ordering is deliberate: site-
# specific (most accurate) first, then generic.
_JD_SELECTORS = [
    # Greenhouse
    "#content",
    ".content",
    "section.opening",
    # Lever
    ".posting-page",
    ".posting",
    # Workday / common ATS
    "[data-automation-id='jobPostingDescription']",
    # Ashby / Wellfound / generic semantic tags
    "article",
    "main",
    # Welcome to the Jungle (public job pages)
    "[data-testid='job-section-description']",
    ".sc-1lqf5uz-0",
    # Last-ditch: the whole <body>
    "body",
]


@dataclass
class FetchedJob:
    """Thin wrapper so the endpoint can distinguish "got a JD" from
    "fetched but couldn't parse". Callers should check `error`."""

    raw: RawJob
    error: Optional[str] = None


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _longest_text_from_selectors(soup, selectors: list[str]) -> str:
    """Try each selector; return the longest non-trivial text found."""
    best = ""
    for sel in selectors:
        try:
            for node in soup.select(sel):
                # Strip script/style/nav before reading text.
                for bad in node.select("script, style, nav, header, footer, form"):
                    bad.decompose()
                text = _collapse_ws(node.get_text(" "))
                if len(text) > len(best):
                    best = text
            if len(best) >= _MIN_JD_CHARS:
                return best
        except Exception:
            continue
    return best


def _guess_title(soup) -> str:
    """Pick the strongest candidate for the job title."""
    for sel in ("h1", "[data-testid*='title']", "title"):
        try:
            node = soup.select_one(sel)
            if node and node.get_text(strip=True):
                return _collapse_ws(node.get_text(" "))[:200]
        except Exception:
            continue
    return ""


def _guess_company(soup, url: str) -> str:
    """Best-effort company guess. We check meta tags first, then fall
    back to extracting a hostname fragment like 'stripe' from
    'boards.greenhouse.io/stripe/jobs/...'."""
    for meta_sel in ("meta[property='og:site_name']", "meta[name='application-name']"):
        try:
            m = soup.select_one(meta_sel)
            if m and m.get("content"):
                return _collapse_ws(m["content"])[:120]
        except Exception:
            continue
    # Path-based: greenhouse, lever, ashbyhq put the company in the URL.
    try:
        host = urlparse(url).hostname or ""
        path = urlparse(url).path.strip("/").split("/")
        if "greenhouse.io" in host and path:
            return path[0].replace("-", " ").title()
        if "lever.co" in host and path:
            return path[0].replace("-", " ").title()
        if "ashbyhq.com" in host and path:
            return path[0].replace("-", " ").title()
        if "welcometothejungle.com" in host:
            # /en/companies/<slug>/jobs/<job-slug>
            if len(path) >= 3 and path[1] == "companies":
                return path[2].replace("-", " ").title()
        # Generic: use the second-level domain.
        host_parts = host.split(".")
        if len(host_parts) >= 2:
            return host_parts[-2].title()
    except Exception:
        pass
    return "Unknown"


def fetch_jd(url: str, *, timeout: float = 15.0) -> FetchedJob:
    """Fetch `url` and parse out title/company/body into a `RawJob`.

    Returns a `FetchedJob`; check `.error` when the body is empty or
    looks like a login wall. Never raises.
    """
    raw = RawJob(
        source="manual",
        url=url,
        title="",
        company="",
        jd_full="",
        apply_url=url,
    )
    try:
        import requests  # local import keeps module light when unused
    except ImportError:  # pragma: no cover - dependency always installed
        return FetchedJob(raw=raw, error="requests package not installed")

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("jd_fetcher: network error for %s: %s", url, exc)
        return FetchedJob(raw=raw, error=f"network error: {exc}")

    if resp.status_code >= 400:
        return FetchedJob(
            raw=raw,
            error=f"HTTP {resp.status_code} from {url}; the page may require login",
        )

    html = resp.text or ""
    if not html.strip():
        return FetchedJob(raw=raw, error="empty response body")

    try:
        from bs4 import BeautifulSoup  # local import
    except ImportError:  # pragma: no cover
        return FetchedJob(raw=raw, error="beautifulsoup4 not installed")

    soup = BeautifulSoup(html, "html.parser")
    body = _longest_text_from_selectors(soup, _JD_SELECTORS)
    title = _guess_title(soup)
    company = _guess_company(soup, url)

    raw.title = title or "Untitled Role"
    raw.company = company or "Unknown"
    raw.jd_full = body

    if len(body) < _MIN_JD_CHARS:
        return FetchedJob(
            raw=raw,
            error=(
                f"Could not extract a readable job description from {url} "
                f"(only {len(body)} chars). The page may be JS-rendered or "
                "behind a login. Paste the description text directly instead."
            ),
        )
    return FetchedJob(raw=raw, error=None)


__all__ = ["FetchedJob", "fetch_jd"]
