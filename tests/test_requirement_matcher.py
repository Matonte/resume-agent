"""Requirement → evidence matcher tests."""

from __future__ import annotations

from app.services.data_loader import load_truth_model
from app.services.requirement_matcher import (
    extract_requirements,
    match_requirements_to_evidence,
)
from app.services.resume_tailor import generate_resume_draft


def test_extract_bullet_requirements() -> None:
    jd = """
    We are hiring a Senior Backend Engineer.

    Requirements:
    - Experience building scalable Java microservices
    - Hands-on AWS Lambda and Step Functions
    - Strong Kafka or event-driven systems background
    """
    reqs = extract_requirements(jd)
    assert len(reqs) >= 3
    joined = " ".join(reqs).lower()
    assert "java" in joined or "microservices" in joined
    assert "aws" in joined or "lambda" in joined


def test_match_returns_evidence_ids_for_fintech_jd() -> None:
    truth = load_truth_model()
    jd = (
        "Experience building scalable Java microservices and event-driven "
        "entitlement systems on Solace. AWS Step Functions preferred."
    )
    matches = match_requirements_to_evidence(jd, truth)
    assert matches
    # At least one requirement should hit a known achievement id.
    flat = [m for block in matches for m in block["matches"]]
    assert flat, "expected at least one evidence match"
    assert all(m.get("experienceId") for m in flat)
    assert all(0.0 < float(m["score"]) <= 1.0 for m in flat)


def test_draft_includes_requirement_matches() -> None:
    draft = generate_resume_draft(
        "Senior backend engineer focused on event-driven entitlement systems and Java.",
        "B_fintech_transaction_systems",
    )
    assert "requirement_matches" in draft
    assert isinstance(draft["requirement_matches"], list)
    assert draft["evidence_ids"]
