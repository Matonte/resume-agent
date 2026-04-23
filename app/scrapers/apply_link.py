"""Heuristic external 'apply on company site' link extraction."""

from __future__ import annotations

from typing import Sequence


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
                if not h.startswith("http"):
                    continue
                low = h.lower()
                if any(x in low for x in exclude_if_contains):
                    continue
                return h.strip()
        except Exception:
            continue
    return fallback
