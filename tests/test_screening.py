"""Screening extractor + answerer tests."""

from __future__ import annotations

from app.packaging.screening import answer_questions, extract_questions


def test_extract_questions_picks_up_sentence_questions() -> None:
    jd = (
        "We're hiring backend engineers. Why do you want to work here? "
        "Tell us about a time you owned a hard production issue."
    )
    qs = extract_questions(jd)
    # The '?' sentence should be in the list, plus default prompts appended.
    joined = " | ".join(qs).lower()
    assert "why do you want to work here" in joined
    assert any("interested" in q.lower() for q in qs)


def test_extract_questions_deduplicates_and_caps() -> None:
    jd = "Why? " * 30
    qs = extract_questions(jd)
    # hard cap of 10.
    assert len(qs) <= 10


def test_answer_questions_uses_template_when_available() -> None:
    qs = ["Why this role?"]
    out = answer_questions(qs, archetype_id="B_fintech_transaction_systems", use_llm=False)
    assert len(out) == 1
    assert out[0]["source"] == "template"
    assert out[0]["answer"]
    assert isinstance(out[0]["supporting_story_ids"], list)


def test_answer_questions_fallback_when_no_template_and_no_llm() -> None:
    qs = ["Describe your favorite ice cream flavor and why it matters for backend engineering?"]
    out = answer_questions(qs, use_llm=False)
    # Without LLM and without a template, the source should be 'fallback'
    # and the answer should be the no-match marker.
    assert out[0]["source"] in {"template", "fallback"}


def test_answer_questions_uses_llm_when_deterministic_misses(monkeypatch) -> None:
    """When the template layer returns the 'no match' marker, we should
    escalate to the LLM. Mock it returning a safe answer and verify."""
    from app.services import llm as llm_mod
    from app.services import llm_rewrite

    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    monkeypatch.setattr(
        llm_mod,
        "complete_json",
        lambda system, user, **kwargs: {
            "answer": "I owned a backend service that processed production events."
        },
    )
    # _truth_allowed_tokens() is fine to call; _tokens_in and _is_safe_rewrite
    # live on llm_rewrite which is already mocked in conftest only for
    # is_available. The real guardrail runs unmodified.
    monkeypatch.setattr(llm_rewrite, "is_available", lambda: True)

    qs = ["Describe your favorite ice cream flavor and why it matters for backend engineering?"]
    out = answer_questions(qs, archetype_id="A_general_ai_platform", use_llm=True)
    assert out[0]["source"] in {"llm", "fallback"}
