import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import Response

from app.auth.onboarding_guard import raise_if_onboarding_incomplete

from app.models.schemas import (
    AnswerRequest,
    AnswerResponse,
    ClassificationResult,
    FitScoreResponse,
    FullDraftRequest,
    FullDraftResponse,
    GenerateResumeRequest,
    HealthResponse,
    JobInput,
    OutreachEnrichRequest,
    ResumeDraftRequest,
    ResumeDraftResponse,
)
from app.services.application_answers import answer_application_question
from app.services.classifier import classify_job
from app.services.data_loader import (
    load_answer_bank,
    load_archetypes,
    load_classification_examples,
    load_rewrite_examples,
    load_story_bank,
    load_truth_model,
)
from app.services.fit_score import compute_fit_score
from app.services.llm import is_available as llm_is_available
from app.config import settings
from app.scrapers.base import RawJob
from app.services.outreach_posting_people import (
    extract_people_from_posting_corpus,
    merge_posting_corpus,
)
from app.services.outreach_enrich import (
    OutreachContactDossier,
    advise_for_job_context,
    advise_posting_people_dossiers,
    enrich_outreach_hits,
)
from app.services.outreach_search import WebSearchHit
from app.services.resume_docx import generate_tailored_resume_bytes
from app.services.resume_tailor import generate_resume_draft

router = APIRouter()

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class MeetingAdvisorBrowserRequest(BaseModel):
    """Standalone meeting-advisor prep (no resume tailoring)."""

    description: str
    company: str = ""
    title: str = ""
    listing_url: str = ""
    subject_name: str = ""
    #: When true, extract named people from the JD (needs LLM) and advise per person.
    #: If none are found, falls back to one generic ``advice`` block.
    extract_people: bool = True
    use_llm: bool = True


class MeetingAdvisorBrowserResponse(BaseModel):
    configured: bool
    meeting_advisor_note: Optional[str] = None
    advice: Optional[Dict[str, Any]] = None
    people: Optional[List[Dict[str, Any]]] = None


def _fit_to_response(fit) -> FitScoreResponse:
    return FitScoreResponse(score=fit.score, band=fit.band, reasons=fit.reasons)


def _safe_slug(raw: str | None, fallback: str) -> str:
    if not raw:
        return fallback
    slug = _SAFE_FILENAME_RE.sub("_", raw.strip())
    return slug or fallback


@router.get("/health", response_model=HealthResponse)
def health():
    mf = {
            "truth_model_roles": len(load_truth_model()["roles"]),
            "archetypes": len(load_archetypes()),
            "stories": len(load_story_bank()),
            "answer_categories": len(load_answer_bank()),
            "classification_examples": len(load_classification_examples()),
            "rewrite_examples": len(load_rewrite_examples()),
            "llm_configured": llm_is_available(),
            "meeting_advisor_configured": settings.meeting_advisor_configured,
            "meeting_advisor_post_url": settings.meeting_advisor_advise_url or None,
            "meeting_advisor_browser_url": settings.meeting_advisor_browser_redirect_url
            or None,
            "meeting_advisor_pages": [
                "/api/meeting-advisor/page",
                "/meeting-advisor",
                "/advisor",
            ],
        }
    return HealthResponse(
        status="ok",
        loaded_files=mf,
    )


@router.get("/archetypes")
def archetypes():
    return load_archetypes()


@router.post("/classify", response_model=ClassificationResult)
def classify(job: JobInput):
    return classify_job(job.description)


@router.post("/draft-resume", response_model=ResumeDraftResponse)
def draft_resume(request: Request, req: ResumeDraftRequest):
    raise_if_onboarding_incomplete(request)
    drafted = generate_resume_draft(
        req.job_description, req.archetype_id, use_llm=req.use_llm
    )
    return ResumeDraftResponse(**drafted)


@router.post("/answer", response_model=AnswerResponse)
def answer(req: AnswerRequest):
    result = answer_application_question(req.question, req.archetype_id)
    return AnswerResponse(**result)


@router.post("/fit-score", response_model=FitScoreResponse)
def fit_score_endpoint(job: JobInput):
    return _fit_to_response(compute_fit_score(job.description))


@router.post("/outreach/enrich", response_model=List[OutreachContactDossier])
def outreach_enrich(req: OutreachEnrichRequest):
    if not (req.company_description or "").strip():
        raise HTTPException(status_code=400, detail="company_description is required")
    if not req.hits:
        raise HTTPException(status_code=400, detail="at least one hit is required")
    hits = [
        WebSearchHit(
            title=h.title,
            url=h.url,
            snippet=h.snippet or "",
            engine=h.engine or "",
            query=h.query or "",
        )
        for h in req.hits
    ]
    return enrich_outreach_hits(
        hits,
        req.company_description.strip(),
        use_llm=req.use_llm,
    )


