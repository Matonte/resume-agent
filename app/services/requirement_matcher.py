"""Map job-description requirements to evidence-bearing achievements.

Deterministic token overlap — no LLM required. Used by the resume tailor to
prefer supported bullets and to expose a requirement→evidence audit trail.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.evidence_schema import iter_achievements

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about",
    "your", "you", "our", "are", "will", "have", "has", "been", "being",
    "a", "an", "of", "to", "in", "on", "at", "by", "as", "is", "it", "be",
    "or", "we", "us", "their", "they", "them", "who", "how", "what", "why",
    "across", "using", "experience", "required", "requirements", "must",
    "ability", "able", "strong", "preferred", "including", "etc",
}

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#\-]{1,}")
_BULLET_RE = re.compile(r"^\s*(?:[-*•●]|\d+[.)])\s+(.+)$")
_REQ_HINT = re.compile(
    r"\b(experience|proficien\w*|familiar|knowledge|skil\w*|require\w*|"
    r"must\s+have|background|years?)\b",
    re.I,
)


def _tokenize(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS]


def extract_requirements(job_description: str, *, limit: int = 12) -> List[str]:
    """Pull discrete requirements from a JD (bullets + requirement-like sentences)."""
    text = (job_description or "").strip()
    if not text:
        return []

    found: List[str] = []
    seen: set[str] = set()

    def _add(line: str) -> None:
        cleaned = re.sub(r"\s+", " ", (line or "").strip())
        if len(cleaned) < 20 or len(cleaned) > 280:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(cleaned)

    for raw in text.splitlines():
        m = _BULLET_RE.match(raw)
        if m:
            _add(m.group(1))

    if len(found) < 3:
        # Sentence fallback for prose JDs.
        for sent in re.split(r"(?<=[.!;])\s+", text):
            if _REQ_HINT.search(sent):
                _add(sent)

    if not found:
        # Last resort: densest non-empty lines.
        for raw in text.splitlines():
            _add(raw)
            if len(found) >= limit:
                break

    return found[:limit]


def _score_pair(req_tokens: set[str], ach_tokens: set[str], role_terms: set[str]) -> float:
    if not req_tokens:
        return 0.0
    direct = len(req_tokens & ach_tokens)
    role_boost = len(req_tokens & role_terms) * 0.25
    # Jaccard-ish normalized by requirement size so long bullets don't dominate.
    return min(1.0, (direct + role_boost) / max(3.0, float(len(req_tokens))))


def _reason(req_tokens: set[str], ach_text: str, company: str) -> str:
    hits = sorted(req_tokens & set(_tokenize(ach_text)))[:5]
    where = f" at {company}" if company else ""
    if hits:
        return f"Overlaps on {', '.join(hits)}{where}"
    return f"Related experience{where}"


def match_requirements_to_evidence(
    job_description: str,
    truth: Dict[str, Any],
    *,
    top_k: int = 3,
    min_score: float = 0.15,
) -> List[Dict[str, Any]]:
    """Return requirement objects with ranked achievement matches."""
    requirements = extract_requirements(job_description)
    catalog: List[Tuple[Dict[str, Any], Dict[str, Any], set[str]]] = []
    for role in truth.get("roles") or []:
        if not isinstance(role, dict):
            continue
        role_terms: set[str] = set()
        for key in ("themes", "tech"):
            for t in role.get(key) or []:
                role_terms.update(_tokenize(str(t)))
        for ach in iter_achievements(role):
            catalog.append((role, ach, role_terms))

    results: List[Dict[str, Any]] = []
    for req in requirements:
        req_tokens = set(_tokenize(req))
        scored: List[Dict[str, Any]] = []
        for role, ach, role_terms in catalog:
            text = ach.get("text") or ""
            ach_tokens = set(_tokenize(text))
            score = _score_pair(req_tokens, ach_tokens, role_terms)
            if score < min_score:
                continue
            company = str(role.get("company") or "")
            scored.append(
                {
                    "experienceId": ach.get("id"),
                    "score": round(score, 3),
                    "reason": _reason(req_tokens, text, company),
                    "text": text,
                    "role_company": company,
                    "status": ach.get("status") or "verified",
                }
            )
        scored.sort(key=lambda m: m["score"], reverse=True)
        results.append(
            {
                "requirement": req,
                "matches": scored[:top_k],
            }
        )
    return results


def achievement_scores_from_matches(
    requirement_matches: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Max score per evidence id across all requirements (for bullet ranking)."""
    scores: Dict[str, float] = {}
    for block in requirement_matches:
        for m in block.get("matches") or []:
            eid = m.get("experienceId")
            if not eid:
                continue
            s = float(m.get("score") or 0.0)
            scores[str(eid)] = max(scores.get(str(eid), 0.0), s)
    return scores


__all__ = [
    "extract_requirements",
    "match_requirements_to_evidence",
    "achievement_scores_from_matches",
]
