"""Heuristic external 'apply on company site' link extraction."""

from __future__ import annotations

from typing import Sequence
from urllib.parse import urlparse

# Domains / path hints that usually mean “real application URL”, not a job board shell.
_ATS_HINTS = (
    "greenhouse.io",
    "boards.greenhouse",
    "lever.co",
    "jobs.lever",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "wd5.myworkdayjobs.com",
    "smartrecruiters.com",
    "jobvite.com",
    "icims.com",
    "bamboohr.com",
    "taleo.net",
    "apply.workable.com",
    "bullhornreach.com",
    "trakstar.com",
    "recruitee.com",
    "teamtailor.com",
    "eightfold.ai",
)


def _apply_url_score(url: str) -> int:
    low = url.lower()
    s = 0
    for frag in _ATS_HINTS:
        if frag in low:
            s += 12
    if "/apply" in low or "/application" in low or "apply?" in low:
        s += 5
    if "careers" in low or "/job" in low or "/jobs/" in low:
        s += 3
    try:
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("jobs.") or ".jobs." in host:
            s += 6
        if "careers" in host or "talent" in host:
            s += 4
    except Exception:
        pass
    return s


def guess_external_apply_url(
    page,
    *,
    fallback: str,
    exclude_if_contains: Sequence[str] = (
        "linkedin.com",
        "licdn.com",
        "jobright.ai",
        "google.com/maps",
    ),
    max_checks: int = 12,
) -> str:
    """Prefer a visible off-platform apply URL when the board wraps the real
    application (LinkedIn Easy Apply vs company site, Jobright deep links)."""

    def allowed(h: str) -> bool:
        if not h.startswith("http"):
            return False
        low = h.lower()
        return not any(x in low for x in exclude_if_contains)

    selectors = [
        "a[data-tracking-control-name*='apply'][href^='http']",
        "a.jobs-unified-top-card__compact-apply-button[href^='http']",
        ".jobs-unified-top-card__button-group a[href^='http']",
        "a[href^='http'][target='_blank']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = min(loc.count(), max_checks)
            for i in range(n):
                h = loc.nth(i).get_attribute("href") or ""
                if not allowed(h):
                    continue
                return h.strip()
        except Exception:
            continue

    # Job boards (e.g. Jobright) often expose the ATS link as a plain anchor our
    # LinkedIn-targeted selectors miss — scan anchors and pick the strongest
    # apply-like external URL.
    try:
        loc = page.locator("a[href^='http']")
        n = min(loc.count(), 80)
        best_h = ""
        best_s = 0
        seen: set[str] = set()
        for i in range(n):
            h = loc.nth(i).get_attribute("href") or ""
            h = h.strip()
            if not allowed(h) or h in seen:
                continue
            seen.add(h)
            sc = _apply_url_score(h)
            if sc > best_s:
                best_s = sc
                best_h = h
        if best_h and best_s >= 6:
            return best_h
    except Exception:
        pass

    return fallback
