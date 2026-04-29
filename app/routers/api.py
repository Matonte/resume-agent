import re
from datetime import datetime

from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

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
from app.services.outreach_enrich import (
    OutreachContactDossier,
    advise_for_job_context,
    enrich_outreach_hits,
)
from app.services.outreach_search import WebSearchHit
from app.services.resume_docx import generate_tailored_resume_bytes
from app.services.resume_tailor import generate_resume_draft

router = APIRouter()

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _fit_to_response(fit) -> FitScoreResponse:
    return FitScoreResponse(score=fit.score, band=fit.band, reasons=fit.reasons)


def _safe_slug(raw: str | None, fallback: str) -> str:
    if not raw:
        return fallback
    slug = _SAFE_FILENAME_RE.sub("_", raw.strip())
    return slug or fallback


@router.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        loaded_files={
            "truth_model_roles": len(load_truth_model()["roles"]),
            "archetypes": len(load_archetypes()),
            "stories": len(load_story_bank()),
            "answer_categories": len(load_answer_bank()),
            "classification_examples": len(load_classification_examples()),
            "rewrite_examples": len(load_rewrite_examples()),
            "llm_configured": llm_is_available(),
            "meeting_advisor_configured": settings.meeting_advisor_configured,
        },
    )


@router.get("/archetypes")
def archetypes():
    return load_archetypes()


@router.post("/classify", response_model=ClassificationResult)
def classify(job: JobInput):
    return classify_job(job.description)


@router.post("/draft-resume", response_model=ResumeDraftResponse)
def draft_resume(req: ResumeDraftRequest):
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
def full_draft(req: FullDraftRequest):
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


@router.post("/generate-resume")
def generate_resume(req: GenerateResumeRequest):
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
