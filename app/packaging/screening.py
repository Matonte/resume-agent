"""Screening-question extraction and answering.

Two public functions:
    extract_questions(text_or_html) -> list[str]
    answer_questions(questions, archetype_id) -> list[dict]

`extract_questions` is a best-effort heuristic: sentence ending in "?"
inside the JD/apply page. A richer LLM-based extractor can be wired into
`_llm_extract_questions` in a later pass.

`answer_questions` routes each question through the existing
`app.services.application_answers.answer_application_question` so we reuse
the archetype-biased templates and story-bank lookups.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.application_answers import answer_application_question


# Simple sentence-boundary extractor.
_QUESTION_RE = re.compile(r"(?P<sentence>[^.?!\n]{12,240}\?)", re.MULTILINE)


# A list of prompts common on application forms. We always include the most
# frequent ones so the candidate has draft answers ready even if the
# scraped page doesn't expose them yet.
_DEFAULT_PROMPTS: List[str] = [
    "Why are you interested in this role?",
    "What makes you a strong fit for this team?",
    "Tell us about a backend system you built that had to be reliable at scale.",
]


def _strip_html(text_or_html: str) -> str:
    """Cheap HTML -> text so the regex isn't fooled by tags. We don't need
    BeautifulSoup here; scrapers already hand us mostly-plain JD text."""
    return re.sub(r"<[^>]+>", " ", text_or_html or "")


def extract_questions(text_or_html: str) -> List[str]:
    """Return deduped, cleaned candidate questions from a JD or apply page.
    Always appends `_DEFAULT_PROMPTS` so the candidate has draft answers
    to the most common screening questions."""
    cleaned = _strip_html(text_or_html or "")
    found = [m.group("sentence").strip() for m in _QUESTION_RE.finditer(cleaned)]
    seen: set[str] = set()
    out: List[str] = []
    for q in found + _DEFAULT_PROMPTS:
        key = re.sub(r"\s+", " ", q.strip()).lower()
        if key in seen or len(key) < 12:
            continue
        seen.add(key)
        out.append(re.sub(r"\s+", " ", q.strip()))
    return out[:10]


_NO_MATCH_MARKER = "No direct template matched"


def _llm_answer(question: str, archetype_id: Optional[str]) -> Optional[str]:
    """Ask the LLM to draft an answer ONLY when the deterministic layer
    didn't find a template. Guardrailed against fabricated numbers + tools.
    Returns None on any failure so the caller keeps the safe default."""
    try:  # pragma: no cover - optional path
        from app.services.llm import complete_json, is_available
        from app.services.llm_rewrite import (
            _is_safe_rewrite,
            _tokens_in,
            _truth_allowed_tokens,
        )
    except Exception:
        return None
    if not is_available():
        return None

    system = (
        "You are a senior resume and application editor. Draft a short answer "
        "(3-6 sentences) to an employer's application question. Use only the "
        "candidate's verified background. You MUST NOT invent metrics, tools, "
        "or employers that aren't already established. Prefer a concrete "
        "situation-action-outcome story over vague statements. No filler like "
        "'I am passionate about' or 'excited to contribute'."
    )
    user = (
        f"Archetype hint: {archetype_id or 'general backend'}.\n"
        f"Question: {question}\n\n"
        "Return JSON: {\"answer\": \"...\"}"
    )
    payload = complete_json(system, user, max_tokens=400, temperature=0.4)
    if not isinstance(payload, dict):
        return None
    candidate = (payload.get("answer") or "").strip()
    if not candidate:
        return None
    allowed = _truth_allowed_tokens() | _tokens_in(question)
    if not _is_safe_rewrite(
        "", candidate, allowed, max_new_material=18
    ):
        return None
    return candidate


def answer_questions(
    questions: List[str],
    archetype_id: Optional[str] = None,
    *,
    use_llm: bool = True,
) -> List[Dict[str, Any]]:
    """Answer each question via the existing application-answers service.

    If the deterministic layer has no matching template for a question and
    the LLM is configured, we ask the LLM for a short guardrailed answer.
    Each item in the return list is
    `{question, answer, supporting_story_ids, source}` where `source` is
    one of `template`, `llm`, or `fallback`.
    """
    out: List[Dict[str, Any]] = []
    for q in questions:
        try:
            result = answer_application_question(q, archetype_id)
        except Exception:  # pragma: no cover - defensive
            result = {"answer": "", "supporting_story_ids": []}

        answer = result.get("answer", "") if isinstance(result, dict) else str(result)
        support = (result.get("supporting_story_ids") or []) if isinstance(result, dict) else []
        source = "template"

        if use_llm and answer.startswith(_NO_MATCH_MARKER):
            llm_text = _llm_answer(q, archetype_id)
            if llm_text:
                answer = llm_text
                source = "llm"
            else:
                source = "fallback"

        out.append({
            "question": q,
            "answer": answer,
            "supporting_story_ids": support,
            "source": source,
        })
    return out


__all__ = ["extract_questions", "answer_questions"]
