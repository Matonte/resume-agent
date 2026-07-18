"""Evidence-addressable candidate profile helpers (schema v2).

Facts stay in ``master_truth_model.json``. Each achievement gets a stable id
and optional provenance so generators can cite evidence instead of inventing.

Backward compatible: roles that only have string ``core_facts`` are upgraded
in memory (and when onboarding writes) to ``achievements[]`` while keeping
``core_facts`` as a parallel list of plain strings for existing callers.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 2

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, *, fallback: str = "item") -> str:
    s = _SLUG_RE.sub("_", (text or "").strip().lower()).strip("_")
    return (s[:40] or fallback)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(p.strip().lower() for p in parts if p)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def achievement_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("text") or item.get("bullet") or "").strip()
    return ""


def normalize_achievement(
    item: Any,
    *,
    role_company: str = "",
    index: int = 0,
    default_source: Optional[str] = None,
    default_status: str = "verified",
) -> Dict[str, Any]:
    text = achievement_text(item)
    if isinstance(item, dict):
        ach_id = str(item.get("id") or "").strip()
        if not ach_id:
            ach_id = _stable_id("ach", role_company, text or str(index))
        status = str(item.get("status") or default_status).strip() or default_status
        source = item.get("evidence_source")
        if source is None and default_source:
            source = default_source
        confidence = item.get("confidence")
        out: Dict[str, Any] = {
            "id": ach_id,
            "text": text,
            "status": status,
            "evidence_source": source,
        }
        if confidence is not None:
            try:
                out["confidence"] = float(confidence)
            except (TypeError, ValueError):
                pass
        tech = item.get("technologies")
        if isinstance(tech, list) and tech:
            out["technologies"] = [str(t) for t in tech if str(t).strip()]
        return out

    return {
        "id": _stable_id("ach", role_company, text or str(index)),
        "text": text,
        "status": default_status,
        "evidence_source": default_source,
    }


def iter_achievements(role: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return normalized achievement dicts for a role (never mutates role)."""
    company = str(role.get("company") or "")
    raw = role.get("achievements")
    if isinstance(raw, list) and raw:
        return [
            normalize_achievement(item, role_company=company, index=i)
            for i, item in enumerate(raw)
            if achievement_text(item)
        ]
    facts = role.get("core_facts") or []
    return [
        normalize_achievement(item, role_company=company, index=i)
        for i, item in enumerate(facts)
        if achievement_text(item)
    ]


def core_fact_texts(role: Dict[str, Any]) -> List[str]:
    return [a["text"] for a in iter_achievements(role) if a.get("text")]


def normalize_role(
    role: Dict[str, Any],
    *,
    default_source: Optional[str] = None,
    role_index: int = 0,
) -> Dict[str, Any]:
    out = dict(role)
    company = str(out.get("company") or f"role_{role_index}")
    role_id = str(out.get("id") or "").strip()
    if not role_id:
        title = str(out.get("title") or "")
        start = str(out.get("start") or "")
        out["id"] = _stable_id("role", company, title, start) if company else f"role_{role_index}"

    achievements = [
        normalize_achievement(
            item,
            role_company=company,
            index=i,
            default_source=default_source,
        )
        for i, item in enumerate(
            out.get("achievements")
            if isinstance(out.get("achievements"), list) and out.get("achievements")
            else (out.get("core_facts") or [])
        )
        if achievement_text(item)
    ]
    out["achievements"] = achievements
    out["core_facts"] = [a["text"] for a in achievements]
    return out


def normalize_truth_model(
    truth: Dict[str, Any],
    *,
    default_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Upgrade a truth model dict to schema v2 (achievements + ids)."""
    if not isinstance(truth, dict):
        return {"candidate": {}, "roles": [], "schema_version": SCHEMA_VERSION}

    out = dict(truth)
    out["schema_version"] = SCHEMA_VERSION
    roles_in = out.get("roles") if isinstance(out.get("roles"), list) else []
    out["roles"] = [
        normalize_role(r if isinstance(r, dict) else {}, default_source=default_source, role_index=i)
        for i, r in enumerate(roles_in)
    ]
    layers = out.get("profile_layers")
    if not isinstance(layers, dict):
        layers = {}
    layers.setdefault("verified_facts", [])
    layers.setdefault("inferred_profile", [])
    layers.setdefault("user_preferences", {})
    out["profile_layers"] = layers
    return out


def find_achievement(
    truth: Dict[str, Any], achievement_id: str
) -> Optional[Dict[str, Any]]:
    aid = (achievement_id or "").strip()
    if not aid:
        return None
    for role in truth.get("roles") or []:
        if not isinstance(role, dict):
            continue
        for ach in iter_achievements(role):
            if ach.get("id") == aid:
                return {**ach, "role_company": role.get("company"), "role_id": role.get("id")}
    return None


def evidence_for_bullet(truth: Dict[str, Any], bullet: str) -> Optional[Dict[str, Any]]:
    text = (bullet or "").strip()
    if not text:
        return None
    for role in truth.get("roles") or []:
        if not isinstance(role, dict):
            continue
        for ach in iter_achievements(role):
            if ach.get("text") == text:
                return {
                    "evidence_id": ach["id"],
                    "text": ach["text"],
                    "status": ach.get("status") or "verified",
                    "evidence_source": ach.get("evidence_source"),
                    "role_company": role.get("company"),
                    "role_id": role.get("id"),
                }
    return None


__all__ = [
    "SCHEMA_VERSION",
    "achievement_text",
    "normalize_achievement",
    "iter_achievements",
    "core_fact_texts",
    "normalize_role",
    "normalize_truth_model",
    "find_achievement",
    "evidence_for_bullet",
]
