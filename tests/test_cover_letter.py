"""Cover letter guardrail tests.

We exercise the deterministic fallback (always safe) and the LLM-polished
path with a mocked `complete_json`. The guardrail must reject any rewrite
that invents numbers or material tokens not present in the source letter,
the job description, or the truth model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.packaging.cover_letter import build_cover_letter, write_cover_letter_docx


def test_deterministic_cover_letter_mentions_company_and_title() -> None:
    out = build_cover_letter(
        candidate_name="Michael Matonte",
        company="Ledgerline Payments",
        title="Senior Backend Engineer",
        archetype_id="B_fintech_transaction_systems",
        job_description="We need a senior backend engineer for our payments platform.",
        use_llm=False,
    )
    assert "Ledgerline Payments" in out
    assert "Senior Backend Engineer" in out
    assert "Michael Matonte" in out


def test_write_cover_letter_docx(tmp_path: Path) -> None:
    text = "Dear team,\n\nHello!\n\nSincerely,\nMe"
    out = tmp_path / "cover.docx"
    path = write_cover_letter_docx(text, out)
    assert path.exists() and path.stat().st_size > 0


def test_llm_rewrite_rejects_invented_metrics(monkeypatch) -> None:
    """Force the LLM to invent a new percentage; the guardrail must reject
    the rewrite so we fall back to the deterministic version."""
    from app.packaging import cover_letter as cl_module
    from app.packaging import llm_cover_letter

    monkeypatch.setattr(llm_cover_letter, "is_available", lambda: True)
    monkeypatch.setattr(cl_module, "build_cover_letter", build_cover_letter)

    def _fake_complete_json(system, user, **kwargs):
        return {
            "cover_letter": (
                "Dear Acme hiring team,\n\n"
                "I cut latency by 73% at Megacorp Fintech using the XyzQueue tool. "
                "I bring expertise in NuClu and FintechTronica.\n\n"
                "Sincerely,\nMichael"
            )
        }

    monkeypatch.setattr(llm_cover_letter, "complete_json", _fake_complete_json)

    polished = llm_cover_letter.rewrite_cover_letter(
        deterministic_cover_letter="Dear Acme hiring team,\n\nHello.\n\nSincerely,\nMichael",
        job_description="Backend engineer at Acme.",
        company="Acme",
        title="Senior Backend Engineer",
        archetype_id="B_fintech_transaction_systems",
    )
    assert polished is None, "guardrail should have rejected invented metrics/tools"
