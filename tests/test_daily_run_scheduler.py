"""Embedded daily_run scheduler (ties scraping to uvicorn lifespan)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app import daily_run_scheduler as daily_run_scheduler_mod
from app.jobs.runner import RunSummary
from app.main import app


@pytest.fixture
def enable_embedded_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily_run_scheduler_mod, "_MIN_EMBEDDED_INTERVAL_SEC", 1)
    monkeypatch.setattr(settings, "daily_run_with_server", True)
    monkeypatch.setattr(settings, "daily_run_embedded_interval_seconds", 1)


def test_lifespan_invokes_run_daily_when_embedded_enabled(
    enable_embedded_daily: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_run = MagicMock(
        return_value=RunSummary(
            run_id="test-run",
            scraped=0,
            filtered=0,
            tailored=0,
            kept=0,
            email_sent=False,
            errors=[],
        )
    )
    monkeypatch.setattr("app.jobs.runner.run_daily", mock_run)

    with TestClient(app):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and mock_run.call_count < 1:
            time.sleep(0.05)

    assert mock_run.call_count >= 1
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("send_email") is True
    assert kwargs.get("use_llm") is True
    assert kwargs.get("check_auth") is True
