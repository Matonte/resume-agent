"""Slim candidate signals for Contact / Meeting Advisor payloads.

Contact Agent should not re-parse résumés; it consumes the same canonical
profile the Resume Agent uses, with evidence ids on each signal.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.data_loader import load_truth_model
from app.services.evidence_schema import iter_achievements
from app.services.requirement_matcher import (
    achievement_scores_from_matches,
    match_requirements_to_evidence,
)


def build_candidate_outreach_signals(
    *,
    job_description: str = "",
    max_signals: int = 5,
) -> Dict[str, Any]:
    """Return a compact, evidence-linked candidate bundle for advisor context."""
    truth = load_truth_model()
    candidate = truth.get("candidate") if isinstance(truth.get("candidate"), dict) else {}
    layers = truth.get("profile_layers") if isinstance(truth.get("profile_layers"), dict) else {}
    user_prefs = layers.get("user_preferences") if isinstance(layers.get("user_preferences"), dict) else {}

    catalog: List[Dict[str, Any]] = []
    for role in truth.get("roles") or []:
        if not isinstance(role, dict):
            continue
        company = str(role.get("company") or "")
        for ach in iter_achievements(role):
            eid = str(ach.get("id") or "").strip()
            text = str(ach.get("text") or "").strip()
            if not eid or not text:
                continue
            catalog.append(
                {
                    "evidenceId": eid,
                    "text": text,
                    "company": company,
                    "status": ach.get("status") or "verified",
                    "technologies": list(ach.get("technologies") or [])[:8],
                }
            )

    scores: Dict[str, float] = {}
    if (job_description or "").strip():
        matches = match_requirements_to_evidence(job_description, truth)
        scores = achievement_scores_from_matches(matches)

    catalog.sort(
        key=lambda s: (scores.get(str(s["evidenceId"]), 0.0),),
        reverse=True,
    )
    signals = catalog[: max(1, int(max_signals))]

    skills = candidate.get("skills") if isinstance(candidate.get("skills"), dict) else {}
    flat_skills: List[str] = []
    for _bucket, vals in skills.items():
        if isinstance(vals, list):
            flat_skills.extend(str(v) for v in vals if str(v).strip())

    return {
        "candidateProfileId": "active",
        "headline": str(candidate.get("headline") or ""),
        "yearsExperience": candidate.get("years_experience") or 0,
        "preferredName": str(candidate.get("preferred_name") or ""),
        "topSkills": flat_skills[:16],
        "userPreferences": {
            "locations": list(user_prefs.get("locations") or []),
            "remote_ok": user_prefs.get("remote_ok"),
            "titles": list(user_prefs.get("titles") or []),
        },
        "signals": signals,
    }


def merge_candidate_into_advisor_context(
    context: Optional[Dict[str, Any]],
    *,
    job_description: str = "",
) -> Dict[str, Any]:
    """Attach ``candidate_profile`` onto an advisor context dict."""
    ctx = dict(context or {})
    bundle = build_candidate_outreach_signals(job_description=job_description)
    ctx["candidate_profile"] = bundle
    # Keep a short human-readable note for advisors that only read notes/goals.
    signal_bits = []
    if bundle.get("yearsExperience"):
        signal_bits.append(f"{bundle['yearsExperience']}+ years experience")
    for sig in bundle.get("signals") or []:
        company = sig.get("company") or ""
        text = (sig.get("text") or "")[:120]
        if text:
            signal_bits.append(f"{text}{' (' + company + ')' if company else ''}")
    if signal_bits:
        existing = str(ctx.get("notes") or "").strip()
        addon = "Candidate evidence signals: " + "; ".join(signal_bits[:4])
        ctx["notes"] = f"{existing}\n{addon}".strip() if existing else addon
    return ctx


__all__ = [
    "build_candidate_outreach_signals",
    "merge_candidate_into_advisor_context",
]
