"""Offline LLM regression: mock `complete_json`, assert final pipeline outputs.

Runs in CI without OPENAI_API_KEY. Extend `cases/*.json` and re-record with
`python scripts/record_llm_regression.py` when prompts or guardrails change.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import pytest

from app.packaging import llm_cover_letter as llm_cover_letter_mod
from app.services import llm as llm_mod
from app.services import llm_rewrite as llm_rewrite_mod
from app.packaging.llm_cover_letter import rewrite_cover_letter
from app.services.llm_rewrite import rewrite_bullets, rewrite_summary

from .loader import load_cases

HANDLERS: Dict[str, Callable[..., Any]] = {
    "rewrite_bullets": rewrite_bullets,
    "rewrite_summary": rewrite_summary,
    "rewrite_cover_letter": rewrite_cover_letter,
}


def _patch_llm(monkeypatch: pytest.MonkeyPatch, mock_return: Any) -> None:
    """Enable LLM paths and return a fixed completion payload.

    Patch `complete_json` on every module that imported it — binding is
    per-module, so `app.services.llm.complete_json` alone is not enough.
    """
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    monkeypatch.setattr(llm_rewrite_mod, "is_available", lambda: True)
    monkeypatch.setattr(llm_cover_letter_mod, "is_available", lambda: True)

    def _fake_complete_json(*_a, **_k):
        return mock_return

    monkeypatch.setattr(llm_mod, "complete_json", _fake_complete_json)
    monkeypatch.setattr(llm_rewrite_mod, "complete_json", _fake_complete_json)
    monkeypatch.setattr(llm_cover_letter_mod, "complete_json", _fake_complete_json)


@pytest.mark.llm_regression
@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_llm_pipeline_regression(case: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    handler = case["handler"]
    fn = HANDLERS.get(handler)
    if fn is None:
        pytest.fail(f"unknown handler {handler!r} in {case.get('_path')}")

    _patch_llm(monkeypatch, case.get("llm_mock_return"))
    kwargs = dict(case["kwargs"])
    result = fn(**kwargs)
    exp = case["expect"]

    if handler == "rewrite_bullets":
        assert result == exp["final_bullets"]
    elif handler == "rewrite_summary":
        assert result == exp["final_summary"]
    elif handler == "rewrite_cover_letter":
        assert result == exp["final_cover_letter"]
    else:
        pytest.fail(f"no assertions for handler {handler}")
