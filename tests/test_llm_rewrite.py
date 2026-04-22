"""Guardrail tests for the LLM rewrite layer.

The real OpenAI call is mocked out via monkeypatching so these tests are
fast and deterministic. We focus on the safety net: does the guardrail
correctly reject rewrites that introduce hallucinated facts?
"""

from __future__ import annotations

import app.services.llm as llm
import app.services.llm_rewrite as llm_rewrite
from app.services.llm_rewrite import (
    _is_safe_rewrite,
    _truth_allowed_tokens,
    rewrite_bullets,
    rewrite_summary,
)


def _enable_llm(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm_rewrite, "is_available", lambda: True)


# ---------- guardrail unit tests ----------


def test_guardrail_rejects_new_numbers():
    src = "Reduced manual provisioning by approximately 70 percent."
    bad = "Reduced manual provisioning by 95 percent."
    assert not _is_safe_rewrite(src, bad, _truth_allowed_tokens())


def test_guardrail_rejects_hallucinated_tools():
    src = "Built APIs on OpenShift."
    bad = "Built APIs on Kubernetes, Istio, Envoy, ArgoCD, and Cilium."
    assert not _is_safe_rewrite(src, bad, set())


def test_guardrail_accepts_safe_rephrase():
    src = "Architected and delivered an event-driven access-control platform."
    good = "Designed and delivered an event-driven access-control platform."
    assert _is_safe_rewrite(src, good, _truth_allowed_tokens())


# ---------- end-to-end: mocked LLM returns a clean rewrite ----------


def test_rewrite_summary_accepts_clean_response(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(
        llm_rewrite,
        "complete_json",
        lambda *a, **kw: {
            "summary": (
                "Senior Backend Engineer with 11+ years of experience building "
                "reliable distributed systems and backend platforms."
            )
        },
    )
    out = rewrite_summary(
        "Senior Backend Engineer with 11+ years of experience building scalable backend systems.",
        "Senior backend role building distributed systems.",
        "A_general_ai_platform",
    )
    assert "Senior Backend Engineer" in out
    assert "11+" in out


def test_rewrite_summary_falls_back_on_hallucination(monkeypatch):
    _enable_llm(monkeypatch)
    original = "Senior Backend Engineer with 11+ years of experience."
    monkeypatch.setattr(
        llm_rewrite,
        "complete_json",
        lambda *a, **kw: {"summary": "FAANG tech lead with 20 years leading 40+ engineers."},
    )
    out = rewrite_summary(original, "any JD", "A_general_ai_platform")
    assert out == original, "hallucinated numbers should be rejected"


def test_rewrite_bullets_preserves_count_and_rejects_bad_items(monkeypatch):
    _enable_llm(monkeypatch)
    sources = [
        "Architected and delivered an event-driven access-control platform.",
        "Reduced manual provisioning by approximately 70 percent.",
    ]
    monkeypatch.setattr(
        llm_rewrite,
        "complete_json",
        lambda *a, **kw: {
            "bullets": [
                "Designed and delivered an event-driven access-control platform.",
                "Reduced manual provisioning by 99 percent.",
            ]
        },
    )
    out = rewrite_bullets(sources, "some JD")
    assert len(out) == 2
    assert out[0].lower().startswith("designed")
    assert out[1] == sources[1], "bad rewrite with new number should fall back"


def test_rewrite_bullets_rejects_wrong_length(monkeypatch):
    _enable_llm(monkeypatch)
    sources = ["A.", "B.", "C."]
    monkeypatch.setattr(
        llm_rewrite,
        "complete_json",
        lambda *a, **kw: {"bullets": ["only one"]},
    )
    out = rewrite_bullets(sources, "jd")
    assert out == sources


def test_rewrite_functions_noop_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: False)
    monkeypatch.setattr(llm_rewrite, "is_available", lambda: False)
    assert rewrite_summary("hello", "jd", "A_general_ai_platform") == "hello"
    assert rewrite_bullets(["a", "b"], "jd") == ["a", "b"]
