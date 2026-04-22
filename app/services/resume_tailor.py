"""Deterministic resume tailoring.

Inputs: a job description and an archetype id.
Outputs: a target summary, a prioritized bullet list drawn from the truth
model, and explicit "notes" reminding the user of guardrails.

Key ideas:
- The summary is assembled from the archetype metadata (`summary_focus`) so it
  reflects the resume's chosen angle, with a years-of-experience anchor from
  the truth model.
- Bullets are scored by how well each role's themes/tech/core_facts overlap
  with the tokens in the job description. The top-scoring bullets across
  roles are returned, never invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.services.data_loader import load_archetypes, load_truth_model

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about",
    "your", "you", "our", "are", "will", "have", "has", "been", "being",
    "a", "an", "of", "to", "in", "on", "at", "by", "as", "is", "it", "be",
    "or", "we", "us", "their", "they", "them", "who", "how", "what", "why",
    "across", "using", "build", "builds", "building", "built",
}

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")


def _tokenize(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS]


@dataclass
class _ScoredBullet:
    bullet: str
    role_company: str
    role_index: int
    score: float
    is_current: bool


def _score_role(role: Dict, job_tokens: set[str]) -> Tuple[float, List[str]]:
    """Return (score, matched_tokens) for a role vs. the JD."""
    role_terms = set()
    for key in ("themes", "tech"):
        for t in role.get(key, []):
            role_terms.update(_tokenize(t))
    for fact in role.get("core_facts", []):
        role_terms.update(_tokenize(fact))

    matched = sorted(job_tokens & role_terms)
    return float(len(matched)), matched


def _rank_bullets(job_description: str) -> List[_ScoredBullet]:
    """Score every truth-model bullet against the JD.

    Scoring layers:
    - role_score: how many JD tokens overlap the role's themes/tech/facts overall
    - fact_match * 1.5: direct token overlap with the bullet itself (strongest)
    - recency bonus: more recent roles get a small boost so we don't lead with
      decade-old bullets when the overlap is tied
    - current-role bonus: the signature / current role gets an extra push so
      the most recent (usually strongest-positioned) role anchors the resume
    """
    truth = load_truth_model()
    job_tokens = set(_tokenize(job_description))
    ranked: List[_ScoredBullet] = []

    roles = truth.get("roles", [])
    for idx, role in enumerate(roles):
        role_score, _matched = _score_role(role, job_tokens)
        company = role.get("company", "")
        is_current = bool(role.get("is_current")) or (idx == 0 and not role.get("end"))
        recency_bonus = max(0.0, 1.5 - idx * 0.25)
        current_bonus = 2.0 if is_current else 0.0
        for fact in role.get("core_facts", []):
            fact_tokens = set(_tokenize(fact))
            fact_match = len(fact_tokens & job_tokens)
            ranked.append(
                _ScoredBullet(
                    bullet=fact,
                    role_company=company,
                    role_index=idx,
                    is_current=is_current,
                    score=role_score + (fact_match * 1.5) + recency_bonus + current_bonus,
                )
            )

    ranked.sort(key=lambda b: b.score, reverse=True)
    return ranked


def _join_clause(items: List[str]) -> str:
    """Render a list as an Oxford-comma phrase: ['a','b','c'] -> 'a, b, and c'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _archetype_summary(archetype_id: str, truth: Dict) -> str:
    """Render the positioning summary using the archetype's scale/domain phrases.

    Template:
        "{headline_title} with {N}+ years of experience building {scale_phrase}
         in {domain_phrase}. Specializes in {specializations}, with a focus on
         {focus_traits}."

    Each archetype declares its own scale_phrase / domain_phrase /
    specializations / focus_traits so the output has a distinct POV for fintech
    (B) vs. distributed systems (D) vs. data/streaming (C) — no generic
    'effective collaboration' wording, no archetype-ambiguous phrasing.
    """
    archetypes = load_archetypes()
    archetype = archetypes.get(archetype_id) or archetypes.get("A_general_ai_platform") or {}

    years = truth.get("candidate", {}).get("years_experience", 10)
    headline_title = (
        archetype.get("headline_title")
        or truth.get("candidate", {}).get("headline")
        or "Senior Backend Engineer"
    )
    scale = archetype.get("scale_phrase") or "distributed backend systems"
    domain = archetype.get("domain_phrase") or "production environments"
    specializations = archetype.get("specializations") or [
        "backend architecture",
        "distributed systems",
        "production reliability",
    ]
    focus_traits = archetype.get("focus_traits") or [
        "reliability",
        "scalability",
        "production performance",
    ]

    return (
        f"{headline_title} with {years}+ years of experience building {scale} in {domain}. "
        f"Specializes in {_join_clause(specializations[:3])}, "
        f"with a focus on {_join_clause(focus_traits[:3])}."
    )


def draft_summary(job_description: str, archetype_id: str) -> str:
    truth = load_truth_model()
    return _archetype_summary(archetype_id, truth)


