"""Resume tailor tests: verify the summary reflects the archetype,
that bullets only come from the truth model, and that notes always include
the guardrail reminders.
"""

from app.services.data_loader import load_truth_model
from app.services.resume_tailor import generate_resume_draft


def _all_truth_bullets() -> set[str]:
    truth = load_truth_model()
    bullets: set[str] = set()
    for role in truth["roles"]:
        bullets.update(role.get("core_facts", []))
    return bullets


def test_draft_summary_contains_archetype_focus_for_streaming():
    draft = generate_resume_draft(
        "Own our data platform and Kafka streaming pipelines.",
        "C_data_streaming_systems",
    )
    summary = draft["summary"].lower()
    assert "real-time processing" in summary or "pipelines" in summary


def test_selected_bullets_are_from_truth_model():
    truth_bullets = _all_truth_bullets()
    draft = generate_resume_draft(
        "Senior backend engineer focused on event-driven entitlement systems.",
        "B_fintech_transaction_systems",
    )
    assert draft["selected_bullets"], "should return at least one bullet"
    for b in draft["selected_bullets"]:
        assert b in truth_bullets, f"bullet not in truth model: {b}"


def test_notes_include_guardrails():
    draft = generate_resume_draft(
        "Distributed systems role.", "D_distributed_systems"
    )
    joined = " ".join(draft["notes"]).lower()
    assert "truth model" in joined
    assert "claim" in joined or "invent" in joined or "verify" in joined


def test_fallback_when_no_overlap():
    draft = generate_resume_draft("xyzzy foo bar baz qux", "A_general_ai_platform")
    assert draft["summary"]
    assert draft["selected_bullets"], "fallback should still return bullets"


def test_fintech_summary_has_positioning_and_scale_language():
    """Archetype B should position the candidate clearly as a fintech backend
    specialist with scale language — not a generic 'improving backend and data
    platforms' blob."""
    draft = generate_resume_draft(
        "Senior Backend Engineer, Payments Platform. Event-driven transaction systems.",
        "B_fintech_transaction_systems",
    )
    summary = draft["summary"].lower()
    assert "11+ years" in summary
    # Must name the scale and the domain explicitly.
    assert "high-throughput" in summary or "distributed" in summary
    assert "financial" in summary
    # Must contain positioning verbs.
    assert "specializes in" in summary
    # No soft filler that the user flagged.
    assert "effective collaboration" not in summary
    assert "various" not in summary


def test_distributed_summary_has_distinct_positioning_from_fintech():
    """Archetypes B and D should NOT produce identical summaries — positioning
    must actually change based on archetype."""
    jd = "Senior backend engineer role."
    b = generate_resume_draft(jd, "B_fintech_transaction_systems")["summary"]
    d = generate_resume_draft(jd, "D_distributed_systems")["summary"]
    assert b != d
    assert "low-latency" in d.lower() or "fault tolerance" in d.lower() or "resilience" in d.lower()


def test_current_role_gets_at_least_four_bullets():
    """Citibank is the current role and should anchor the resume — the picker
    must surface at least 4 of its bullets for a relevant JD."""
    truth = load_truth_model()
    current = next(
        (r for r in truth["roles"] if r.get("is_current") or not r.get("end")),
        truth["roles"][0],
    )
    current_bullets = set(current.get("core_facts", []))
    draft = generate_resume_draft(
        "Senior Backend Engineer building event-driven distributed transaction systems "
        "with auditability and entitlements workflows.",
        "B_fintech_transaction_systems",
    )
    picked_from_current = [b for b in draft["selected_bullets"] if b in current_bullets]
    assert len(picked_from_current) >= 4, (
        f"current role should anchor the resume; picked only {len(picked_from_current)} "
        f"of {len(current_bullets)} available current-role bullets"
    )


def test_citihawks_project_is_visible_in_current_role_bullets():
    """The signature project should be nameable — it's a huge asset the user
    explicitly called out."""
    truth = load_truth_model()
    current = next(r for r in truth["roles"] if r.get("is_current"))
    joined = " ".join(current.get("core_facts", [])).lower()
    assert "citihawks" in joined, "signature project name should appear in current-role facts"
