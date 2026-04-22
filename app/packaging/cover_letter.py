"""Cover letter generation.

This module is the public surface used by the runner. The LLM pass with
truth-model guardrails is implemented in the `cover-letter` task and shares
helpers with `app.services.llm_rewrite`. For now we expose a single
`build_cover_letter(...)` that returns text; `write_cover_letter_docx`
persists it as a .docx inside the per-job artifact folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from docx import Document

from app.services.data_loader import load_archetypes, load_truth_model


def _deterministic_cover_letter(
    *,
    candidate_name: str,
    company: str,
    title: str,
    archetype_id: str,
) -> str:
    """Fallback cover letter assembled from the truth model only. Used when
    the LLM is unavailable or its output fails guardrails."""
    truth = load_truth_model()
    archetypes = load_archetypes()
    archetype = archetypes.get(archetype_id) or {}

    candidate = truth.get("candidate", {})
    years = candidate.get("years_experience", 10)
    headline = archetype.get("headline_title") or candidate.get("headline", "Senior Backend Engineer")
    scale = archetype.get("scale_phrase", "distributed backend systems")
    domain = archetype.get("domain_phrase", "financial and enterprise environments")
    specializations = archetype.get("specializations") or []
    focus_traits = archetype.get("focus_traits") or []

    spec_str = ", ".join(specializations[:3]) if specializations else "backend architecture"
    focus_str = ", ".join(focus_traits[:3]) if focus_traits else "reliability"

    current_role = next(
        (r for r in truth.get("roles", []) if r.get("is_current")),
        (truth.get("roles") or [None])[0],
    )
    current_company = (current_role or {}).get("company", "")
    signature = (current_role or {}).get("signature_project") or ""

    paragraphs = [
        f"Dear {company} hiring team,",
        (
            f"I'm {candidate_name or 'a'} {headline} with {years}+ years of experience "
            f"building {scale} in {domain}. I'm writing to express interest in your "
            f"{title} role."
        ),
        (
            f"My recent work at {current_company} has focused on {spec_str}, with a "
            f"focus on {focus_str}."
            + (f" I led {signature}, a production system that is representative of the "
               f"impact I would bring to {company}." if signature else "")
        ),
        (
            f"I would welcome the chance to talk about how that background maps to "
            f"the {title} role on your team."
        ),
        "Sincerely,\n" + (candidate_name or ""),
    ]
    return "\n\n".join(p for p in paragraphs if p)


def build_cover_letter(
    *,
    candidate_name: str,
    company: str,
    title: str,
    archetype_id: str,
    job_description: str,
    use_llm: bool = False,
) -> str:
    """Return the cover letter body.

    If `use_llm` is True and the LLM is available, we route through
    `app.packaging.llm_cover_letter.rewrite_cover_letter` (wired up in the
    `cover-letter` task). Otherwise we return the deterministic fallback.

    The LLM module imports lazily so tests can exercise this function
    without OpenAI installed or configured.
    """
    base = _deterministic_cover_letter(
        candidate_name=candidate_name, company=company, title=title, archetype_id=archetype_id,
    )
    if not use_llm:
        return base
    try:  # pragma: no cover - import-time optional
        from app.packaging.llm_cover_letter import rewrite_cover_letter, is_available
    except Exception:
        return base
    if not is_available():
        return base
    polished = rewrite_cover_letter(
        deterministic_cover_letter=base,
        job_description=job_description,
        company=company,
        title=title,
        archetype_id=archetype_id,
    )
    return polished or base


def write_cover_letter_docx(text: str, path: Path) -> Path:
    """Write a minimal .docx cover letter at `path` (one paragraph per
    blank-line-separated chunk)."""
    doc = Document()
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        doc.add_paragraph(chunk)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


__all__ = ["build_cover_letter", "write_cover_letter_docx"]
