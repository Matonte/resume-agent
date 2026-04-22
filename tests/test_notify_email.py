"""Email digest tests: rendering + mocked SMTP handshake."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.storage.db import JobRecord
from app.notify.email import (
    build_digest_message,
    render_digest_html,
    render_digest_text,
    send_digest,
)


def _sample_jobs() -> list[JobRecord]:
    return [
        JobRecord(
            id="abcd1234",
            source="jobright",
            url="https://jobright.ai/jobs/1",
            title="Senior Backend Engineer",
            company="Helix Fintech",
            location="Remote (US)",
            jd_full="JD body",
            fit_score=8.7,
            daily_run_id="2026-04-22",
        ),
        JobRecord(
            id="efef5678",
            source="linkedin",
            url="https://linkedin.com/jobs/view/2",
            title="Staff Engineer",
            company="Ledgerline",
            location="New York, NY",
            jd_full="JD body",
            fit_score=6.2,
            daily_run_id="2026-04-22",
        ),
    ]


def test_render_html_contains_links_and_rows() -> None:
    html = render_digest_html(_sample_jobs(), date(2026, 4, 22))
    assert "Helix Fintech" in html
    assert "Ledgerline" in html
    assert "8.7/10" in html
    assert "2026-04-22" in html
    assert "jobs/today" in html


def test_render_text_lists_each_job() -> None:
    txt = render_digest_text(_sample_jobs(), date(2026, 4, 22))
    assert "Helix Fintech" in txt
    assert "Ledgerline" in txt
    assert txt.startswith("Daily job digest")


def test_build_digest_message_multipart() -> None:
    msg = build_digest_message(_sample_jobs(), date(2026, 4, 22))
    assert "2026-04-22" in msg["Subject"]
    assert msg.is_multipart()
    # Expect both plain and html parts.
    subtypes = {p.get_content_subtype() for p in msg.iter_parts()}
    assert "plain" in subtypes
    assert "html" in subtypes


def test_send_digest_skips_when_email_not_configured(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "gmail_address", "")
    monkeypatch.setattr(settings, "gmail_app_password", "")
    assert send_digest(_sample_jobs(), date(2026, 4, 22)) is False


def test_send_digest_logs_in_and_sends(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "gmail_address", "me@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "app-password")

    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.__exit__.return_value = False

    def factory():
        return smtp

    sent = send_digest(_sample_jobs(), date(2026, 4, 22), smtp_factory=factory)
    assert sent is True
    smtp.login.assert_called_once_with("me@example.com", "app-password")
    smtp.send_message.assert_called_once()
