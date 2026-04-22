"""Application-answer tests: verify intent detection and archetype bias."""

from app.services.application_answers import answer_application_question


def test_why_this_role_fintech_uses_fintech_template():
    result = answer_application_question(
        "Why this role?", archetype_id="B_fintech_transaction_systems"
    )
    assert "financial" in result["answer"].lower() or "fintech" in result["answer"].lower()


def test_why_this_role_streaming_uses_streaming_template():
    result = answer_application_question(
        "Why this role?", archetype_id="C_data_streaming_systems"
    )
    assert "ingestion" in result["answer"].lower() or "data" in result["answer"].lower()


def test_ambiguity_returns_supporting_story():
    result = answer_application_question(
        "Tell me about handling ambiguity."
    )
    assert result["answer"]
    assert result["supporting_story_ids"], "ambiguity answer should link to a story"


def test_ownership_returns_supporting_story():
    result = answer_application_question(
        "Describe a time you took ownership of a project."
    )
    assert result["supporting_story_ids"]


def test_unknown_question_falls_back():
    result = answer_application_question("What is your favorite color?")
    assert "template matched" in result["answer"].lower() or "story bank" in result["answer"].lower()
    assert result["supporting_story_ids"] == []
