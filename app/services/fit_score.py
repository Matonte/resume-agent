"""Fit score (0-10): how well does this job match the candidate's background?

Deterministic. Combines three inputs that are all easy to defend in a review:

1. Classifier strength: did one archetype clearly win, or is the JD scattered?
2. Bullet coverage: how many truth-model core_facts have real token overlap
   with the JD?
3. Seniority alignment: does the JD ask for years of experience the candidate
   has? (Only a modest penalty if it demands much more.)

Returns a score, a short band label ("Excellent" / "Strong" / "OK" / "Weak"),
and a list of human-readable reasons so the UI can explain the number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from app.services.classifier import classify_job
from app.services.data_loader import load_truth_model
from app.services.resume_tailor import _tokenize


@dataclass
class FitScore:
    score: float        # 0-10, one decimal
    band: str
    reasons: List[str]


MAX_SCORE = 10.0

WEIGHT_CLASSIFIER = 5.0       # up to 5 points from the classifier's normalized score
WEIGHT_BULLET_COVERAGE = 4.0  # up to 4 points from how many bullets have real JD overlap
WEIGHT_SENIORITY = 1.0        # up to 1 point if seniority expectations fit

BULLET_COVERAGE_TARGET = 8    # hitting ~8 relevant bullets saturates the component


def _bullet_coverage(job_description: str) -> tuple[float, int]:
    """Return (normalized_coverage, count_of_matching_bullets)."""
    truth = load_truth_model()
    job_tokens = set(_tokenize(job_description))
    if not job_tokens:
        return 0.0, 0

    hits = 0
    for role in truth.get("roles", []):
        for fact in role.get("core_facts", []):
            fact_tokens = set(_tokenize(fact))
            if fact_tokens & job_tokens:
                hits += 1
    return min(1.0, hits / BULLET_COVERAGE_TARGET), hits


_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)


def _seniority_component(job_description: str) -> tuple[float, str]:
    truth = load_truth_model()
    candidate_years = int(truth.get("candidate", {}).get("years_experience") or 0)
    if not job_description:
        return 0.5, "No JD text to check seniority."
    matches = [int(m.group(1)) for m in _YEARS_RE.finditer(job_description)]
    if not matches:
        return 1.0, "No explicit years-of-experience requirement detected."
    required = max(matches)
    if required <= candidate_years:
        return 1.0, f"Meets the JD's {required}+ years requirement (candidate: {candidate_years})."
    gap = required - candidate_years
    if gap <= 2:
        return 0.6, f"Close: JD asks for {required}+ years, candidate has {candidate_years}."
    if gap <= 5:
        return 0.3, f"Stretch: JD asks for {required}+ years, candidate has {candidate_years}."
    return 0.1, f"Likely mismatch: JD asks for {required}+ years, candidate has {candidate_years}."


def _band(score: float) -> str:
    if score >= 8.5:
        return "Excellent"
    if score >= 6.5:
        return "Strong"
    if score >= 4.5:
        return "OK"
    if score >= 2.5:
        return "Weak"
    return "Poor"


def compute_fit_score(job_description: str) -> FitScore:
    classification = classify_job(job_description or "")
    classifier_component = (classification.score or 0.0) * WEIGHT_CLASSIFIER

    coverage_ratio, bullet_hits = _bullet_coverage(job_description or "")
    coverage_component = coverage_ratio * WEIGHT_BULLET_COVERAGE

    seniority_ratio, seniority_reason = _seniority_component(job_description or "")
    seniority_component = seniority_ratio * WEIGHT_SENIORITY

    total = min(
        MAX_SCORE,
        classifier_component + coverage_component + seniority_component,
    )
    total = round(total, 1)

    reasons: List[str] = []
    reasons.append(
        f"Archetype match `{classification.archetype_id}` "
        f"at {int(round(classification.score * 100))}% confidence "
        f"({len(classification.reasons)} signals)."
    )
    reasons.append(
        f"{bullet_hits} truth-model bullet(s) have direct JD token overlap."
    )
    reasons.append(seniority_reason)

    return FitScore(score=total, band=_band(total), reasons=reasons)


__all__ = ["FitScore", "compute_fit_score"]
