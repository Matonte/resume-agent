"""Tests for posting People extraction and follow-up query builder."""

from __future__ import annotations

from unittest.mock import patch

from app.scrapers.base import RawJob
from app.services.outreach_posting_people import (
    PostingPerson,
    build_followup_queries,
    extract_people_from_posting_corpus,
    merge_posting_corpus,
)


def test_merge_posting_corpus_uses_jd_only_when_no_apply() -> None:
    raw = RawJob(
        source="x",
        url="https://boards.example/j/1",
        title="T",
        company="Co",
        jd_full="About the team.\nContact Jamie Smith for questions.",
    )
    assert merge_posting_corpus(raw, fetch_apply_page=True) == raw.jd_full


def test_build_followup_queries_dedupes_and_caps() -> None:
    people = [
        PostingPerson("Pat Jones"),
        PostingPerson("Pat Jones"),
        PostingPerson("Sam Ali Boom"),
    ]
    qs = build_followup_queries(people, "Acme Corp", max_queries=2)
    assert len(qs) == 2
    assert qs[0] == '"Pat Jones" Acme Corp'
    assert '"Sam Ali Boom" Acme Corp' in qs


def test_extract_people_parses_llm_json() -> None:
    fake_json = {
        "people": [
            {
                "name": "Jordan Lee",
                "role_hint": "Recruiter",
                "evidence": "Reach out to Jordan Lee (talent)",
            },
            {"name": "Apply", "role_hint": "", "evidence": "bad"},
        ]
    }
    with patch("app.services.outreach_posting_people.is_available", return_value=True):
        with patch(
            "app.services.outreach_posting_people.complete_json",
            return_value=fake_json,
        ):
            out = extract_people_from_posting_corpus(
                "Some JD text",
                "Co",
                max_people=5,
                use_llm=True,
            )
    assert len(out) == 1
    assert out[0].name == "Jordan Lee"
    assert out[0].role_hint == "Recruiter"


def test_extract_people_skips_without_llm() -> None:
    out = extract_people_from_posting_corpus(
        "Jordan Lee hires here",
        "Co",
        max_people=5,
        use_llm=False,
    )
    assert out == []
