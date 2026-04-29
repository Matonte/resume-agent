"""Combination web search for outreach discovery (companies, people, news).

Drives two providers when keys are set — Google Programmable Search (CSE) and
Bing Web Search v7 — plus YAML-driven *keyword rules* that add `site:...` and
other scoped queries. Results are merged and URL-deduplicated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import yaml
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_YAML = _REPO / "data" / "outreach_search.yaml"


class KeywordRule(BaseModel):
    match: List[str] = Field(default_factory=list)
    extra_queries: List[str] = Field(default_factory=list)


class OutreachSearchConfig(BaseModel):
    open_queries: List[str] = Field(
        default_factory=lambda: [
            "{description} startup company",
        ]
    )
    keyword_rules: List[KeywordRule] = Field(default_factory=list)
    max_queries: int = 20
    results_per_query: int = 8


def load_outreach_search_config(path: Optional[Path | str] = None) -> OutreachSearchConfig:
    """Load YAML from `data/outreach_search.yaml` or return defaults if missing."""
    resolved = _DEFAULT_YAML if path is None else Path(path)
    if not resolved.exists():
        return OutreachSearchConfig()
    with resolved.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return OutreachSearchConfig.model_validate(raw)


def _substitute_description(template: str, description: str) -> str:
    return template.replace("{description}", description.strip())


def _rule_matches(
    rule: KeywordRule, description: str, explicit_tags: Optional[Sequence[str]]
) -> bool:
    d = description.lower()
    for phrase in rule.match:
        p = (phrase or "").strip().lower()
        if p and p in d:
            return True
    if explicit_tags and rule.match:
        tags_lower = {t.strip().lower() for t in explicit_tags if t and t.strip()}
        for phrase in rule.match:
            p = (phrase or "").strip().lower()
            if p and p in tags_lower:
                return True
    return False


def build_query_plan(
    description: str,
    config: Optional[OutreachSearchConfig] = None,
    explicit_tags: Optional[Sequence[str]] = None,
) -> List[str]:
    """Expand open queries + keyword_rules into a deduped, capped list."""
    cfg = config or load_outreach_search_config()
    desc = (description or "").strip()
    if not desc:
        return []

    seen: set[str] = set()
    ordered: List[str] = []

    def add_q(q: str) -> None:
        q = " ".join(q.split())
        if not q or q in seen:
            return
        seen.add(q)
        ordered.append(q)

    for t in cfg.open_queries:
        add_q(_substitute_description(t, desc))
    for rule in cfg.keyword_rules:
        if not _rule_matches(rule, desc, explicit_tags):
            continue
        for t in rule.extra_queries:
            add_q(_substitute_description(t, desc))
    return ordered[: max(0, cfg.max_queries)]


def _normalize_url(url: str) -> str:
    if not (url or "").strip():
        return ""
    try:
        parts = urlsplit(url.strip())
    except Exception:
        return (url or "").strip().lower()
    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    if not netloc:
        return (url or "").strip().lower()
    path = (parts.path or "/").rstrip("/") or "/"
    # Drop tracking params commonly used in SERP redirects.
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "gclid", "fbclid", "igshid"}]
    query = urlencode(q) if q else ""
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str
    engine: str
    query: str


@dataclass
class CombinationSearchResult:
    queries: List[str] = field(default_factory=list)
    hits: List[WebSearchHit] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def merge_dedupe_hits(hits: Sequence[WebSearchHit]) -> List[WebSearchHit]:
    """Keep first occurrence per normalized URL; preserve input order."""
    by_url: dict[str, WebSearchHit] = {}
    order: List[str] = []
    for h in hits:
        key = _normalize_url(h.url)
        if not key or key in by_url:
            continue
        by_url[key] = h
        order.append(key)
    return [by_url[k] for k in order]


def _google_cse_search(
    client: httpx.Client,
    query: str,
    num: int,
) -> List[WebSearchHit]:
    key = (settings.google_cse_api_key or "").strip()
    cx = (settings.google_cse_cx or "").strip()
    if not key or not cx:
        return []
    num = min(max(1, num), 10)
    r = client.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": key, "cx": cx, "q": query, "num": num},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    out: List[WebSearchHit] = []
    for item in data.get("items") or []:
        link = (item.get("link") or "").strip()
        if not link:
            continue
        out.append(
            WebSearchHit(
                title=(item.get("title") or "")[:500],
                url=link,
                snippet=(item.get("snippet") or "")[:2000],
                engine="google",
                query=query,
            )
        )
    return out


def _bing_search(client: httpx.Client, query: str, count: int) -> List[WebSearchHit]:
    key = (settings.bing_search_key or "").strip()
    if not key:
        return []
    count = min(max(1, count), 10)
    r = client.get(
        "https://api.bing.microsoft.com/v7.0/search",
        params={"q": query, "count": count, "mkt": "en-US", "textDecorations": "false"},
        headers={"Ocp-Apim-Subscription-Key": key},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    web = data.get("webPages") or {}
    out: List[WebSearchHit] = []
    for item in web.get("value") or []:
        link = (item.get("url") or "").strip()
        if not link:
            continue
        out.append(
            WebSearchHit(
                title=(item.get("name") or "")[:500],
                url=link,
                snippet=(item.get("snippet") or "")[:2000],
                engine="bing",
                query=query,
            )
        )
    return out


def run_combination_search(
    description: str,
    explicit_tags: Optional[Sequence[str]] = None,
    *,
    config: Optional[OutreachSearchConfig] = None,
    config_path: Optional[Path | str] = None,
) -> CombinationSearchResult:
    """Build queries from config, hit Google + Bing (when keys exist), merge."""
    cfg = config or load_outreach_search_config(config_path)
    queries = build_query_plan(description, cfg, explicit_tags=explicit_tags)
    if not queries:
        return CombinationSearchResult(queries=[], hits=[], errors=[])

    n = min(max(1, cfg.results_per_query), 10)
    has_google = bool((settings.google_cse_api_key or "").strip()) and bool(
        (settings.google_cse_cx or "").strip()
    )
    has_bing = bool((settings.bing_search_key or "").strip())
    if not has_google and not has_bing:
        return CombinationSearchResult(
            queries=queries,
            hits=[],
            errors=["No search API keys configured (set GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX and/or BING_SEARCH_KEY)."],
        )

    all_hits: List[WebSearchHit] = []
    errors: List[str] = []

    with httpx.Client() as client:
        for q in queries:
            if has_google:
                try:
                    all_hits.extend(_google_cse_search(client, q, n))
                except Exception as exc:  # pragma: no cover - network
                    msg = f"google: {q[:80]!r}: {exc!s}"
                    logger.warning("%s", msg)
                    errors.append(msg)
            if has_bing:
                try:
                    all_hits.extend(_bing_search(client, q, n))
                except Exception as exc:  # pragma: no cover - network
                    msg = f"bing: {q[:80]!r}: {exc!s}"
                    logger.warning("%s", msg)
                    errors.append(msg)

    merged = merge_dedupe_hits(all_hits)
    return CombinationSearchResult(queries=queries, hits=merged, errors=errors)


__all__ = [
    "KeywordRule",
    "OutreachSearchConfig",
    "load_outreach_search_config",
    "build_query_plan",
    "WebSearchHit",
    "CombinationSearchResult",
    "merge_dedupe_hits",
    "run_combination_search",
]
