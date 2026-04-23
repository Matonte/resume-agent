"""Reusable tailoring pipeline.

Takes a `RawJob` (whether from a daily scraper or a manual paste) and
produces the full tailored package: resume.docx, cover_letter.docx,
screening.json, metadata.json on disk, plus a `JobRecord` ready to be
upserted into SQLite.

This module exists so the manual `/tailor` endpoint can share exactly the
same logic as the nightly daily run. The only difference between the two
call sites should be how the `RawJob` is obtained, not how it is tailored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.jobs.preferences import Preferences
from app.packaging.cover_letter import build_cover_letter, write_cover_letter_docx
from app.packaging.screening import answer_questions, extract_questions
from app.scrapers.base import RawJob
from app.services.classifier import classify_job
from app.services.fit_score import compute_fit_score
from app.services.resume_docx import generate_tailored_resume_bytes
from app.services.resume_tailor import generate_resume_draft
from app.storage.db import STATUS_NEW, JobRecord, artifact_dir_for


@dataclass
class TailoredJob:
    """Return value of `tailor_job_from_raw`. Holds the DB record plus
    the on-disk artifact directory so callers can hand back download
    URLs without re-computing paths."""

    record: JobRecord
    artifact_dir: str


def tailor_job_from_raw(
    raw: RawJob,
    prefs: Preferences,
    *,
    run_id: str,
    run_date: date,
    user_id: int = 1,
    use_llm: bool = True,
) -> TailoredJob:
    """Run the full tailor pipeline on a single `RawJob`.

    Writes `resume.docx`, `cover_letter.docx`, `screening.json`, and
    `metadata.json` under `outputs/<run_date>/job_<id>/`. Returns a
    `JobRecord` with status=NEW; the caller decides whether to upsert
    and whether to apply ranking/capping.
    """
    classification = classify_job(raw.jd_full)
    archetype_id = classification.archetype_id

    fit = compute_fit_score(raw.jd_full)

    draft = generate_resume_draft(
        job_description=raw.jd_full,
        archetype_id=archetype_id,
        use_llm=use_llm,
    )

    job_id = JobRecord.make_id(raw.source, raw.url, user_id=user_id)
    job_dir = artifact_dir_for(job_id, run_date, user_id=user_id)

    resume_bytes = generate_tailored_resume_bytes(
        archetype_id=archetype_id,
        job_description=raw.jd_full,
        use_llm=use_llm,
    )
    (job_dir / "resume.docx").write_bytes(resume_bytes)

    cover_text = build_cover_letter(
        candidate_name=prefs.candidate.name,
        company=raw.company,
        title=raw.title,
        archetype_id=archetype_id,
        job_description=raw.jd_full,
        use_llm=use_llm,
    )
    write_cover_letter_docx(cover_text, job_dir / "cover_letter.docx")

    questions = extract_questions(raw.jd_full)
    screening = answer_questions(questions, archetype_id=archetype_id, use_llm=use_llm)
    (job_dir / "screening.json").write_text(
        json.dumps(screening, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    metadata = {
        "job_id": job_id,
        "source": raw.source,
        "url": raw.url,
        "apply_url": raw.apply_url or raw.url,
        "title": raw.title,
        "company": raw.company,
        "location": raw.location,
        "salary_raw": raw.salary_raw,
        "archetype_id": archetype_id,
        "fit_score": fit.score,
        "fit_band": fit.band,
        "summary": draft.get("summary"),
        "selected_bullets": draft.get("selected_bullets"),
        "draft_notes": draft.get("notes"),
        "llm_applied": draft.get("llm_applied", False),
        "discovered_at": raw.posted_at.isoformat() if raw.posted_at else None,
        "cover_letter_preview": cover_text[:400],
    }
    (job_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    record = JobRecord(
        id=job_id,
        source=raw.source,
        url=raw.url,
        external_id=raw.external_id,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        salary_raw=raw.salary_raw,
        posted_at=raw.posted_at,
        jd_full=raw.jd_full,
        archetype_id=archetype_id,
        fit_score=fit.score,
        artifact_dir=str(job_dir),
        screening=screening,
        status=STATUS_NEW,
        daily_run_id=run_id,
        user_id=user_id,
    )
    return TailoredJob(record=record, artifact_dir=str(job_dir))


__all__ = ["TailoredJob", "tailor_job_from_raw"]
