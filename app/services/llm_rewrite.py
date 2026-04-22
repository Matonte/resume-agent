"""LLM rewrite pass, guarded by the truth model.

These functions take deterministic text that was pulled from the truth model
(a summary or a list of bullets) and ask the model to polish the language to
mirror the job description — WITHOUT inventing metrics, tools, dates, scope,
or titles.

Every function falls back to its deterministic input if:
- no API key is set,
- the LLM call fails,
- the response violates guardrails (e.g. introduces numbers or tools not in
  the source bullet).

Tests run offline by default; turn LLM on by setting `OPENAI_API_KEY`.
"""

from __future__ import annotations

import logging
import re
from typing import List

from app.services.data_loader import load_archetypes, load_truth_model
from app.services.llm import complete_json, is_available

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a senior resume editor helping a software engineer tailor a real resume "
    "to a specific job description. Your job is to produce bullets and summaries that "
    "sound senior, concrete, and results-oriented — each bullet should read as "
    "action + system (with scale context) + outcome.\n\n"
    "HARD CONSTRAINTS:\n"
    "- NEVER invent metrics, percentages, team sizes, durations, dollar amounts, or "
    "specific tools/frameworks/clouds that aren't in the source text.\n"
    "- NEVER change companies, titles, or dates.\n"
    "- Every factual claim in your output must already be supported by the source.\n\n"
    "ENCOURAGED:\n"
    "- Mirror the job description's vocabulary where it naturally fits.\n"
    "- Surface scale and impact that are ALREADY implied by the source (e.g., a bullet "
    "about a production backend platform can say 'in production' or 'under production "
    "load'; a bullet about high-volume ingestion can say 'high-volume' or 'high-throughput'; "
    "a bullet about microservices can say 'distributed backend services').\n"
    "- Prefer concrete scale phrasing over generic adjectives: 'high-throughput', "
    "'real-time', 'distributed', 'production', 'low-latency', 'event-driven', "
    "'enterprise-scale' — only when the source already implies them.\n"
    "- Vary the OUTCOME half across bullets. Do not close three bullets in a row with "
    "'improving reliability' or 'improving observability'. Rotate across these "
    "impact dimensions as supported by each source: scalability, performance / "
    "latency, developer experience / velocity, cost reduction, architecture clarity, "
    "reliability, observability. Each bullet should land on a different dimension "
    "when possible.\n"
    "- Avoid soft filler: 'effective collaboration', 'various', 'several', 'helped with'.\n"
    "Output must be senior, concrete, and defensible in an interview."
)


# --------------------------- guardrails ---------------------------

# Numbers: catch any digit run with optional decimals/commas.
_NUM_RE = re.compile(r"\d[\d,\.]*")
# Tokens: letter-led sequences, with trailing punctuation stripped. We only
# use this set for "is this word introduced?" checks, so losing edge cases
# like "Node.js" is fine — worst case the guardrail is slightly stricter.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+\-/#]{2,}")

# Words that appear in rewrites but not in the source without being factually
# dangerous — allow them through.
_SAFE_NEW_TOKENS = {
    # connectors / stopwords
    "and", "the", "for", "with", "that", "this", "from", "into", "about",
    "across", "using", "where", "under", "over", "within", "while",
    # scope / action words
    "built", "build", "building", "led", "leads", "leading", "own", "owned",
    "owning", "improved", "improving", "improve", "designed", "designing",
    "design", "delivered", "deliver", "delivering", "supporting", "supports",
    "support", "include", "includes", "emphasis", "proven", "focus", "focused",
    # senior / scale / impact vocabulary that is safe to surface when source
    # already implies it (backend service, production system, distributed etc.)
    "platform", "platforms", "systems", "system", "service", "services",
    "backend", "distributed", "production", "production-ready", "scalable",
    "scalability", "scale", "senior", "reliable", "reliability", "resilience",
    "resilient", "performance", "performant", "throughput", "high-throughput",
    "low-latency", "latency", "real-time", "realtime", "event-driven",
    "concurrent", "concurrency", "fault-tolerant", "resilient", "enterprise",
    "enterprise-scale", "workflow", "workflows", "operational", "operations",
    "impact", "incident", "detection", "monitoring", "observability",
    "pipeline", "pipelines", "ingestion", "streaming", "high-volume",
    # experience / positioning
    "experience", "experienced", "strengths", "strength", "years", "decade",
    "specializes", "specializing", "specialized",
    # domain
    "financial", "finance", "fintech", "regulated", "compliance",
}


