"""LLM polish for cover letters, guardrailed against the truth model.

Reuses the same guard helpers as `app.services.llm_rewrite` so a cover
letter can never invent:
- numbers (team sizes, years, metrics, dollar amounts),
- tools/frameworks that aren't in the truth model or the JD,
- companies or titles.

The user passes in a deterministic cover letter (already safe, built from
the truth model in `app.packaging.cover_letter._deterministic_cover_letter`)
and the LLM is asked to mirror the job description's vocabulary, tighten
the voice, and remove soft filler, without changing the underlying facts.

If the LLM output fails the guardrail, we return `None` so the caller can
fall back to the deterministic version.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.company_resolve import is_placeholder_company
from app.services.data_loader import load_archetypes
from app.services.llm import complete_json, is_available
from app.services.llm_rewrite import (
    _is_safe_rewrite,
    _tokens_in,
    _truth_allowed_tokens,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a senior resume and cover-letter editor. Your only job is to "
    "polish a cover letter that has already been drafted from a candidate's "
    "verified experience. You may tighten language and mirror the job "
    "description's vocabulary, but you may NEVER:\n"
    "- invent metrics, percentages, team sizes, years, dollar amounts,\n"
    "- add tools/frameworks/companies that aren't in the source letter or JD,\n"
    "- change the candidate's name, current employer, or past employers,\n"
    "- add claims the source letter does not already support.\n\n"
    "Style: 3-4 short paragraphs, senior-engineer voice, concrete over vague, "
    "no 'passionate about', no 'excited to contribute', no soft filler."
)


def rewrite_cover_letter(
    *,
    deterministic_cover_letter: str,
    job_description: str,
    company: str,
    title: str,
    archetype_id: str,
) -> Optional[str]:
    """Return a polished cover letter, or None if the LLM output was
    unsafe / unavailable (caller should use the deterministic version)."""
    if not is_available():
        return None

    archetypes = load_archetypes()
    archetype = archetypes.get(archetype_id, {})
    scale = archetype.get("scale_phrase", "distributed backend systems")
    domain = archetype.get("domain_phrase", "production environments")
    specializations = ", ".join(archetype.get("specializations", []) or [])
    focus_traits = ", ".join(archetype.get("focus_traits", []) or [])

    target_co = (company or "").strip()
    if is_placeholder_company(target_co):
        target_co = (
            "not stated in the listing (use a generic salutation such as "
            "'Dear hiring team' — do not invent an employer name)"
        )

    user_prompt = (
        f"Target company: {target_co}\n"
        f"Target role:    {title}\n"
        f"Archetype hints - scale: '{scale}'; domain: '{domain}'; "
        f"specializations: {specializations}; focus traits: {focus_traits}.\n\n"
        f"Job description:\n---\n{(job_description or '').strip()[:4000]}\n---\n\n"
        f"Source cover letter (already guardrailed against the truth model; "
        f"every claim here is safe):\n---\n{deterministic_cover_letter.strip()}\n---\n\n"
        "Rewrite the cover letter. Produce 3-4 short paragraphs (50-110 words "
        "each). Preserve the openers, the salutation, and the candidate's "
        "name. Mirror the JD's language where natural. Do NOT introduce new "
        "facts or metrics. Close with a concrete, low-filler sentence.\n\n"
        'Respond as JSON: {"cover_letter": "..."} — the value is the full '
        "cover letter text, with \\n\\n between paragraphs."
    )

    payload = complete_json(SYSTEM_PROMPT, user_prompt, max_tokens=900, temperature=0.3)
    if not isinstance(payload, dict):
        return None
    candidate = (payload.get("cover_letter") or "").strip()
    if not candidate:
        return None

    # Guardrail: the polished letter may freely reuse JD vocabulary but not
    # introduce more than ~12 material new tokens vs. the deterministic base
    # (longer budget than bullets because the letter has more text).
    allowed = _truth_allowed_tokens() | _tokens_in(job_description) | _tokens_in(company) | _tokens_in(title)
    if not _is_safe_rewrite(
        deterministic_cover_letter, candidate, allowed, max_new_material=12
    ):
        return None

    return candidate


__all__ = ["rewrite_cover_letter", "is_available"]
