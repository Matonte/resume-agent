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
from app.services.evidence_schema import (
    core_fact_texts,
    evidence_for_bullet,
    iter_achievements,
)
from app.services.requirement_matcher import (
    achievement_scores_from_matches,
    match_requirements_to_evidence,
)

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
    evidence_id: str
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
    for fact in core_fact_texts(role):
        role_terms.update(_tokenize(fact))

    matched = sorted(job_tokens & role_terms)
    return float(len(matched)), matched


def _rank_bullets(job_description: str) -> List[_ScoredBullet]:
    """Score every truth-model bullet against the JD.

    Scoring layers:
    - role_score: how many JD tokens overlap the role's themes/tech/facts overall
    - fact_match * 1.5: direct token overlap with the bullet itself (strongest)
    - requirement match * 4: best requirement→evidence score for this achievement
    - recency bonus: more recent roles get a small boost so we don't lead with
      decade-old bullets when the overlap is tied
    - current-role bonus: the signature / current role gets an extra push so
      the most recent (usually strongest-positioned) role anchors the resume
    """
    truth = load_truth_model()
    job_tokens = set(_tokenize(job_description))
    req_matches = match_requirements_to_evidence(job_description, truth)
    evid_boost = achievement_scores_from_matches(req_matches)
    ranked: List[_ScoredBullet] = []

    roles = truth.get("roles", [])
    for idx, role in enumerate(roles):
        role_score, _matched = _score_role(role, job_tokens)
        company = role.get("company", "")
        is_current = bool(role.get("is_current")) or (idx == 0 and not role.get("end"))
        recency_bonus = max(0.0, 1.5 - idx * 0.25)
        current_bonus = 2.0 if is_current else 0.0
        for ach in iter_achievements(role):
            fact = ach.get("text") or ""
            if not fact:
                continue
            status = str(ach.get("status") or "").lower()
            try:
                conf = float(ach.get("confidence") if ach.get("confidence") is not None else 1.0)
            except (TypeError, ValueError):
                conf = 1.0
            # Omit weak inferences rather than present them as experience.
            if status == "inferred" and conf < 0.55:
                continue
            eid = str(ach.get("id") or "")
            fact_tokens = set(_tokenize(fact))
            fact_match = len(fact_tokens & job_tokens)
            req_bonus = evid_boost.get(eid, 0.0) * 4.0
            ranked.append(
                _ScoredBullet(
                    bullet=fact,
                    evidence_id=eid,
                    role_company=company,
                    role_index=idx,
                    is_current=is_current,
                    score=role_score
                    + (fact_match * 1.5)
                    + req_bonus
                    + recency_bonus
                    + current_bonus,
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


def _tokens_in(text: str) -> set:
    return {m.group(0).lower() for m in re.finditer(r"[A-Za-z][A-Za-z0-9+\-/#]{2,}", text or "")}


_INDUSTRY_TOKENS = {
    "financial",
    "finance",
    "fintech",
    "banking",
    "healthcare",
    "retail",
    "industrial",
    "regulated",
    "compliance",
    "enterprise",
}


def _profile_token_blob(truth: Dict) -> set:
    blob_parts: List[str] = []
    cand = truth.get("candidate") or {}
    blob_parts.append(str(cand.get("headline") or ""))
    skills = cand.get("skills") or {}
    if isinstance(skills, dict):
        for v in skills.values():
            if isinstance(v, list):
                blob_parts.extend(str(x) for x in v)
            elif isinstance(v, str):
                blob_parts.append(v)
    for role in truth.get("roles") or []:
        blob_parts.append(str(role.get("company") or ""))
        blob_parts.append(str(role.get("title") or ""))
        blob_parts.extend(str(t) for t in (role.get("themes") or []))
        blob_parts.extend(str(t) for t in (role.get("tech") or []))
        for fact in role.get("core_facts") or []:
            blob_parts.append(str(fact))
        for ach in role.get("achievements") or []:
            if isinstance(ach, dict):
                blob_parts.append(str(ach.get("text") or ""))
    return _tokens_in(" ".join(blob_parts))


def _ground_industry_phrase(truth: Dict, phrase: str, *, fallback: str) -> str:
    """Drop industry/employer-ish words that are not already in the profile."""
    allowed = _profile_token_blob(truth)
    words = (phrase or "").split()
    kept: List[str] = []
    for w in words:
        bare = re.sub(r"[^A-Za-z0-9+\-/#]", "", w).lower()
        if bare in _INDUSTRY_TOKENS and bare not in allowed:
            continue
        kept.append(w)
    grounded = " ".join(kept).strip(" ,")
    grounded = re.sub(r"\s+", " ", grounded)
    grounded = re.sub(r"\b(and|or|in|of|the)\s+(and|or|in|of|the)\b", r"\1", grounded, flags=re.I)
    grounded = re.sub(r"^(and|or)\s+", "", grounded, flags=re.I)
    grounded = re.sub(r"\s+(and|or)$", "", grounded, flags=re.I)
    grounded = grounded.strip(" ,")
    return grounded if grounded else fallback


def _archetype_summary(archetype_id: str, truth: Dict) -> str:
    """Render the positioning summary using the archetype's scale/domain phrases.

    Years of experience are taken only from the candidate profile when set —
    never invented. Industry words in scale/domain are kept only when the
    profile already contains them.
    """
    archetypes = load_archetypes()
    archetype = archetypes.get(archetype_id) or archetypes.get("A_general_ai_platform") or {}

    raw_years = truth.get("candidate", {}).get("years_experience")
    years: Optional[int] = None
    try:
        if raw_years is not None and str(raw_years).strip() != "":
            y = int(raw_years)
            if y > 0:
                years = y
    except (TypeError, ValueError):
        years = None

    cand_headline = ((truth.get("candidate") or {}).get("headline") or "").strip()
    headline_title = (
        cand_headline
        or archetype.get("headline_title")
        or "Software Engineer"
    )

    scale = _ground_industry_phrase(
        truth,
        archetype.get("scale_phrase") or "backend systems",
        fallback="software systems",
    )
    domain = _ground_industry_phrase(
        truth,
        archetype.get("domain_phrase") or "production environments",
        fallback="production environments",
    )

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

    if years is not None:
        sentence1 = (
            f"{headline_title} with {years}+ years of experience building {scale} in {domain}."
        )
    else:
        sentence1 = f"{headline_title} with experience building {scale} in {domain}."

    return (
        f"{sentence1} "
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
    *,
    profile_id: Optional[int] = None,
) -> Dict:
    ranked = _rank_bullets(job_description)

    # The current role is the resume's anchor and deserves more bullets than
    # past roles; older companies are capped at 2 so the draft doesn't get
    # pulled backward in time.
    # Hard gate: never select a bullet without a stable evidence id.
    picked: List[str] = []
    picked_ids: List[str] = []
    per_company: Dict[str, int] = {}
    dropped_no_evidence = 0
    for b in ranked:
        if b.score <= 0:
            continue
        if not b.evidence_id:
            dropped_no_evidence += 1
            continue
        company_cap = 5 if b.is_current else (3 if b.role_index <= 1 else 2)
        if per_company.get(b.role_company, 0) >= company_cap:
            continue
        picked.append(b.bullet)
        picked_ids.append(b.evidence_id)
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
            for ach in iter_achievements(current_role):
                fact = ach.get("text") or ""
                eid = str(ach.get("id") or "")
                if not fact or not eid or fact in existing:
                    continue
                picked.insert(current_count, fact)
                picked_ids.insert(current_count, eid)
                current_count += 1
                if current_count >= 4:
                    break

    if not picked and roles:
        for ach in iter_achievements(roles[0])[:4]:
            eid = str(ach.get("id") or "")
            text = ach.get("text") or ""
            if not eid or not text:
                continue
            picked.append(text)
            picked_ids.append(eid)

    deterministic_summary = draft_summary(job_description, archetype_id)
    final_summary = deterministic_summary
    final_bullets = list(picked)
    final_ids = list(picked_ids)
    llm_applied = False

    rag_context = ""
    if profile_id is not None:
        try:
            from app.services.resume_rag import retrieve_rag_context
            from app.storage.db import get_conn

            with get_conn() as conn:
                rag_context = retrieve_rag_context(conn, profile_id, job_description)
        except Exception:
            rag_context = ""

    if use_llm:
        # Lazy import so the base tailor stays usable without the openai dep.
        from app.services.llm_rewrite import (
            is_available,
            rewrite_bullets,
            rewrite_summary,
        )

        if is_available():
            final_summary = rewrite_summary(
                deterministic_summary,
                job_description,
                archetype_id,
                rag_context=rag_context,
            )
            rewritten = rewrite_bullets(picked, job_description, rag_context=rag_context)
            # Preserve evidence ids by index; drop any rewrite without an id.
            paired_bullets: List[str] = []
            paired_ids: List[str] = []
            for i, bullet in enumerate(rewritten):
                eid = picked_ids[i] if i < len(picked_ids) else ""
                if not eid:
                    ev = evidence_for_bullet(truth, bullet)
                    eid = str((ev or {}).get("evidence_id") or "")
                if not eid:
                    dropped_no_evidence += 1
                    continue
                paired_bullets.append(bullet)
                paired_ids.append(eid)
            final_bullets = paired_bullets
            final_ids = paired_ids
            llm_applied = (
                final_summary != deterministic_summary or final_bullets != picked
            )

    # Final evidence gate — no claim without an evidence id.
    gated_bullets: List[str] = []
    gated_ids: List[str] = []
    for bullet, eid in zip(final_bullets, final_ids):
        if eid:
            gated_bullets.append(bullet)
            gated_ids.append(eid)
        else:
            dropped_no_evidence += 1
    final_bullets = gated_bullets
    final_ids = gated_ids

    notes = [
        "Accuracy guarantee: every claim stays grounded in your verified experience — we do not invent metrics, titles, tools, or dates.",
        "Each tailored bullet is evidence-backed; unsupported claims are dropped, not guessed.",
        "Optional job-language matching may rephrase wording, but not invent new numbers, tools, or scope.",
        "Quick check before you send: do metrics, titles, and tools still match what you actually did?",
    ]
    if dropped_no_evidence:
        notes.append(
            f"Dropped {dropped_no_evidence} bullet(s) that were not evidence-backed."
        )
    if archetype_id:
        notes.append(f"Resume focus template: `{archetype_id}`.")
    if use_llm and not llm_applied:
        notes.append("Job-language matching was requested but fell back to a deterministic draft.")

    clarifying_questions: List[str] = []
    raw_years = (truth.get("candidate") or {}).get("years_experience")
    years_set = False
    try:
        years_set = raw_years is not None and int(raw_years) > 0
    except (TypeError, ValueError):
        years_set = False
    if not years_set:
        clarifying_questions.append(
            "How many years of professional experience should we state on tailored resumes?"
        )
    weak_inferred = 0
    for role in truth.get("roles") or []:
        for ach in iter_achievements(role):
            status = str(ach.get("status") or "").lower()
            try:
                conf = float(ach.get("confidence") if ach.get("confidence") is not None else 1.0)
            except (TypeError, ValueError):
                conf = 1.0
            if status == "inferred" and conf < 0.55:
                weak_inferred += 1
    if weak_inferred:
        clarifying_questions.append(
            f"Confirm or remove {weak_inferred} low-confidence inferred claim(s) in your profile before sending."
        )
    if clarifying_questions:
        notes.append(
            "Clarifying questions (answer these instead of assuming): "
            + " ".join(clarifying_questions)
        )

    selected_evidence = []
    for bullet, eid in zip(final_bullets, final_ids):
        ev = evidence_for_bullet(truth, bullet)
        if ev and ev.get("evidence_id"):
            selected_evidence.append(ev)
        else:
            selected_evidence.append(
                {
                    "evidence_id": eid,
                    "text": bullet,
                    "status": "supported",
                    "evidence_source": None,
                    "role_company": None,
                    "role_id": None,
                }
            )

    return {
        "summary": final_summary,
        "selected_bullets": final_bullets,
        "evidence_ids": list(final_ids),
        "selected_evidence": selected_evidence,
        "requirement_matches": match_requirements_to_evidence(job_description, truth),
        "evidence_gated": True,
        "clarifying_questions": clarifying_questions,
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
        for fact in core_fact_texts(role):
            fact_tokens = set(_tokenize(fact))
            score = len(fact_tokens & job_tokens)
            scored.append((score, fact))

    scored.sort(key=lambda t: t[0], reverse=True)
    ordered = [fact for _, fact in scored]
    if not ordered:
        return core_fact_texts(matches[0])[:limit]

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
        if bullet in core_fact_texts(role):
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