def generate_resume_draft(
    job_description: str,
    archetype_id: str,
    use_llm: bool = False,
) -> Dict:
    ranked = _rank_bullets(job_description)

    # The current role is the resume's anchor and deserves more bullets than
    # past roles; older companies are capped at 2 so the draft doesn't get
    # pulled backward in time.
    picked: List[str] = []
    per_company: Dict[str, int] = {}
    for b in ranked:
        if b.score <= 0:
            continue
        company_cap = 5 if b.is_current else (3 if b.role_index <= 1 else 2)
        if per_company.get(b.role_company, 0) >= company_cap:
            continue
        picked.append(b.bullet)
        per_company[b.role_company] = per_company.get(b.role_company, 0) + 1
        if len(picked) >= 10:
            break

    # Ensure the current role contributes at least 4 bullets (signature-project
    # visibility). If the JD overlap alone didn't reach 4, top it up with the
    # highest-ranked unused facts from the current role.
    truth = load_truth_model()
    roles = truth.get("roles", [])
    current_role = next(
        (r for r in roles if r.get("is_current") or not r.get("end")),
        roles[0] if roles else None,
    )
    if current_role:
        current_company = current_role.get("company", "")
        current_count = sum(1 for p in picked if _normalize_company(current_company) == _normalize_company(_company_for_bullet(p, roles)))
        if current_count < 4:
            existing = set(picked)
            for fact in current_role.get("core_facts", []):
                if fact in existing:
                    continue
                picked.insert(current_count, fact)
                current_count += 1
                if current_count >= 4:
                    break

    if not picked and roles:
        picked = list(roles[0].get("core_facts", []))[:4]

    deterministic_summary = draft_summary(job_description, archetype_id)
    final_summary = deterministic_summary
    final_bullets = picked
    llm_applied = False

    if use_llm:
        # Lazy import so the base tailor stays usable without the openai dep.
        from app.services.llm_rewrite import (
            is_available,
            rewrite_bullets,
            rewrite_summary,
        )

        if is_available():
            final_summary = rewrite_summary(deterministic_summary, job_description, archetype_id)
            final_bullets = rewrite_bullets(picked, job_description)
            llm_applied = (
                final_summary != deterministic_summary or final_bullets != picked
            )

    notes = [
        "Every claim traces back to `master_truth_model.json`; review before submission.",
        "LLM rewrites are guardrailed to not introduce new numbers, tools, or scope.",
        "Verify metrics, titles, and tools match the truth model before sending.",
    ]
    if archetype_id:
        notes.append(f"Base resume: archetype `{archetype_id}` (see `data/archetypes/`).")
    if use_llm and not llm_applied:
        notes.append("LLM requested but fell back to deterministic output.")

    return {
        "summary": final_summary,
        "selected_bullets": final_bullets,
        "notes": notes,
        "llm_applied": llm_applied,
    }


def rank_role_bullets(
    job_description: str, company: str, title: Optional[str] = None, limit: int = 8
) -> List[str]:
    """Return the role's core_facts ordered by relevance to the job description.

    Used by the DOCX generator to pick the N most-relevant bullets for a given
    role section in the template. Never invents text — all returned strings
    come directly from `master_truth_model.json`.
    """
    truth = load_truth_model()
    job_tokens = set(_tokenize(job_description))

    matches = [
        r for r in truth.get("roles", [])
        if _normalize_company(r.get("company", "")) == _normalize_company(company)
    ]
    if title:
        title_norm = _normalize_title(title)
        narrow = [r for r in matches if title_norm and title_norm in _normalize_title(r.get("title", ""))]
        if narrow:
            matches = narrow

    if not matches:
        return []

    scored: List[Tuple[float, str]] = []
    for role in matches:
        for fact in role.get("core_facts", []):
            fact_tokens = set(_tokenize(fact))
            score = len(fact_tokens & job_tokens)
            scored.append((score, fact))

    scored.sort(key=lambda t: t[0], reverse=True)
    ordered = [fact for _, fact in scored]
    if not ordered:
        return list(matches[0].get("core_facts", []))[:limit]

    seen: set[str] = set()
    unique: List[str] = []
    for fact in ordered:
        if fact not in seen:
            seen.add(fact)
            unique.append(fact)
        if len(unique) >= limit:
            break
    return unique


def _company_for_bullet(bullet: str, roles: List[Dict]) -> str:
    """Reverse-lookup which role a bullet came from. Used when we top up the
    current role's bullet count after the main ranking pass."""
    for role in roles:
        if bullet in role.get("core_facts", []):
            return role.get("company", "")
    return ""


def _normalize_title(raw: str) -> str:
    """Lowercase and collapse whitespace so 'Contractor  Software Engineer'
    matches 'Contractor Software Engineer'."""
    return re.sub(r"\s+", " ", (raw or "").strip().lower())


def _normalize_company(raw: str) -> str:
    """Normalize a company string so template headers and truth-model entries match.

    Handles common variants like 'JP Morgan & Chase' vs 'JP Morgan Chase',
    'CapGemini (client: Synchrony Bank)' vs 'CapGemini', whitespace/punctuation.
    """
    if not raw:
        return ""
    s = raw.strip()
    # Drop anything after a parenthesis (client details, etc.) for matching.
    if "(" in s:
        s = s.split("(")[0]
    s = re.sub(r"[^a-zA-Z0-9]+", "", s).lower()
    aliases = {
        "jpmorgan": "jpmorganchase",
        "jpmorganchase": "jpmorganchase",
        "jpmorganampchase": "jpmorganchase",
    }
    return aliases.get(s, s)


__all__ = [
    "generate_resume_draft",
    "draft_summary",
    "rank_role_bullets",
    "_normalize_company",
]
