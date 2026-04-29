"""Extract named contacts from job posting + optional apply-page text.

Uses the OpenAI JSON helper when ``use_llm`` and keys allow; otherwise returns
no names (deterministic tests stay offline). Follow-up web queries are built for
each plausible ``First Last``-style name plus company label.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List

from app.scrapers.base import RawJob
from app.services.jd_fetcher import fetch_jd
from app.services.llm import complete_json, is_available

logger = logging.getLogger(__name__)

_MAX_CORPUS_CHARS = 12_000

_LLM_SYSTEM = """You extract real people named in job posting or careers-page text
who a job seeker might contact (recruiter, hiring manager, talent partner,
engineering manager, interviewer, named team lead, person tied to a posted email).
Rules:
- Only include people explicitly named in the text. Do NOT invent or guess names.
- If a string might not be a person's name, omit it.
- role_hint: short label from context (e.g. "Engineering Manager", "Recruiter").
- evidence: the shortest exact phrase copied from the input that supports the name (max 180 chars).

Return JSON with this shape only:
{"people": [{"name": "", "role_hint": "", "evidence": ""}]}
Use {"people": []} when there are no qualifying names."""

_BANNED_LOWERCASE = frozenset(
    {
        "apply",
        "submit",
        "click",
        "here",
        "team",
        "company",
        "applicant",
        "candidate",
        "role",
        "position",
        "description",
        "requirements",
        "benefits",
        "overview",
        "summary",
        "responsibilities",
        "qualifications",
    }
)


@dataclass
class PostingPerson:
    name: str
    role_hint: str = ""
    evidence: str = ""


def merge_posting_corpus(raw: RawJob, *, fetch_apply_page: bool) -> str:
    """Join ``jd_full`` with optional ATS/apply page body (HTTP fetch)."""
    parts: List[str] = []
    jd = (raw.jd_full or "").strip()
    if jd:
        parts.append(jd)
    apply = (raw.apply_url or "").strip()
    listing = (raw.url or "").strip()
    if fetch_apply_page and apply and apply.rstrip("/") != listing.rstrip("/"):
        try:
            fj = fetch_jd(apply, timeout=14.0)
        except Exception:
            logger.debug("merge_posting_corpus: fetch_jd failed for apply_url", exc_info=True)
            fj = None
        else:
            if fj.error:
                logger.debug("merge_posting_corpus: apply page skipped: %s", fj.error[:120])
            elif (fj.raw.jd_full or "").strip():
                parts.append((fj.raw.jd_full or "").strip())
    corpus = "\n\n---\n\n".join(parts)
    if len(corpus) > _MAX_CORPUS_CHARS:
        corpus = corpus[:_MAX_CORPUS_CHARS] + "\n…"
    return corpus


def _name_plausible(name: str) -> bool:
    n = (name or "").strip()
    if len(n) < 4 or len(n) > 100:
        return False
    low = n.lower()
    if "http" in low or "www." in low or "@" in low:
        return False
    if not re.search(r"[a-zA-Z]", n):
        return False
    words = n.split()
    if len(words) < 2:
        return False
    if low in _BANNED_LOWERCASE:
        return False
    for w in words:
        if len(w) > 64:
            return False
        if re.search(r"\d", w):
            return False
        if not re.match(r"^[A-Za-z][A-Za-z'\-\.]*$", w):
            return False
    return True


def extract_people_from_posting_corpus(
    corpus: str,
    company: str,
    *,
    max_people: int,
    use_llm: bool,
) -> List[PostingPerson]:
    if not (corpus or "").strip() or max_people <= 0:
        return []
    if not (use_llm and is_available()):
        return []
    user = f"Company label (may be incomplete): {company}\n\nJob posting text:\n{corpus}"
    data = complete_json(_LLM_SYSTEM, user, max_tokens=900, temperature=0.15)
    if not isinstance(data, dict):
        return []
    rows = data.get("people")
    if not isinstance(rows, list):
        return []
    out: List[PostingPerson] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not _name_plausible(name):
            continue
        out.append(
            PostingPerson(
                name=name,
                role_hint=str(row.get("role_hint") or "").strip()[:120],
                evidence=str(row.get("evidence") or "").strip()[:200],
            )
        )
        if len(out) >= max_people:
            break
    return out


def build_followup_queries(
    people: List[PostingPerson],
    company: str,
    *,
    max_queries: int,
) -> List[str]:
    """One quoted-name + company query per person (deduped)."""
    if not people or max_queries <= 0:
        return []
    co = (company or "").strip() or "company"
    qs: List[str] = []
    seen: set[str] = set()
    for p in people:
        if len(qs) >= max_queries:
            break
        if not _name_plausible(p.name):
            continue
        q = f"\"{p.name}\" {co}"
        low = q.lower()
        if low in seen:
            continue
        seen.add(low)
        qs.append(q)
    return qs


__all__ = [
    "PostingPerson",
    "merge_posting_corpus",
    "extract_people_from_posting_corpus",
    "build_followup_queries",
]
