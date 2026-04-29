"""Enrich web-search contacts with recruiter / hiring-manager angles.

1. **flask_sample meeting_advisor** (recommended): set ``MEETING_ADVISOR_URL`` (e.g.
   ``http://127.0.0.1:5003`` when running ``python run_meeting_advisor.py`` from
   ``flask_sample``). Each contact triggers ``POST .../api/v1/advise`` with the
   search title/snippet as notes; the response merges WhoIsWhat (K) + WhoIsHoss
   (HOSS) plus ``advice`` JSON (opening_move, do/don't, watchpoints, …) into
   the dossier. The full HTTP JSON is stored under ``whoiswhat_raw["meeting_advisor"]``
   when other enrichers are absent, or merged into a dict beside
   ``enrich_contacts`` / ``plugin`` keys.

2. Optional **Python plug-in** on ``WHOISWHAT_AGENT_PATH``: module
   ``WHOISWHAT_ENRICH_MODULE`` + ``WHOISWHAT_ENRICH_CALLABLE`` (default
   ``enrich_contacts``). Same per-item list contract as documented below; row
   stored in ``whoiswhat_raw`` (or under ``enrich_contacts`` if meeting_advisor
   also runs).

3. **LLM** (``use_llm`` + OpenAI): refines talking points using the search hit
   plus any enrichment JSON. Does not invent employers beyond sources.

4. **Heuristic fallback** when other layers are off: role guess from title +
   light template copy.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.services.llm import complete_json, is_available
from app.services.outreach_search import WebSearchHit

logger = logging.getLogger(__name__)


class OutreachStakeholderNotes(BaseModel):
    summary: str = ""
    how_to_talk: List[str] = Field(default_factory=list)
    what_to_avoid: List[str] = Field(default_factory=list)


class OutreachContactDossier(BaseModel):
    title: str
    url: str
    snippet: str
    source_query: str = ""
    source_engine: str = ""
    inferred_primary_role: str = "unknown"
    recruiter: OutreachStakeholderNotes = Field(default_factory=OutreachStakeholderNotes)
    hiring_manager: OutreachStakeholderNotes = Field(default_factory=OutreachStakeholderNotes)
    combined_opening: str = ""
    whoiswhat_raw: Optional[Dict[str, Any]] = None
    llm_applied: bool = False


def _subject_name_from_hit(hit: WebSearchHit) -> str:
    """Best-effort name/label for WhoIsWhat / meeting_advisor subject_name."""
    t = (hit.title or "").strip()
    if not t:
        return "Unknown contact"
    for sep in (" — ", " – ", " | ", " - "):
        if sep in t:
            t = t.split(sep, 1)[0].strip()
            break
    return (t[:120] or "").strip() or "Unknown contact"


def _meeting_advisor_base_url() -> str:
    return (settings.meeting_advisor_url or "").strip().rstrip("/")


def _call_meeting_advisor(
    hit: WebSearchHit,
    company_description: str,
    inferred_role: str,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[Dict[str, Any]]:
    """POST to flask_sample meeting_advisor /api/v1/advise."""
    base = _meeting_advisor_base_url()
    if not base:
        return None
    subject = _subject_name_from_hit(hit)
    notes = (
        f"Company / intent: {company_description.strip()[:1500]}\n\n"
        f"Search title: {hit.title}\nURL: {hit.url}\nSnippet: {hit.snippet[:2000]}"
    )
    context = {
        "setting": "Cold async outreach (email or LinkedIn), no prior in-person relationship",
        "your_role": "Experienced software engineer exploring fit with this company",
        "stakes": "First impression; keep outreach concise and respectful",
        "goals": "Open a useful conversation about roles or team needs without pressure",
        "notes": f"Resume-agent inferred contact type: {inferred_role}. Prefer ethical, non-manipulative guidance.",
    }
    payload = {
        "subject_name": subject,
        "notes": notes,
        "source_hint": "",
        "context": context,
    }
    url = f"{base}/api/v1/advise"
    try:
        if client is not None:
            r = client.post(url, json=payload)
        else:
            with httpx.Client(timeout=120.0) as c:
                r = c.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(
                "meeting_advisor %s returned HTTP %s: %s",
                url,
                r.status_code,
                (r.text or "")[:500],
            )
            return None
        data = r.json()
        return data if isinstance(data, dict) else None
    except Exception:
        logger.exception("meeting_advisor request to %s failed", url)
        return None


def _attach_meeting_advisor_raw(
    base: OutreachContactDossier, advisor_full: Dict[str, Any]
) -> None:
    if base.whoiswhat_raw is None:
        base.whoiswhat_raw = {"meeting_advisor": advisor_full}
    elif isinstance(base.whoiswhat_raw, dict):
        base.whoiswhat_raw = {**base.whoiswhat_raw, "meeting_advisor": advisor_full}
    else:
        base.whoiswhat_raw = {
            "enrich_contacts": base.whoiswhat_raw,
            "meeting_advisor": advisor_full,
        }


def _merge_meeting_advisor_into_dossier(
    dossier: OutreachContactDossier, advisor_full: Dict[str, Any]
) -> None:
    advice = advisor_full.get("advice")
    if not isinstance(advice, dict):
        advice = {}
    opening = str(advice.get("opening_move") or "").strip()
    if opening:
        dossier.combined_opening = opening
    obs = str(advice.get("key_observations") or "").strip()
    do = advice.get("do") if isinstance(advice.get("do"), list) else []
    dont = advice.get("dont") if isinstance(advice.get("dont"), list) else []
    watch = advice.get("watchpoints") if isinstance(advice.get("watchpoints"), list) else []
    esc = str(advice.get("escalation_plan") or "").strip()
    how_lines = [str(x).strip() for x in do if str(x).strip()]
    how_lines.extend(
        f"Watch for: {str(x).strip()}" for x in watch if str(x).strip()
    )
    avoid_lines = [str(x).strip() for x in dont if str(x).strip()]
    summary = obs
    if esc:
        summary = f"{summary}\n\nIf it goes sideways: {esc}".strip() if summary else esc
    block = OutreachStakeholderNotes(
        summary=summary,
        how_to_talk=how_lines,
        what_to_avoid=avoid_lines,
    )
    if dossier.inferred_primary_role == "recruiter":
        dossier.recruiter = _merge_stakeholder(dossier.recruiter, block)
    else:
        dossier.hiring_manager = _merge_stakeholder(dossier.hiring_manager, block)
    _attach_meeting_advisor_raw(dossier, advisor_full)


def _hit_to_item(hit: WebSearchHit) -> Dict[str, str]:
    return {
        "title": hit.title or "",
        "url": hit.url or "",
        "snippet": hit.snippet or "",
        "query": hit.query or "",
        "engine": hit.engine or "",
    }


def _normalize_stakeholder_blob(raw: Any) -> OutreachStakeholderNotes:
    if raw is None:
        return OutreachStakeholderNotes()
    if isinstance(raw, str):
        return OutreachStakeholderNotes(summary=raw.strip())
    if not isinstance(raw, dict):
        return OutreachStakeholderNotes()
    how = raw.get("how_to_talk")
    if isinstance(how, str):
        how_l = [how] if how.strip() else []
    elif isinstance(how, list):
        how_l = [str(x).strip() for x in how if str(x).strip()]
    else:
        how_l = []
    av = raw.get("what_to_avoid")
    if isinstance(av, str):
        av_l = [av] if av.strip() else []
    elif isinstance(av, list):
        av_l = [str(x).strip() for x in av if str(x).strip()]
    else:
        av_l = []
    return OutreachStakeholderNotes(
        summary=str(raw.get("summary") or "").strip(),
        how_to_talk=how_l,
        what_to_avoid=av_l,
    )


def _merge_stakeholder(
    base: OutreachStakeholderNotes, extra: OutreachStakeholderNotes
) -> OutreachStakeholderNotes:
    out = base.model_copy()
    if extra.summary and (not out.summary or len(extra.summary) > len(out.summary)):
        out.summary = extra.summary
    seen = set(out.how_to_talk)
    for x in extra.how_to_talk:
        if x not in seen:
            out.how_to_talk.append(x)
            seen.add(x)
    seen_a = set(out.what_to_avoid)
    for x in extra.what_to_avoid:
        if x not in seen_a:
            out.what_to_avoid.append(x)
            seen_a.add(x)
    return out


def _infer_role_from_title(title: str, snippet: str) -> str:
    t = f"{title} {snippet}".lower()
    if re.search(r"\b(hr|talent|people ops|people operations|recruit|recruiting|recruiter|sourcer|staffing)\b", t):
        return "recruiter"
    if re.search(
        r"\b(vp |vice |director |head of engineering|head of|engineering manager|em\b|\bmanager\b)",
        t,
    ) and not re.search(r"\brecruit", t):
        return "hiring_manager"
    if re.search(
        r"\b(software|engineer|developer|sre|devops|scientist|programmer)\b",
        t,
    ):
        return "engineer"
    return "unknown"


def _try_import_whoiswhat_enrich() -> Optional[Any]:
    root = (settings.whoiswhat_agent_path or "").strip()
    mod_name = (settings.whoiswhat_enrich_module or "").strip()
    if not root or not mod_name:
        return None
    p = Path(root).resolve()
    if not p.is_dir():
        logger.warning("WHOISWHAT_AGENT_PATH is not a directory: %s", p)
        return None
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)
    try:
        module = importlib.import_module(mod_name)
    except Exception:
        logger.exception("failed to import WHOISWHAT_ENRICH_MODULE %s", mod_name)
        return None
    fn_name = (settings.whoiswhat_enrich_callable or "enrich_contacts").strip() or "enrich_contacts"
    fn = getattr(module, fn_name, None)
    if not callable(fn):
        logger.warning("whoiswhat module %s has no callable %s", mod_name, fn_name)
        return None
    return fn


def _call_whoiswhat(
    items: List[Dict[str, str]], company_description: str
) -> Optional[List[Dict[str, Any]]]:
    fn = _try_import_whoiswhat_enrich()
    if fn is None:
        return None
    try:
        sig = inspect.signature(fn)
        kwargs: Dict[str, Any] = {}
        if "company_description" in sig.parameters:
            kwargs["company_description"] = company_description
        elif "description" in sig.parameters:
            kwargs["description"] = company_description
        raw = fn(items, **kwargs) if kwargs else fn(items)
    except TypeError:
        try:
            raw = fn(items, company_description)
        except Exception:
            logger.exception("whoiswhat enrich_contacts call failed")
            return None
    except Exception:
        logger.exception("whoiswhat enrich_contacts call failed")
        return None
    if not isinstance(raw, list):
        logger.warning("whoiswhat enrich_contacts returned non-list")
        return None
    return [x if isinstance(x, dict) else {} for x in raw]


def _dossier_from_whoiswhat_row(row: Dict[str, Any]) -> OutreachContactDossier:
    """Internal: build partial dossier fields from one whoiswhat output row (no hit)."""
    rec = _normalize_stakeholder_blob(row.get("recruiter"))
    hm = _normalize_stakeholder_blob(row.get("hiring_manager"))
    role = str(row.get("inferred_primary_role") or row.get("primary_role") or "").strip()
    opening = str(row.get("combined_opening") or row.get("opening") or "").strip()
    return OutreachContactDossier(
        title="",
        url="",
        snippet="",
        inferred_primary_role=role or "unknown",
        recruiter=rec,
        hiring_manager=hm,
        combined_opening=opening,
        whoiswhat_raw=row,
    )


_LLM_SYSTEM = """You help a job seeker plan short, respectful outbound messages.
You only use facts present in the provided search snippet, title, URL, or optional enrichment JSON
(e.g. a plug-in row and/or meeting_advisor with profiles and tactical advice).
If something is unknown, say so briefly — do not invent employer history, schools, or awards."""


def _analyze_with_llm(
    hit: WebSearchHit,
    company_description: str,
    enrichment: Optional[Any],
) -> Optional[Dict[str, Any]]:
    if not is_available():
        return None
    extra_blob = ""
    if enrichment:
        try:
            import json

            extra_blob = json.dumps(enrichment, ensure_ascii=False, indent=2)[:6000]
        except Exception:
            extra_blob = str(enrichment)[:4000]
    user = (
        f"Company / search intent (from user):\n{company_description.strip()[:2000]}\n\n"
        f"Search result — title: {hit.title}\nURL: {hit.url}\nSnippet:\n{hit.snippet[:2000]}\n\n"
    )
    if extra_blob:
        user += f"Optional enrichment JSON from other agents (may be partial):\n{extra_blob}\n\n"
    user += (
        'Respond as JSON with this shape:\n{\n'
        '  "inferred_primary_role": "recruiter"|"hiring_manager"|"engineer"|"unknown",\n'
        '  "recruiter": {"summary": "", "how_to_talk": [], "what_to_avoid": []},\n'
        '  "hiring_manager": {"summary": "", "how_to_talk": [], "what_to_avoid": []},\n'
        '  "combined_opening": "one short sentence opening line for an email or DM"\n'
        "}\n"
        "Use recruiter fields when the person is likely TA/hiring; use hiring_manager when they likely own the team/role."
        ' If the URL/profile is unclear, use "unknown" and keep how_to_talk generic and low-risk.'
    )
    payload = complete_json(_LLM_SYSTEM, user, max_tokens=900, temperature=0.25)
    return payload if isinstance(payload, dict) else None


def _fallback_dossier(hit: WebSearchHit, role: str) -> OutreachContactDossier:
    rec = OutreachStakeholderNotes()
    hm = OutreachStakeholderNotes()
    if role == "recruiter":
        rec = OutreachStakeholderNotes(
            summary="Likely talent / recruiting; optimize for role fit and process.",
            how_to_talk=[
                "Lead with the role or team you want and location/remote preference.",
                "Ask one concise question about the interview process or hiring timeline.",
            ],
            what_to_avoid=["Long career autobiography in the first message."],
        )
    elif role == "hiring_manager":
        hm = OutreachStakeholderNotes(
            summary="Likely owns team or technical bar; respect their time.",
            how_to_talk=[
                "Reference a concrete problem space from their product or post if the snippet supports it.",
                "Offer a 2–3 line relevant win from your background, then ask one focused question.",
            ],
            what_to_avoid=["Assuming they are the decision-maker for hiring without evidence."],
        )
    elif role == "engineer":
        hm = OutreachStakeholderNotes(
            summary="Peer IC; tone can be more technical.",
            how_to_talk=[
                "Reference stack or domain from the snippet if present.",
                "Ask about team practices, architecture, or the problem they're solving.",
            ],
            what_to_avoid=["Cold-pitching referrals they cannot vouch for."],
        )
    else:
        rec = OutreachStakeholderNotes(
            summary="Role unclear from the snippet alone; keep the first touch short.",
            how_to_talk=[
                "State the kind of role or team you want in one line.",
                "Ask one specific question they can answer quickly.",
            ],
            what_to_avoid=["Long autobiographical intros without a clear ask."],
        )
    open_line = (
        f"Noticed your {'profile' if hit.url else 'page'} related to {hit.title[:60] or 'your work'}"
        + " — I'm exploring roles in the same space and would value a brief pointer."
    )
    return OutreachContactDossier(
        title=hit.title,
        url=hit.url,
        snippet=hit.snippet,
        source_query=hit.query,
        source_engine=hit.engine,
        inferred_primary_role=role if role != "unknown" else "unknown",
        recruiter=rec,
        hiring_manager=hm,
        combined_opening=open_line.strip(),
        whoiswhat_raw=None,
        llm_applied=False,
    )


def _merge_whoiswhat_into_dossier(
    base: OutreachContactDossier, ww_row: Dict[str, Any]
) -> None:
    partial = _dossier_from_whoiswhat_row(ww_row)
    base.recruiter = _merge_stakeholder(base.recruiter, partial.recruiter)
    base.hiring_manager = _merge_stakeholder(base.hiring_manager, partial.hiring_manager)
    if partial.combined_opening and not base.combined_opening:
        base.combined_opening = partial.combined_opening
    pr = partial.inferred_primary_role
    if pr and pr != "unknown":
        if base.inferred_primary_role == "unknown":
            base.inferred_primary_role = pr
    # Preserve full agent payload for debugging / UI
    base.whoiswhat_raw = ww_row


def enrich_outreach_hits(
    hits: Sequence[WebSearchHit],
    company_description: str,
    *,
    use_llm: bool = True,
) -> List[OutreachContactDossier]:
    """Return one dossier per hit, merging optional whoiswhat + LLM analysis."""
    items = [_hit_to_item(h) for h in hits]
    ww_rows = _call_whoiswhat(items, company_description) if items else None

    out: List[OutreachContactDossier] = []
    for i, hit in enumerate(hits):
        ww_row: Optional[Dict[str, Any]] = None
        if ww_rows and i < len(ww_rows):
            candidate = ww_rows[i]
            ww_row = candidate if isinstance(candidate, dict) and candidate else None

        role = _infer_role_from_title(hit.title, hit.snippet)
        if ww_row:
            r = str(ww_row.get("inferred_primary_role") or ww_row.get("primary_role") or "").strip().lower()
            if r in ("recruiter", "hiring_manager", "engineer", "unknown"):
                role = r

        dossier = _fallback_dossier(hit, role)

        if ww_row:
            _merge_whoiswhat_into_dossier(dossier, ww_row)

        advisor_resp = _call_meeting_advisor(hit, company_description, role)
        if advisor_resp:
            _merge_meeting_advisor_into_dossier(dossier, advisor_resp)

        if use_llm:
            llm_payload = _analyze_with_llm(
                hit,
                company_description,
                dossier.whoiswhat_raw,
            )
            if isinstance(llm_payload, dict):
                dossier.llm_applied = True
                ir = str(llm_payload.get("inferred_primary_role") or "").strip()
                if ir:
                    dossier.inferred_primary_role = ir
                dossier.recruiter = _merge_stakeholder(
                    dossier.recruiter, _normalize_stakeholder_blob(llm_payload.get("recruiter"))
                )
                dossier.hiring_manager = _merge_stakeholder(
                    dossier.hiring_manager,
                    _normalize_stakeholder_blob(llm_payload.get("hiring_manager")),
                )
                co = str(llm_payload.get("combined_opening") or "").strip()
                if co:
                    dossier.combined_opening = co

        out.append(dossier)
    return out


__all__ = [
    "OutreachStakeholderNotes",
    "OutreachContactDossier",
    "enrich_outreach_hits",
]
