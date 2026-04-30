"""Optional per-job outreach notes (recruiter / hiring manager, optional ICs).

When enabled in ``preferences.yaml`` under ``outreach_for_job``, runs combination
web search for the company + role. With ``posting_people``, named people in the
job text (and optionally the apply URL) get extra name+company searches. Hits are
merged (name-specific results first), enriched (meeting advisor + optional LLM),
and matching roles write ``outreach_contacts.json`` and update ``metadata.json``.

The daily runner calls :func:`maybe_write_job_outreach_notes` **only for jobs
that survive fit ranking** (the kept set), not for skipped listings. Manual
tailor invokes it for the single job when enabled.

Requires Google/Bing search keys for full SERP outreach. When search keys are
missing but ``MEETING_ADVISOR_URL`` is set and ``posting_people`` is true,
named people in the JD still get advisor-backed dossiers (no web search).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.jobs.preferences import OutreachForJobConfig, Preferences
from app.scrapers.base import RawJob
from app.storage.db import JobRecord
from app.services.outreach_enrich import (
    OutreachContactDossier,
    advise_posting_people_dossiers,
    enrich_outreach_hits,
)
from app.services.outreach_posting_people import (
    build_followup_queries,
    extract_people_from_posting_corpus,
    merge_posting_corpus,
)
from app.services.outreach_search import (
    WebSearchHit,
    load_outreach_search_config,
    merge_dedupe_hits,
    run_combination_search,
    run_supplementary_outreach_searches,
)

logger = logging.getLogger(__name__)


def _allowed_outreach_roles(cfg: OutreachForJobConfig) -> frozenset[str]:
    roles = {"recruiter", "hiring_manager"}
    if cfg.include_engineer_contacts:
        roles.add("engineer")
    return frozenset(roles)


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
    desc = _build_outreach_description(raw)
    if not desc.strip():
        return

    followup_queries: list[str] = []
    extracted: list = []
    if cfg.posting_people:
        corpus = merge_posting_corpus(raw, fetch_apply_page=cfg.fetch_apply_page)
        extracted = extract_people_from_posting_corpus(
            corpus,
            (raw.company or "").strip(),
            max_people=max(0, cfg.max_posting_people),
            use_llm=use_llm,
        )
        followup_queries = build_followup_queries(
            extracted,
            (raw.company or "").strip(),
            max_queries=max(0, cfg.max_followup_queries),
        )
        if extracted:
            logger.info(
                "outreach_for_job: extracted %d named people from posting text",
                len(extracted),
            )

    if not settings.web_search_configured:
        if (
            settings.meeting_advisor_configured
            and cfg.posting_people
            and extracted
        ):
            try:
                dossiers = advise_posting_people_dossiers(
                    extracted,
                    company=(raw.company or "").strip(),
                    title=(raw.title or "").strip(),
                    job_description_excerpt=(raw.jd_full or "").strip(),
                    listing_url=(raw.url or raw.apply_url or "").strip(),
                    use_llm=use_llm,
                )
            except Exception:
                logger.exception(
                    "outreach_for_job: posting-people advisor-only enrich failed"
                )
                return
            allowed = _allowed_outreach_roles(cfg)
            matched: List[OutreachContactDossier] = [
                d
                for d in dossiers
                if (d.inferred_primary_role or "").strip().lower() in allowed
            ]
            if not matched:
                logger.info(
                    "outreach_for_job: advisor-only path produced no allowed-role "
                    "contacts for %s",
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
                    "outreach_source": "posting_people_meeting_advisor",
                },
            )
            logger.info(
                "outreach_for_job: advisor-only (no SERP) wrote %d contacts for %s → %s",
                len(matched),
                (raw.company or "")[:50],
                out_json.name,
            )
        else:
            logger.info(
                "outreach_for_job skipped (no web search API keys) for %s",
                (raw.company or raw.title or "")[:80],
            )
        return

    try:
        search = run_combination_search(desc)
    except Exception:
        logger.exception("outreach_for_job: combination search failed")
        return

    sup_hits: List[WebSearchHit] = []
    if followup_queries:
        try:
            ocfg = load_outreach_search_config()
            sup = run_supplementary_outreach_searches(
                followup_queries,
                results_per_query=ocfg.results_per_query,
            )
            sup_hits = sup.hits
            for err in sup.errors:
                logger.debug("outreach_for_job: follow-up search: %s", err[:200])
        except Exception:
            logger.exception("outreach_for_job: supplementary search failed")

    combined = merge_dedupe_hits(sup_hits + search.hits)
    enrich_cap = cfg.max_search_hits
    if followup_queries:
        enrich_cap = min(32, cfg.max_search_hits + len(followup_queries))
    hits = combined[: max(1, enrich_cap)]
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

    allowed = _allowed_outreach_roles(cfg)
    matched: List[OutreachContactDossier] = [
        d
        for d in dossiers
        if (d.inferred_primary_role or "").strip().lower() in allowed
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
        "outreach_for_job: wrote %d contacts for %s → %s",
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
