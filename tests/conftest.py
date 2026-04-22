"""Test-wide fixtures.

By default we force the LLM layer OFF during the test run so the suite stays
offline regardless of the developer's `.env`. Individual tests that want to
exercise LLM-guarded code can monkeypatch `app.services.llm.is_available`
and the completion functions directly.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    # Reload the llm module's view of availability without re-importing.
    import app.services.llm as llm
    import app.services.llm_rewrite as llm_rewrite

    monkeypatch.setattr(llm, "is_available", lambda: False)
    monkeypatch.setattr(llm_rewrite, "is_available", lambda: False)
    yield