def _numbers_in(text: str) -> set[str]:
    return set(m.group(0) for m in _NUM_RE.finditer(text or ""))


def _tokens_in(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def _is_safe_rewrite(
    source: str,
    rewrite: str,
    allowed_tokens: set[str],
    *,
    max_new_material: int = 3,
) -> bool:
    """A rewrite is safe when:
    - it doesn't invent new numeric facts, AND
    - the number of *material* new tokens (not in source, allowed tokens,
      or the safe-vocab list) stays under `max_new_material`.

    Bullets use a tight limit (3) because every word is a factual claim.
    Summaries use a looser limit (6) because their job is to mirror the JD's
    vocabulary. Either way, new numbers are always rejected.
    """
    src_numbers = _numbers_in(source)
    rew_numbers = _numbers_in(rewrite)
    new_numbers = rew_numbers - src_numbers
    if new_numbers:
        logger.warning("LLM rewrite introduced new numbers %s; rejecting", new_numbers)
        return False

    src_tokens = _tokens_in(source)
    rew_tokens = _tokens_in(rewrite)
    new_tokens = rew_tokens - src_tokens - allowed_tokens - _SAFE_NEW_TOKENS
    suspicious = {t for t in new_tokens if len(t) > 3}
    if len(suspicious) > max_new_material:
        logger.warning(
            "LLM rewrite introduced too many new material tokens (%d > %d): %s",
            len(suspicious),
            max_new_material,
            suspicious,
        )
        return False
    return True


def _truth_allowed_tokens() -> set[str]:
    truth = load_truth_model()
    allowed: set[str] = set()
    for role in truth.get("roles", []):
        allowed |= _tokens_in(" ".join(role.get("tech", [])))
        allowed |= _tokens_in(" ".join(role.get("themes", [])))
        allowed |= _tokens_in(role.get("company", ""))
        allowed |= _tokens_in(role.get("title", ""))
        for fact in role.get("core_facts", []):
            allowed |= _tokens_in(fact)
    skills = truth.get("candidate", {}).get("skills", {}) or {}
    for v in skills.values():
        if isinstance(v, list):
            allowed |= _tokens_in(" ".join(v))
    return allowed


# --------------------------- rewriters ---------------------------


def rewrite_summary(
    deterministic_summary: str,
    job_description: str,
    archetype_id: str,
) -> str:
    """Polish the summary to mirror the JD's language. Falls back to the
    deterministic summary on any failure."""
    if not is_available():
        return deterministic_summary
    archetypes = load_archetypes()
    archetype = archetypes.get(archetype_id, {})
    scale = archetype.get("scale_phrase", "distributed backend systems")
    domain = archetype.get("domain_phrase", "production environments")
    specializations = ", ".join(archetype.get("specializations", []) or [])
    focus_traits = ", ".join(archetype.get("focus_traits", []) or [])

    user_prompt = (
        f"Job description:\n---\n{job_description.strip()[:4000]}\n---\n\n"
        f"Current summary (deterministic baseline):\n---\n{deterministic_summary.strip()}\n---\n\n"
        f"Archetype positioning hints — scale phrase: '{scale}'; domain: '{domain}'; "
        f"specializations: {specializations}; focus traits: {focus_traits}.\n\n"
        "Rewrite the summary as EXACTLY 2 short sentences using this shape:\n"
        "Sentence 1: '<Senior Title> with <N>+ years of experience building <scale phrase> "
        "in <domain>.'\n"
        "Sentence 2: 'Specializes in <A, B, and C>, with a focus on <X, Y, and Z>.'\n\n"
        "- Preserve the years of experience and seniority from the current summary.\n"
        "- Use the scale/domain/specializations/focus hints verbatim where they fit the JD, "
        "or tighten them to mirror the JD's own vocabulary.\n"
        "- Do NOT invent tools, metrics, companies, or team sizes.\n"
        "- Avoid soft filler like 'effective collaboration', 'passionate about'.\n\n"
        'Respond as JSON: {"summary": "..."}'
    )
    payload = complete_json(SYSTEM_PROMPT, user_prompt, max_tokens=400, temperature=0.3)
    if not isinstance(payload, dict):
        return deterministic_summary
    candidate = (payload.get("summary") or "").strip()
    if not candidate:
        return deterministic_summary

    allowed = _truth_allowed_tokens()
    # Summaries get a looser budget: their whole job is to mirror JD language.
    if not _is_safe_rewrite(deterministic_summary, candidate, allowed, max_new_material=6):
        return deterministic_summary
    return candidate


def rewrite_bullets(
    source_bullets: List[str],
    job_description: str,
) -> List[str]:
    """Rewrite each bullet to mirror JD language. Per-bullet guardrails:
    a single unsafe rewrite falls back to the original for that bullet only."""
    if not source_bullets:
        return []
    if not is_available():
        return list(source_bullets)

    numbered = "\n".join(f"{i + 1}. {b}" for i, b in enumerate(source_bullets))
    user_prompt = (
        f"Job description:\n---\n{job_description.strip()[:4000]}\n---\n\n"
        f"Source bullets (each is a real past-tense accomplishment from a truth model):\n"
        f"---\n{numbered}\n---\n\n"
        "For each bullet, produce a rewrite in the shape of "
        "ACTION + SYSTEM (with scale context already implied by the source) + OUTCOME. "
        "Requirements:\n"
        "- preserve every factual claim (tools, metrics, actions, outcomes) exactly,\n"
        "- add scale/impact phrasing ONLY where it is already implied by the source "
        "(e.g., a backend service bullet can say 'distributed backend services' or "
        "'under production load'; a high-volume ingestion bullet can say 'high-throughput'),\n"
        "- mirror the job description's vocabulary where natural,\n"
        "- stays in the same past-tense senior-engineer voice,\n"
        "- one sentence, ideally 18-32 words.\n"
        "VARIETY REQUIREMENT: across the full set, rotate outcome types — "
        "scalability, performance / latency, developer experience / velocity, "
        "cost reduction, architecture clarity, reliability, observability. "
        "Do NOT end multiple bullets with the same phrase such as 'improving reliability' "
        "or 'improving observability'. If the source already dictates a specific outcome "
        "(e.g., '90% cost reduction'), keep that outcome and choose a different dimension "
        "for neighboring bullets.\n"
        "Do NOT invent new numbers, percentages, tools, frameworks, clouds, team sizes, "
        "or scope that are not already implied by the source bullet.\n\n"
        'Respond as JSON: {"bullets": ["rewrite 1", "rewrite 2", ...]} '
        "in the exact order of the source bullets and with the same count."
    )
    payload = complete_json(SYSTEM_PROMPT, user_prompt, max_tokens=1600, temperature=0.3)
    if not isinstance(payload, dict):
        return list(source_bullets)
    rewrites = payload.get("bullets")
    if not isinstance(rewrites, list) or len(rewrites) != len(source_bullets):
        return list(source_bullets)

    allowed = _truth_allowed_tokens() | _tokens_in(job_description)
    final: List[str] = []
    for src, rew in zip(source_bullets, rewrites):
        rew_s = (rew or "").strip()
        if not rew_s or not _is_safe_rewrite(src, rew_s, allowed, max_new_material=4):
            final.append(src)
        else:
            final.append(rew_s)
    return final


__all__ = ["rewrite_summary", "rewrite_bullets", "is_available"]
