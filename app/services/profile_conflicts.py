"""Detect conflicting employment facts across merged résumé sources."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.evidence_schema import iter_achievements


def _norm_company(name: str) -> str:
    return "".join(c for c in (name or "").lower() if c.isalnum())


def detect_profile_conflicts(truth: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return human-readable conflicts (dates / duplicate employers).

    Does not silently pick a winner — callers surface these for user review.
    """
    conflicts: List[Dict[str, Any]] = []
    roles = [r for r in (truth.get("roles") or []) if isinstance(r, dict)]
    by_company: Dict[str, List[Dict[str, Any]]] = {}
    for role in roles:
        key = _norm_company(str(role.get("company") or ""))
        if not key:
            continue
        by_company.setdefault(key, []).append(role)

    for _key, group in by_company.items():
        if len(group) < 2:
            continue
        ends = {(r.get("end"), r.get("is_current"), r.get("start")) for r in group}
        if len(ends) > 1:
            conflicts.append(
                {
                    "type": "employment_dates",
                    "company": group[0].get("company"),
                    "message": (
                        f"Multiple date ranges for {group[0].get('company')}: "
                        + "; ".join(
                            (
                                f"{r.get('title') or 'role'} "
                                f"{r.get('start') or '?'}–"
                                f"{'present' if r.get('is_current') or not r.get('end') else r.get('end')}"
                            )
                            for r in group
                        )
                    ),
                    "role_ids": [r.get("id") for r in group if r.get("id")],
                }
            )

    # Duplicate achievement texts under different ids (possible double-merge).
    seen_text: Dict[str, str] = {}
    for role in roles:
        for ach in iter_achievements(role):
            text = (ach.get("text") or "").strip().lower()
            if not text:
                continue
            prior = seen_text.get(text)
            if prior and prior != ach.get("id"):
                conflicts.append(
                    {
                        "type": "duplicate_achievement",
                        "message": f"Same achievement text appears more than once: {ach.get('text')[:120]}",
                        "achievement_ids": [prior, ach.get("id")],
                    }
                )
            else:
                seen_text[text] = str(ach.get("id") or "")

    return conflicts


__all__ = ["detect_profile_conflicts"]