@router.post("/full-draft", response_model=FullDraftResponse)
def full_draft(request: Request, req: FullDraftRequest):
    raise_if_onboarding_incomplete(request)
    classification = classify_job(req.description)
    archetype_id = req.archetype_override or classification.archetype_id

    drafted = generate_resume_draft(req.description, archetype_id, use_llm=req.use_llm)
    resume = ResumeDraftResponse(**drafted)

    answer_payload = None
    if req.question and req.question.strip():
        a = answer_application_question(req.question, archetype_id)
        answer_payload = AnswerResponse(**a)

    fit = _fit_to_response(compute_fit_score(req.description))

    meeting_advice = None
    meeting_note: str | None = None
    if req.meeting_advisor:
        if not settings.meeting_advisor_configured:
            meeting_note = "MEETING_ADVISOR_URL is not set."
        else:
            meeting_advice = advise_for_job_context(
                subject_name=(req.advisor_subject_name or "").strip(),
                company=(req.company or "").strip(),
                title=(req.title or "").strip(),
                job_description_excerpt=req.description,
            )
            if meeting_advice is None:
                meeting_note = "Meeting advisor returned no response (check server logs)."

    return FullDraftResponse(
        classification=classification,
        resume=resume,
        answer=answer_payload,
        fit=fit,
        meeting_advice=meeting_advice,
        meeting_advisor_note=meeting_note,
    )


@router.get("/meeting-advisor")
def meeting_advisor_api_help():
    """Browser GET /api/meeting-advisor shows how to call the JSON endpoint (avoids confusing 405)."""
    ext = settings.meeting_advisor_browser_redirect_url
    return {
        "method": "POST",
        "ui": ext or "/meeting-advisor",
        "ui_note": (
            "MEETING_ADVISOR_UI_URL is set — GET /meeting-advisor sends the browser "
            "to that URL."
            if ext
            else "Embedded advisor at /meeting-advisor. Set MEETING_ADVISOR_UI_URL only "
            "to forward the browser to another host."
        ),
        "ui_root_path": "/meeting-advisor",
        "aliases": ["/advisor", "/meeting-advisor/"],
        "meeting_advisor_configured": settings.meeting_advisor_configured,
        "resume_agent_posts_to": settings.meeting_advisor_advise_url or None,
        "hint": (
            "MEETING_ADVISOR_URL is the base of the advisor app (not resume-agent "
            "unless that stack implements the advise route). Example: http://127.0.0.1:5003"
        ),
        "flask_sample_siblings": {
            "meeting_advisor": "http://127.0.0.1:5003 (run_meeting_advisor.py)",
            "whoiswhat": "http://127.0.0.1:5000 (run.py — required for K profile)",
            "whoishoss": "http://127.0.0.1:5002 (run_whoishoss.py — required for HOSS)",
        },
        "diagnostic": "From repo root: python scripts/check_meeting_advisor_stack.py",
    }


@router.post("/meeting-advisor", response_model=MeetingAdvisorBrowserResponse)
def meeting_advisor_standalone(body: MeetingAdvisorBrowserRequest):
    """Conversation prep only: POST JD + optional person, or extract names from JD."""
    if not settings.meeting_advisor_configured:
        return MeetingAdvisorBrowserResponse(
            configured=False,
            meeting_advisor_note="MEETING_ADVISOR_URL is not set.",
        )
    text = (body.description or "").strip()
    if len(text) < 50:
        raise HTTPException(
            status_code=400,
            detail="description must be at least 50 characters",
        )
    co = (body.company or "").strip()
    ti = (body.title or "").strip()
    listing = (body.listing_url or "").strip()

    tried_extract = False
    if body.extract_people:
        raw = RawJob(
            source="meeting_advisor",
            url=listing or "https://example.invalid/job",
            title=ti or "Role",
            company=co or "Company",
            jd_full=text,
        )
        corpus = merge_posting_corpus(raw, fetch_apply_page=False)
        tried_extract = True
        extracted = extract_people_from_posting_corpus(
            corpus,
            co,
            max_people=8,
            use_llm=body.use_llm,
        )
        if extracted:
            dossiers = advise_posting_people_dossiers(
                extracted,
                company=co,
                title=ti,
                job_description_excerpt=text,
                listing_url=listing,
                use_llm=body.use_llm,
            )
            return MeetingAdvisorBrowserResponse(
                configured=True,
                people=[d.model_dump(mode="json") for d in dossiers],
            )

    advice = advise_for_job_context(
        subject_name=(body.subject_name or "").strip(),
        company=co,
        title=ti,
        job_description_excerpt=text,
        listing_url=listing,
    )
    note: Optional[str] = None
    if advice is None:
        note = (
            "Meeting advisor returned no response. If the log shows HTTP 404, "
            "MEETING_ADVISOR_URL must be the base URL of the advisor service "
            "(the process that implements POST …/api/v1/advise), e.g. "
            "http://127.0.0.1:5003 — not resume-agent alone unless you run the "
            "advisor there. Optionally set MEETING_ADVISOR_ADVISE_PATH."
        )
    elif tried_extract:
        note = (
            "No names extracted from this posting — showing general hiring-team prep. "
            "(Try a longer JD, enable “Use LLM” with OPENAI_API_KEY, or set a focus person.)"
        )
    return MeetingAdvisorBrowserResponse(
        configured=True, meeting_advisor_note=note, advice=advice
    )


@router.post("/generate-resume")
def generate_resume(request: Request, req: GenerateResumeRequest):
    raise_if_onboarding_incomplete(request)
    description = (req.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    archetype_id = req.archetype_override or classify_job(description).archetype_id

    try:
        blob = generate_tailored_resume_bytes(
            archetype_id, description, use_llm=req.use_llm
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    date_tag = datetime.now().strftime("%Y%m%d")
    company_slug = _safe_slug(req.target_company, "Target")
    archetype_letter = archetype_id.split("_", 1)[0]
    filename = f"MatonteResume_{archetype_letter}_{company_slug}_{date_tag}.docx"

    return Response(
        content=blob,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Archetype": archetype_id,
        },
    )
