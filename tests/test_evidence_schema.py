"""Evidence schema v2: stable achievement ids + normalize legacy core_facts."""

from __future__ import annotations

from app.services.data_loader import load_truth_model
from app.services.evidence_schema import (
    SCHEMA_VERSION,
    evidence_for_bullet,
    iter_achievements,
    normalize_truth_model,
)
from app.services.resume_tailor import generate_resume_draft


def test_normalize_adds_achievement_ids_to_string_facts() -> None:
    truth = normalize_truth_model(
        {
            "candidate": {"preferred_name": "A"},
            "roles": [
                {
                    "company": "Acme",
                    "title": "Engineer",
                    "core_facts": ["Built APIs on AWS Lambda", "Led Kafka migration"],
                }
            ],
        },
        default_source="resume_1.txt",
    )
    assert truth["schema_version"] == SCHEMA_VERSION
    role = truth["roles"][0]
    assert role["id"]
    assert len(role["achievements"]) == 2
    assert all(a["id"] and a["text"] for a in role["achievements"])
    assert role["achievements"][0]["evidence_source"] == "resume_1.txt"
    assert role["core_facts"] == ["Built APIs on AWS Lambda", "Led Kafka migration"]
    assert "profile_layers" in truth


def test_bundled_truth_model_loads_with_evidence_ids() -> None:
    truth = load_truth_model()
    assert truth["schema_version"] == SCHEMA_VERSION
    assert truth["roles"], "expected bundled roles"
    for role in truth["roles"]:
        achs = iter_achievements(role)
        assert achs
        assert len(achs) == len(role.get("core_facts") or [])
        for a in achs:
            assert a["id"]
            assert a["text"]


def test_draft_includes_evidence_ids() -> None:
    draft = generate_resume_draft(
        "Senior backend engineer focused on event-driven entitlement systems.",
        "B_fintech_transaction_systems",
    )
    assert draft["selected_bullets"]
    assert draft["evidence_ids"], "expected evidence_ids for selected bullets"
    assert draft.get("evidence_gated") is True
    assert len(draft["evidence_ids"]) == len(draft["selected_bullets"])
    assert len(draft["selected_evidence"]) == len(draft["selected_bullets"])
    for ev in draft["selected_evidence"]:
        assert ev.get("evidence_id"), "every selected claim must have evidence_id"
        found = evidence_for_bullet(load_truth_model(), ev["text"])
        # Rewrites may change text; id must still be present either way.
        if found is not None:
            assert found["evidence_id"] == ev["evidence_id"]


def test_notes_mention_evidence_gate() -> None:
    draft = generate_resume_draft(
        "Distributed systems role.", "D_distributed_systems"
    )
    joined = " ".join(draft["notes"]).lower()
    assert "evidence-backed" in joined
    assert "accuracy guarantee" in joined
    assert draft.get("evidence_gated") is True
