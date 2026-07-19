"""Candidate signal bundle for Meeting Advisor."""

from __future__ import annotations

from app.services.candidate_signal_bundle import (
    build_candidate_outreach_signals,
    merge_candidate_into_advisor_context,
)


def test_build_signals_include_evidence_ids() -> None:
    bundle = build_candidate_outreach_signals(
        job_description="Java microservices event-driven AWS Step Functions"
    )
    assert bundle["signals"]
    for sig in bundle["signals"]:
        assert sig["evidenceId"]
        assert sig["text"]


def test_merge_adds_candidate_profile_to_context() -> None:
    ctx = merge_candidate_into_advisor_context(
        {"setting": "outreach", "notes": "base"},
        job_description="Kafka streaming backend",
    )
    assert "candidate_profile" in ctx
    assert ctx["candidate_profile"]["signals"]
    assert "Candidate evidence signals" in (ctx.get("notes") or "")
