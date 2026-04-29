from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class JobInput(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    description: str

class ClassificationResult(BaseModel):
    archetype_id: str
    score: float = Field(ge=0.0, le=1.0)
    reasons: List[str]

class ResumeDraftRequest(BaseModel):
    archetype_id: str
    job_description: str
    target_company: Optional[str] = None
    target_title: Optional[str] = None
    use_llm: bool = False

class ResumeDraftResponse(BaseModel):
    summary: str
    selected_bullets: List[str]
    notes: List[str]
    llm_applied: bool = False

class AnswerRequest(BaseModel):
    question: str
    job_description: str
    archetype_id: Optional[str] = None

class AnswerResponse(BaseModel):
    answer: str
    supporting_story_ids: List[str]

class FullDraftRequest(BaseModel):
    description: str
    question: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    archetype_override: Optional[str] = None
    use_llm: bool = False

class FitScoreResponse(BaseModel):
    score: float = Field(ge=0.0, le=10.0)
    band: str
    reasons: List[str]

class FullDraftResponse(BaseModel):
    classification: ClassificationResult
    resume: ResumeDraftResponse
    answer: Optional[AnswerResponse] = None
    fit: FitScoreResponse

class GenerateResumeRequest(BaseModel):
    description: str
    archetype_override: Optional[str] = None
    target_company: Optional[str] = None
    target_title: Optional[str] = None
    use_llm: bool = False

class HealthResponse(BaseModel):
    status: str
    loaded_files: Dict[str, Any]


class OutreachSearchHitInput(BaseModel):
    title: str
    url: str
    snippet: str = ""
    query: str = ""
    engine: str = ""


class OutreachEnrichRequest(BaseModel):
    company_description: str
    hits: List[OutreachSearchHitInput]
    use_llm: bool = True
