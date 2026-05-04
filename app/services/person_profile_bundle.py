"""Orchestrate public-evidence → people-intel → Meeting Advisor (K + HOSS + advice).

All taxonomy outputs are **prep frameworks** grounded only on supplied/public text,
not clinical or hiring assessments — see ``DISCLAIMER``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from app.config import settings
from app.services.meeting_advisor_client import post_meeting_advise
from app.services.outreach_search import WebSearchHit, merge_dedupe_hits, run_person_name_search
from app.services.whoiswhat_people_intel import call_people_intel, snippets_from_web_hit

DISCLAIMER = (
    "WhoIsWhat (K taxonomy) and WhoIsHoss (HOSS) are stylized archetypal frameworks "
    "for conversation preparation — not psychological diagnoses or evaluations of real people. "
    "When grounded only on brief web snippets, treat labels as tentative prompts, not facts."
)


class ProfileSnippet(BaseModel):
    source_label: str = ""
    content: str = ""


class PersonProfileBundleParams(BaseModel):
    name: str
    company: str = ""
    title_hint: str = ""
    run_web_search: bool = True
    web_search_max_per_query: int = Field(default=8, ge=1, le=10)
    web_search_max_hits_for_intel: int = Field(default=12, ge=1, le=25)
    include_people_intel: bool = True
    include_meeting_profiles: bool = True
    meeting_setting: str = "interview"
    meeting_stakes: str = "medium"
    your_role: str = "Professional exploring fit — respectful first conversation."
    meeting_goals: str = (
        "Understand how to communicate effectively and surface relevant experience without pressure."
    )
    extra_snippets: List[ProfileSnippet] = Field(default_factory=list)
    evidence_char_cap: int = Field(default=8000, ge=2000, le=20000)


def _hits_to_evidence_text(hits: Sequence[WebSearchHit], cap: int) -> str:
    parts: List[str] = []
    for h in hits[:30]:
        line = (
            f"[{h.engine} — {h.title}]\nURL: {h.url}\nSnippet: {h.snippet}"
        ).strip()
        if line:
            parts.append(line)
    blob = "\n\n---\n\n".join(parts)
    return blob[:cap] if len(blob) > cap else blob


def _merge_snippets_into_evidence(
    base: str, extra: Sequence[ProfileSnippet], cap: int
) -> str:
    parts: List[str] = []
    if base.strip():
        parts.append(base.strip())
    for s in extra:
        c = (s.content or "").strip()
        if not c:
            continue
        label = (s.source_label or "user supplied").strip()
        parts.append(f"[{label}]\n{c}")
    blob = "\n\n---\n\n".join(parts)
    return blob[:cap] if len(blob) > cap else blob


def build_practical_readout(
    *,
    people_intel: Optional[Dict[str, Any]],
    meeting_payload: Optional[Dict[str, Any]],
    hit_count: int,
) -> Dict[str, Any]:
    """Human-oriented rollup — complements raw classifier JSON."""

    strength = (
        "strong"
        if hit_count >= 6
        else ("moderate" if hit_count >= 2 else ("thin" if hit_count else "none"))
    )
    out: Dict[str, Any] = {
        "evidence_strength": strength,
        "likely_professional_role": None,
        "role_confidence": None,
        "professional_interests": [],
        "communication_signals": [],
        "stakeholder_skew": None,
        "safe_angle": None,
        "prep_dimensions": {},
        "highlights_for_prep": [],
    }

    if people_intel:
        out["likely_professional_role"] = people_intel.get("likely_role")
        out["role_confidence"] = people_intel.get("confidence")
        out["professional_interests"] = people_intel.get("professional_interests") or []
        out["communication_signals"] = (
            people_intel.get("communication_style_signals") or []
        )
        out["safe_angle"] = people_intel.get("safe_outreach_angle")
        lim = people_intel.get("limitations")
        if lim:
            out["limitations_note"] = lim
        sl = people_intel.get("stakeholder_likelihood")
        if isinstance(sl, dict) and sl:
            try:
                top = max(sl.items(), key=lambda kv: float(kv[1] or 0))
                out["stakeholder_skew"] = {"role": top[0], "score": float(top[1])}
            except (TypeError, ValueError):
                pass

    if meeting_payload:
        k = meeting_payload.get("k_profile") or {}
        h = meeting_payload.get("hoss_profile") or {}
        adv = meeting_payload.get("advice") or {}
        out["prep_dimensions"] = {
            "k_code": k.get("classification_code"),
            "k_label": k.get("classification_label"),
            "hoss_display": h.get("display_label"),
            "hoss_level": h.get("hoss_level"),
            "meeting_risk_level": adv.get("risk_level"),
        }
        opening = adv.get("opening_move")
        if opening:
            out["highlights_for_prep"].append(f"Suggested opening line: {opening}")
        obs = adv.get("key_observations")
        if obs:
            out["highlights_for_prep"].append(f"Observations (tentative): {obs}")
        for d in adv.get("do") or []:
            if str(d).strip():
                out["highlights_for_prep"].append(f"Do: {d}")
        if meeting_payload.get("k_error"):
            out["highlights_for_prep"].append(
                f"WhoIsWhat call issue: {meeting_payload['k_error']}"
            )
        if meeting_payload.get("hoss_error"):
            out["highlights_for_prep"].append(
                f"WhoIsHoss call issue: {meeting_payload['hoss_error']}"
            )

    if out["safe_angle"] and f"angle: {out['safe_angle']}" not in " ".join(
        out["highlights_for_prep"]
    ):
        out["highlights_for_prep"].insert(
            0, f"Professional-context angle: {out['safe_angle']}"
        )

    return out


def build_person_profile_bundle(params: PersonProfileBundleParams) -> Dict[str, Any]:
    warnings: List[str] = []
    raw_name = " ".join((params.name or "").split()).strip()
    if len(raw_name) < 2:
        return {
            "error": "name must be at least 2 characters",
            "disclaimer": DISCLAIMER,
        }

    hits: List[WebSearchHit] = []
    queries: List[str] = []
    search_errors: List[str] = []

    if params.run_web_search:
        if not settings.web_search_configured:
            warnings.append(
                "Web search skipped: configure GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX "
                "and/or BING_SEARCH_KEY."
            )
        else:
            res = run_person_name_search(
                raw_name,
                company=(params.company or "").strip() or None,
                title_hint=(params.title_hint or "").strip() or None,
                results_per_query=params.web_search_max_per_query,
            )
            queries = res.queries
            hits = list(res.hits)
            search_errors = list(res.errors)

    evidence = _hits_to_evidence_text(hits, params.evidence_char_cap)
    evidence = _merge_snippets_into_evidence(
        evidence, params.extra_snippets, params.evidence_char_cap
    )

    people_intel: Optional[Dict[str, Any]] = None
    people_intel_note: Optional[str] = None

    if params.include_people_intel:
        if not settings.whoiswhat_people_intel_configured:
            people_intel_note = "WHOISWHAT_SERVICE_URL not set; skipped people-intel."
        else:
            snippets: List[Dict[str, str]] = []
            cap = params.web_search_max_hits_for_intel
            for h in hits[:cap]:
                snippets.extend(snippets_from_web_hit(h))
            for s in params.extra_snippets:
                c = (s.content or "").strip()
                if c:
                    snippets.append(
                        {
                            "source_label": (s.source_label or "user supplied").strip()
                            or "user supplied",
                            "content": c,
                        }
                    )
            if snippets:
                people_intel = call_people_intel(
                    person=raw_name,
                    company=(params.company or "").strip() or None,
                    snippets=snippets,
                    notes=(
                        "Evidence is from open-web search snippets and/or user-supplied text only. "
                        "Public professional context synthesis; no private-life or protected-trait inference."
                    ),
                )
                if people_intel is None:
                    people_intel_note = (
                        "people-intel returned no data (check WhoIsWhat service and OPENAI_API_KEY there)."
                    )
            else:
                people_intel_note = "No non-empty snippets for people-intel."

    meeting_payload: Optional[Dict[str, Any]] = None
    meeting_note: Optional[str] = None

    if params.include_meeting_profiles:
        ctx = {
            "setting": (params.meeting_setting or "interview").strip(),
            "stakes": (params.meeting_stakes or "medium").strip(),
            "your_role": (params.your_role or "").strip() or None,
            "goals": (params.meeting_goals or "").strip() or None,
            "notes": (
                "Archetypal prep only. Grounding text is public/web-sourced where available."
            ),
        }
        notes_for_advisor = evidence.strip() if evidence.strip() else None
        meeting_payload, meeting_note = post_meeting_advise(
            subject_name=raw_name,
            notes=notes_for_advisor[:6000] if notes_for_advisor else None,
            source_hint="resume_agent_public_bundle",
            context=ctx,
        )

    practical = build_practical_readout(
        people_intel=people_intel,
        meeting_payload=meeting_payload,
        hit_count=len(hits),
    )

    hit_models = merge_dedupe_hits(hits)

    return {
        "disclaimer": DISCLAIMER,
        "subject_name": raw_name,
        "web_search": {
            "configured": settings.web_search_configured,
            "queries": queries,
            "hits": [
                {
                    "title": h.title,
                    "url": h.url,
                    "snippet": h.snippet,
                    "engine": h.engine,
                    "query": h.query,
                }
                for h in hit_models[:30]
            ],
            "errors": search_errors,
        },
        "people_intel": people_intel,
        "people_intel_note": people_intel_note,
        "meeting_advisor": meeting_payload,
        "meeting_advisor_note": meeting_note,
        "practical_readout": practical,
        "warnings": warnings,
    }


__all__ = [
    "DISCLAIMER",
    "PersonProfileBundleParams",
    "ProfileSnippet",
    "build_person_profile_bundle",
    "build_practical_readout",
]
