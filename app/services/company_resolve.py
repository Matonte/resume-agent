"""Infer a displayable employer name when company is missing or 'Unknown'."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_PLACEHOLDER_COMPANIES = frozenset(
    {
        "unknown",
        "unknown company",
        "n/a",
        "na",
        "tbd",
        "none",
        "not specified",
        "unspecified",
        "confidential",
    }
)

_ROLE_WORD_HINT = re.compile(
    r"\b(engineer|engineering|developer|scientist|designer|analyst|architect|"
    r"manager|director|intern|specialist|representative|recruiter|"
    r"remote|hybrid|full[\s-]?time|part[\s-]?time|contract)\b",
    re.I,
)


def is_placeholder_company(name: str | None) -> bool:
    n = (name or "").strip().lower()
    return not n or n in _PLACEHOLDER_COMPANIES


def _clean_fragment(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def company_hint_from_listing_url(url: str) -> str:
    """ATS paths and host slugs (no HTML). Returns '' when not inferable."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = [p for p in parsed.path.strip("/").split("/") if p]
        if "greenhouse.io" in host and path:
            return _clean_fragment(path[0].replace("-", " ").title())
        if "lever.co" in host and path:
            return _clean_fragment(path[0].replace("-", " ").title())
        if "ashbyhq.com" in host and path:
            return _clean_fragment(path[0].replace("-", " ").title())
        if "welcometothejungle.com" in host and len(path) >= 3 and path[1] == "companies":
            return _clean_fragment(path[2].replace("-", " ").title())
        parts = host.split(".")
        if len(parts) >= 2:
            sld = parts[-2]
            if sld in {"www", "jobs", "careers", "boards", "apply", "my"}:
                return ""
            return _clean_fragment(sld.replace("-", " ").title())
    except Exception:
        pass
    return ""


def company_hint_from_jd(jd: str) -> str:
    """Lightweight patterns on posting text (first ~2k chars)."""
    jd = (jd or "").strip()
    if len(jd) < 15:
        return ""

    head = jd[:2000]

    m = re.match(r"^\s*([^\n|]+?)\s*\|\s*([^\n|]+)", head)
    if m:
        left = _clean_fragment(m.group(1))
        right = _clean_fragment(m.group(2))
        if (
            left
            and right
            and not _ROLE_WORD_HINT.search(left)
            and _ROLE_WORD_HINT.search(right)
        ):
            return left[:120]

    for pat in (
        r"(?is)\babout\s+([A-Z0-9][A-Za-z0-9&'’\.\-\s]{2,52}?)(?:\s*(?:[—\-–]|[,.]|\n))",
        r"(?is)\bat\s+([A-Z0-9][A-Za-z0-9&'’\.\-\s]{2,52}?)\s*,\s*we\b",
        r"(?is)\bjoin\s+([A-Z0-9][A-Za-z0-9&'’\.\-\s]{2,52}?)(?:\s*[,\n]|\s+and\s)",
    ):
        mm = re.search(pat, head)
        if mm:
            cand = _clean_fragment(mm.group(1))
            if cand and not is_placeholder_company(cand) and len(cand) >= 2:
                return cand[:120]

    first = head.split("\n")[0].strip()
    if (
        first
        and 2 <= len(first) <= 72
        and not _ROLE_WORD_HINT.search(first)
        and not first.lower().startswith("http")
        and not first.endswith(":")
    ):
        return first[:120]

    return ""


def resolve_company_for_packaging(company: str, jd: str, listing_url: str = "") -> str:
    """Return best label for letters / metadata when scrapers say Unknown."""
    c = _clean_fragment(company)
    if not is_placeholder_company(c):
        return c
    for hint in (company_hint_from_jd(jd), company_hint_from_listing_url(listing_url)):
        h = _clean_fragment(hint)
        if h and not is_placeholder_company(h):
            return h[:120]
    return c


__all__ = [
    "company_hint_from_jd",
    "company_hint_from_listing_url",
    "is_placeholder_company",
    "resolve_company_for_packaging",
]
