"""Opt-in live API smoke tests (non-deterministic; checks structure only)."""

from __future__ import annotations

import os

import pytest

from app.config import settings
from app.services.llm_rewrite import rewrite_bullets

pytestmark = pytest.mark.llm_live


def _live_allowed() -> bool:
    return bool(settings.openai_api_key) and os.environ.get("RUN_LLM_LIVE", "").strip() in (
        "1",
        "true",
        "yes",
    )


@pytest.mark.skipif(not _live_allowed(), reason="Set OPENAI_API_KEY and RUN_LLM_LIVE=1")
def test_live_rewrite_bullets_smoke() -> None:
    src = [
        "Maintained a streaming aggregation service processing 500k events per minute.",
    ]
    jd = (
        "Senior Software Engineer — Kafka, stream processing, "
        "Java, low-latency data paths."
    )
    out = rewrite_bullets(src, jd)
    assert isinstance(out, list)
    assert len(out) == len(src)
    assert all(isinstance(b, str) and len(b) > 20 for b in out)
