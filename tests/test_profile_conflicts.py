"""Profile conflict detection for onboarding review."""

from __future__ import annotations

from app.services.profile_conflicts import detect_profile_conflicts


def test_detects_conflicting_end_dates_same_company() -> None:
    truth = {
        "roles": [
            {
                "id": "r1",
                "company": "Citibank",
                "title": "Engineer",
                "start": "2025-03",
                "end": "2026-06",
                "core_facts": ["Built APIs"],
            },
            {
                "id": "r2",
                "company": "Citibank",
                "title": "AVP",
                "start": "2025-03",
                "end": "2026-07",
                "core_facts": ["Built workflows"],
            },
        ]
    }
    conflicts = detect_profile_conflicts(truth)
    assert any(c["type"] == "employment_dates" for c in conflicts)
    assert "Citibank" in (conflicts[0].get("message") or "")
