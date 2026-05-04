"""HTTP client for flask_sample WhoIsWhat ``POST /api/v1/people-intel``.

Resume-agent gathers **public** text (search snippets, posting excerpts); this
service forwards them to the sibling WhoIsWhat process for synthesis — no
scraping or LinkedIn API inside resume-agent.

Set ``CONTACT_ADVISOR_SERVICE_URL`` or ``WHOISWHAT_SERVICE_URL`` (e.g. ``http://127.0.0.1:5000``) to enable calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.config import settings
from app.services.outreach_posting_people import PostingPerson
from app.services.outreach_search import WebSearchHit

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def people_intel_post_url() -> str:
    return (settings.whoiswhat_people_intel_post_url or "").strip()


def is_configured() -> bool:
    return settings.whoiswhat_people_intel_configured


def snippets_from_web_hit(hit: WebSearchHit) -> List[Dict[str, str]]:
    """Turn a SERP row into labeled snippets safe for people-intel."""
    out: List[Dict[str, str]] = []
    title = (hit.title or "").strip()
    if title:
        out.append({"source_label": "web search title", "content": title[:8000]})
    snip = (hit.snippet or "").strip()
    if snip:
        out.append({"source_label": "web search snippet", "content": snip[:12000]})
    url = (hit.url or "").strip()
    if url and url not in (title, snip):
        out.append({"source_label": "result URL context", "content": url[:2000]})
    return out


def snippets_from_posting_person(
    person: PostingPerson, job_excerpt: str, *, company: str, title: str
) -> List[Dict[str, str]]:
    """JD / posting text only — callers may add LinkedIn etc. via custom snippets."""
    out: List[Dict[str, str]] = []
    rh = (person.role_hint or "").strip()
    if rh:
        out.append({"source_label": "job posting role hint", "content": rh[:500]})
    ev = (person.evidence or "").strip()
    if ev:
        out.append({"source_label": "job posting (named contact evidence)", "content": ev[:2000]})
    head = (company or "").strip() or "Company"
    role_title = (title or "").strip() or "Role"
    if head or role_title:
        out.append(
            {
                "source_label": "job listing context",
                "content": f"Company: {head}\nRole: {role_title}"[:2000],
            }
        )
    ex = (job_excerpt or "").strip()
    if ex:
        out.append({"source_label": "job posting excerpt", "content": ex[:10000]})
    return out


def call_people_intel(
    *,
    person: str,
    company: str | None,
    snippets: Sequence[Dict[str, str]],
    notes: str | None = None,
    client: Optional[httpx.Client] = None,
) -> Optional[Dict[str, Any]]:
    """POST to WhoIsWhat people-intel. Returns parsed JSON or None on failure."""
    url = people_intel_post_url()
    if not url:
        return None
    payload: Dict[str, Any] = {
        "person": (person or "").strip(),
        "snippets": [dict(x) for x in snippets if (x.get("content") or "").strip()],
    }
    co = (company or "").strip()
    if co:
        payload["company"] = co
    no = (notes or "").strip()
    if no:
        payload["notes"] = no

    if not payload["snippets"]:
        logger.debug("people_intel skipped: no non-empty snippets for %s", person)
        return None

    try:
        if client is not None:
            r = client.post(url, json=payload)
        else:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as c:
                r = c.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(
                "people_intel %s returned HTTP %s: %s",
                url,
                r.status_code,
                (r.text or "")[:400],
            )
            return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except Exception:
        logger.exception("people_intel request to %s failed", url)
        return None


__all__ = [
    "call_people_intel",
    "is_configured",
    "people_intel_post_url",
    "snippets_from_posting_person",
    "snippets_from_web_hit",
]
