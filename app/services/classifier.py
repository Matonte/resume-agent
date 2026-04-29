"""Keyword + training-example classifier.

Scores each archetype by weighted signal sources:
1. Hand-authored keyword hints (domain intuition).
2. `best_for` / `summary_focus` fields from `archetypes.json`.
3. `keywords` from `training/classification_examples.json`, weighted most.

Produces a ClassificationResult with a normalized score and the top reasons
(matched phrases). This is deliberately deterministic so behavior is easy to
test and defend in an interview without relying on an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from app.models.schemas import ClassificationResult
from app.services.data_loader import (
    load_archetypes,
    load_classification_examples,
)

# Multi-word phrases must come before single words so we catch them first.
KEYWORD_HINTS: Dict[str, List[str]] = {
    "B_fintech_transaction_systems": [
        "financial transactions", "transaction integrity", "audit trail",
        "regulatory", "compliance", "entitlement", "entitlements",
        "ledger", "payments", "fraud", "fintech", "bank", "banking",
        "audit", "risk", "transactions",
    ],
    "C_data_streaming_systems": [
        "real-time ingestion", "data pipeline", "data pipelines", "data platform",
        "event streaming", "stream processing", "etl", "kafka", "flink",
        "ingestion", "streaming", "pipelines", "throughput", "latency",
        "analytics", "observability",
    ],
    "D_distributed_systems": [
        "low latency", "fault tolerance", "high-throughput", "high throughput",
        "backend infrastructure", "distributed systems", "distributed",
        "microservices", "concurrency", "resilience", "reliability",
        "scalability",
    ],
    "A_general_ai_platform": [
        "developer productivity", "internal platform", "platform engineering",
        "llm", "ai", "agents", "automation", "developer tools",
        "platform", "tooling",
    ],
    "E_staff_backend": [
        "staff engineer", "staff software", "technical lead", "tech lead",
        "technical leadership", "mentorship", "mentor engineers",
        "architecture review", "cross-functional", "cross functional",
        "engineering manager", "principal engineer",
    ],
    "E_core_backend": [
        "core services",
        "backend development",
        "service ownership",
        "api design",
        "product engineering",
        "feature delivery",
        "roadmap execution",
        "shipping features",
    ],
}

# Relative weight per signal source.
WEIGHT_TRAINING = 3.0
WEIGHT_ARCHETYPE_META = 2.0
WEIGHT_KEYWORD_HINT = 1.0

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-\.]*")


@dataclass
class _Signal:
    phrase: str
    weight: float


def _normalize(text: str) -> str:
    return text.lower()


def _phrase_in(haystack: str, phrase: str) -> bool:
    """Match a phrase with word-ish boundaries for single tokens, substring
    for multi-word phrases (they already carry context)."""
    phrase = phrase.lower().strip()
    if not phrase:
        return False
    if " " in phrase or "-" in phrase or "/" in phrase:
        return phrase in haystack
    pattern = rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _collect_signals() -> Dict[str, List[_Signal]]:
    """Merge hints, archetype metadata, and training keywords into one per-archetype
    list of (phrase, weight) signals. Deduplicates phrases, keeping the max weight."""
    signals: Dict[str, Dict[str, float]] = {aid: {} for aid in KEYWORD_HINTS}

    for archetype_id, phrases in KEYWORD_HINTS.items():
        for p in phrases:
            signals.setdefault(archetype_id, {})
            signals[archetype_id][p.lower()] = max(
                signals[archetype_id].get(p.lower(), 0.0), WEIGHT_KEYWORD_HINT
            )

    try:
        archetypes = load_archetypes()
    except Exception:
        archetypes = {}
    for archetype_id, meta in archetypes.items():
        bucket = signals.setdefault(archetype_id, {})
        for p in list(meta.get("best_for", [])) + list(meta.get("summary_focus", [])):
            bucket[p.lower()] = max(bucket.get(p.lower(), 0.0), WEIGHT_ARCHETYPE_META)

    try:
        examples = load_classification_examples()
    except Exception:
        examples = []
    for ex in examples:
        archetype_id = ex.get("chosen_archetype")
        if not archetype_id:
            continue
        bucket = signals.setdefault(archetype_id, {})
        for kw in ex.get("keywords", []):
            bucket[kw.lower()] = max(bucket.get(kw.lower(), 0.0), WEIGHT_TRAINING)

    return {
        aid: [_Signal(phrase=p, weight=w) for p, w in phrases.items()]
        for aid, phrases in signals.items()
    }


def _score_archetypes(text: str) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
    signals_by_archetype = _collect_signals()
    scores: Dict[str, float] = {}
    matched: Dict[str, List[str]] = {}

    for archetype_id, signals in signals_by_archetype.items():
        total = 0.0
        hits: List[Tuple[str, float]] = []
        for s in signals:
            if _phrase_in(text, s.phrase):
                total += s.weight
                hits.append((s.phrase, s.weight))
        scores[archetype_id] = total
        # Show the strongest matched phrases first, dedup preserving order.
        hits.sort(key=lambda t: (-t[1], t[0]))
        seen: set[str] = set()
        ordered: List[str] = []
        for phrase, _ in hits:
            if phrase not in seen:
                seen.add(phrase)
                ordered.append(phrase)
        matched[archetype_id] = ordered
    return scores, matched


def classify_job(description: str) -> ClassificationResult:
    text = _normalize(description or "")
    scores, matched = _score_archetypes(text)

    if not scores:
        return ClassificationResult(
            archetype_id="A_general_ai_platform",
            score=0.0,
            reasons=["No archetype signals configured; defaulted to general."],
        )

    best = max(scores, key=scores.get)
    best_score = scores[best]

    # Normalize against a reasonable ceiling so a handful of strong matches saturates.
    normalized = min(1.0, best_score / 10.0)

    if best_score == 0:
        return ClassificationResult(
            archetype_id="A_general_ai_platform",
            score=0.0,
            reasons=[
                "No keyword, archetype, or training signals matched.",
                "Defaulted to the general AI/platform archetype.",
            ],
        )

    reasons = matched[best][:6] or ["Matched via weighted signal aggregation."]
    # Add a short competitive-margin note when the next-best is close.
    sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(sorted_scores) > 1:
        runner_up_id, runner_up_score = sorted_scores[1]
        if runner_up_score > 0 and best_score - runner_up_score <= 1.5:
            reasons.append(
                f"Close call vs {runner_up_id} (score {runner_up_score:.1f} vs {best_score:.1f})."
            )

    return ClassificationResult(
        archetype_id=best,
        score=normalized,
        reasons=reasons,
    )


__all__ = ["classify_job", "KEYWORD_HINTS"]
