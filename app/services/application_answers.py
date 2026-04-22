"""Routes an application question to the best-matching template from the
answer bank, optionally biased by the job's archetype.

No invented content: every answer comes directly from
`data/application_answer_bank.json` and links (when applicable) back to a
story in `data/story_bank.json` via `supporting_story_ids`.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from app.services.data_loader import load_answer_bank

# Maps a bank category to the lowercase question substrings that trigger it.
# Order matters: more specific intents first so "why this company" beats "why".
INTENT_RULES: List[Tuple[str, List[str]]] = [
    ("why_this_company", ["why this company", "why us", "about our company", "interested in us"]),
    ("why_this_role", ["why this role", "why this position", "interested in the role", "interested in this role"]),
    ("ambiguity_example", ["ambigu", "unclear requirement", "changing requirement", "evolving requirement"]),
    ("ownership_example", ["ownership", "owned", "took the lead", "led the effort", "drove the project", "end to end"]),
]

# When multiple templates exist for a category, pick by archetype affinity.
ARCHETYPE_LABEL_PREFERENCE: Dict[str, Dict[str, str]] = {
    "why_this_role": {
        "B_fintech_transaction_systems": "fintech",
        "C_data_streaming_systems": "data_streaming",
        "D_distributed_systems": "backend_distributed",
        "A_general_ai_platform": "backend_distributed",
    },
    "why_this_company": {
        # Default nudge: infra-heavy archetypes -> infrastructure template.
        "D_distributed_systems": "infrastructure_company",
        "C_data_streaming_systems": "infrastructure_company",
        "B_fintech_transaction_systems": "product_company",
        "A_general_ai_platform": "product_company",
    },
}


def _detect_intent(question: str) -> Optional[str]:
    q = (question or "").lower()
    for category, needles in INTENT_RULES:
        for needle in needles:
            if needle in q:
                return category
    # Loose fallbacks on single keywords.
    if re.search(r"\blead(er|ing)?\b", q):
        return "ownership_example"
    if "company" in q and "why" in q:
        return "why_this_company"
    if "role" in q and "why" in q:
        return "why_this_role"
    return None


def _select_entry(category: str, entries: List[Dict], archetype_id: Optional[str]) -> Dict:
    if not entries:
        return {}
    if archetype_id and category in ARCHETYPE_LABEL_PREFERENCE:
        preferred_label = ARCHETYPE_LABEL_PREFERENCE[category].get(archetype_id)
        if preferred_label:
            for e in entries:
                if e.get("label") == preferred_label:
                    return e
    return entries[0]


def answer_application_question(
    question: str, archetype_id: Optional[str] = None
) -> Dict:
    bank = load_answer_bank()
    category = _detect_intent(question)

    if category and category in bank:
        entry = _select_entry(category, bank[category], archetype_id)
        if entry:
            return {
                "answer": entry.get("template", ""),
                "supporting_story_ids": [entry["story_id"]] if entry.get("story_id") else [],
            }

    return {
        "answer": (
            "No direct template matched. Draft from the story bank: pick one concrete story, "
            "lead with situation + action + outcome, and tie it back to the specific company "
            "or team. Keep it factual and defensible in an interview."
        ),
        "supporting_story_ids": [],
    }


__all__ = ["answer_application_question"]
