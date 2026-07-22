"""Load and serialize candidate truth models for review UIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.services.evidence_schema import normalize_truth_model
from app.services.profile_conflicts import detect_profile_conflicts


def truth_path(candir: Path) -> Path:
    return candir / "master_truth_model.json"


def load_profile_truth(candir: Path) -> Dict[str, Any]:
    path = truth_path(candir)
    if not path.is_file():
        return normalize_truth_model({"candidate": {}, "roles": []})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalize_truth_model({"candidate": {}, "roles": []})
    if not isinstance(raw, dict):
        return normalize_truth_model({"candidate": {}, "roles": []})
    return normalize_truth_model(raw)


def has_reviewable_roles(truth: Dict[str, Any]) -> bool:
    roles = truth.get("roles") or []
    return isinstance(roles, list) and any(
        isinstance(r, dict)
        and (r.get("company") or r.get("core_facts") or r.get("achievements"))
        for r in roles
    )


def profile_review_payload(candir: Path) -> Dict[str, Any]:
    truth = load_profile_truth(candir)
    conflicts = detect_profile_conflicts(truth)
    candidate = truth.get("candidate") if isinstance(truth.get("candidate"), dict) else {}
    roles_out: List[Dict[str, Any]] = []
    for role in truth.get("roles") or []:
        if not isinstance(role, dict):
            continue
        achievements = role.get("achievements") or []
        roles_out.append(
            {
                "id": role.get("id"),
                "company": role.get("company"),
                "title": role.get("title"),
                "location": role.get("location"),
                "start": role.get("start"),
                "end": role.get("end"),
                "is_current": role.get("is_current"),
                "tech": role.get("tech") or [],
                "themes": role.get("themes") or [],
                "achievements": achievements,
                "core_facts": role.get("core_facts") or [],
            }
        )
    inferred = []
    layers = truth.get("profile_layers") if isinstance(truth.get("profile_layers"), dict) else {}
    if isinstance(layers.get("inferred_profile"), list):
        inferred = layers["inferred_profile"]
    return {
        "candidate": {
            "preferred_name": candidate.get("preferred_name") or "",
            "headline": candidate.get("headline") or "",
            "years_experience": candidate.get("years_experience") or 0,
            "skills": candidate.get("skills") or {},
        },
        "roles": roles_out,
        "inferred_profile": inferred,
        "conflicts": conflicts,
        "has_roles": has_reviewable_roles(truth),
        "schema_version": truth.get("schema_version"),
    }


__all__ = [
    "has_reviewable_roles",
    "load_profile_truth",
    "profile_review_payload",
    "truth_path",
]
