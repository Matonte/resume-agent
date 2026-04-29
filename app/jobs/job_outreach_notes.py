"""Optional per-job outreach notes (recruiter / hiring manager).

When enabled in ``preferences.yaml`` under ``outreach_for_job``, runs combination
web search for the company + role, enriches hits, and if any contact is inferred
as ``recruiter`` or ``hiring_manager``, writes ``outreach_contacts.json`` and
updates ``metadata.json``.

The daily runner calls :func:`maybe_write_job_outreach_notes` **only for jobs
that survive fit ranking** (the kept set), not for skipped listings. Manual
tailor invokes it for the single job when enabled.

Requires Google/Bing search keys in settings. Meeting advisor URL is optional
but adds the flask_sample tactical JSON when configured.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.jobs.preferences import Preferences
from app.scrapers.base import RawJob
from app.storage.db import JobRecord
from app.services.outreach_enrich import OutreachContactDossier, enrich_outreach_hits
from app.services.outreach_search import run_combination_search

logger = logging.getLogger(__name__)

_RECRUITER_ROLES = frozenset({"recruiter", "hiring_manager"})


def _build_outreach_description(raw: RawJob) -> str:
    parts = [
        (raw.company or "").strip(),
        (raw.title or "").strip(),
    ]
    jd = (raw.jd_full or "").strip()
    if jd:
        parts.append(jd[:2000])
    return "\n".join(p for p in parts if p)


def maybe_write_job_outreach_notes(
    raw: RawJob,
    job_dir: Path,
    prefs: Preferences,
    *,
    use_llm: bool = True,
) -> None:
    """Write outreach artifacts under ``job_dir`` when prefs + search allow."""
    cfg = prefs.outreach_for_job
    if not cfg.enabled:
        return
    if not settings.web_search_configured:
        logger.info(
            "outreach_for_job skipped (no web search API keys) for %s",
            (raw.company or raw.title or "")[:80],
        )
        return
    desc = _build_outreach_description(raw)
    if not desc.strip():
        return

    try:
        search = run_combination_search(desc)
    except Exception:
        logger.exception("outreach_for_job: combination search failed")
        return

    hits = search.hits[: max(1, cfg.max_search_hits)]
    if not hits:
        logger.debug(
            "outreach_for_job: no SERP hits for %s",
            (raw.company or "")[:60],
        )
        return

    try:
        dossiers = enrich_outreach_hits(hits, desc, use_llm=use_llm)
    except Exception:
        logger.exception("outreach_for_job: enrich failed")
        return

    matched: List[OutreachContactDossier] = [
        d
        for d in dossiers
        if (d.inferred_primary_role or "").strip().lower() in _RECRUITER_ROLES
    ]
    if not matched:
        logger.info(
            "outreach_for_job: no recruiter/HM among %d enriched hits for %s",
            len(dossiers),
            (raw.company or "")[:60],
        )
        return

    payload: List[Dict[str, Any]] = [d.model_dump(mode="json") for d in matched]
    out_json = job_dir / "outreach_contacts.json"
    out_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _patch_metadata_outreach(
        job_dir,
        {
            "outreach_written": True,
            "outreach_contacts_file": "outreach_contacts.json",
            "outreach_contact_count": len(matched),
            "outreach_roles": [d.inferred_primary_role for d in matched],
        },
    )
    logger.info(
        "outreach_for_job: wrote %d recruiter/HM contacts for %s → %s",
        len(matched),
        (raw.company or "")[:50],
        out_json.name,
    )


def outreach_badge_for_job(job: JobRecord) -> Optional[Dict[str, Any]]:
    """Summary for dashboards and digest email when ``outreach_contacts.json`` exists."""
    if not job.artifact_dir:
        return None
    base = Path(job.artifact_dir)
    oc = base / "outreach_contacts.json"
    if not oc.is_file():
        return None
    meta_path = base / "metadata.json"
    if meta_path.is_file():
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
            o = m.get("outreach") if isinstance(m, dict) else None
            if isinstance(o, dict) and o.get("outreach_written"):
                return {
                    "written": True,
                    "contact_count": int(o.get("outreach_contact_count") or 0),
                    "roles": list(o.get("outreach_roles") or []),
                }
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    try:
        rows = json.loads(oc.read_text(encoding="utf-8"))
        n = len(rows) if isinstance(rows, list) else 0
    except (json.JSONDecodeError, OSError):
        n = 0
    return {"written": True, "contact_count": n, "roles": []}


def _patch_metadata_outreach(job_dir: Path, outreach_meta: Dict[str, Any]) -> None:
    meta_path = job_dir / "metadata.json"
    if not meta_path.is_file():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(meta, dict):
        return
    meta["outreach"] = outreach_meta
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


__all__ = ["maybe_write_job_outreach_notes", "outreach_badge_for_job"]
