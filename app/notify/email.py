"""Daily digest email via Gmail SMTP with an App Password.

Gmail requires an App Password (not your regular password) for SMTP. Set
`GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env`. The digest links each
job back to the local dashboard at `DASHBOARD_BASE_URL/jobs/today`.
"""

from __future__ import annotations

import html
import logging
import smtplib
from datetime import date
from email.message import EmailMessage
from typing import Iterable, List, Optional

from app.config import settings
from app.storage.db import JobRecord

logger = logging.getLogger(__name__)


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SMTPS (implicit TLS)


def _job_url(job: JobRecord) -> str:
    base = settings.dashboard_base_url.rstrip("/")
    return f"{base}/jobs/today#job-{job.id}"


def _fmt_fit(score: Optional[float]) -> str:
    return f"{score:.1f}/10" if isinstance(score, (int, float)) else "-"


def render_digest_html(jobs: Iterable[JobRecord], for_date: date) -> str:
    """Pure HTML renderer so tests can assert on structure without SMTP."""
    jobs = list(jobs)
    rows = []
    for j in jobs:
        rows.append(
            "<tr>"
            f"<td style='padding:6px 10px;'><a href='{html.escape(_job_url(j))}'>"
            f"{html.escape(j.title)}</a></td>"
            f"<td style='padding:6px 10px;'>{html.escape(j.company)}</td>"
            f"<td style='padding:6px 10px;'>{html.escape(j.location or '-')}</td>"
            f"<td style='padding:6px 10px;'>{html.escape(j.source)}</td>"
            f"<td style='padding:6px 10px;'>{_fmt_fit(j.fit_score)}</td>"
            f"<td style='padding:6px 10px;'><a href='{html.escape(j.url)}'>post</a></td>"
            "</tr>"
        )
    table_body = "\n".join(rows) or (
        "<tr><td colspan='6' style='padding:10px;text-align:center;color:#666;'>"
        "No jobs surfaced today.</td></tr>"
    )
    dashboard_url = settings.dashboard_base_url.rstrip("/") + "/jobs/today"
    return f"""<!doctype html>
<html><body style='font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:820px;margin:0 auto;padding:20px;'>
<h2 style='margin:0 0 8px 0;'>Daily job digest - {for_date.isoformat()}</h2>
<p style='color:#555;margin-top:0;'>{len(jobs)} tailored package(s) ready for review.
Open the <a href='{html.escape(dashboard_url)}'>dashboard</a> to approve or skip.</p>
<table style='border-collapse:collapse;width:100%;font-size:14px;'>
  <thead style='background:#f4f4f4;text-align:left;'>
    <tr>
      <th style='padding:6px 10px;'>Title</th>
      <th style='padding:6px 10px;'>Company</th>
      <th style='padding:6px 10px;'>Location</th>
      <th style='padding:6px 10px;'>Source</th>
      <th style='padding:6px 10px;'>Fit</th>
      <th style='padding:6px 10px;'>Link</th>
    </tr>
  </thead>
  <tbody>
    {table_body}
  </tbody>
</table>
<p style='color:#888;font-size:12px;margin-top:18px;'>resume-agent daily digest</p>
</body></html>
"""


def render_digest_text(jobs: Iterable[JobRecord], for_date: date) -> str:
    jobs = list(jobs)
    lines = [f"Daily job digest - {for_date.isoformat()} ({len(jobs)} job(s))", ""]
    for j in jobs:
        lines.append(
            f"- [{_fmt_fit(j.fit_score)}] {j.title} at {j.company} "
            f"({j.source}, {j.location or '-'})\n  {j.url}"
        )
    if not jobs:
        lines.append("  (no jobs today)")
    lines += ["", f"Open dashboard: {settings.dashboard_base_url.rstrip('/')}/jobs/today"]
    return "\n".join(lines)


def build_digest_message(jobs: List[JobRecord], for_date: date) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[resume-agent] Daily digest - {for_date.isoformat()} ({len(jobs)} jobs)"
    msg["From"] = settings.gmail_address or "resume-agent@localhost"
    msg["To"] = settings.gmail_address or "resume-agent@localhost"
    msg.set_content(render_digest_text(jobs, for_date))
    msg.add_alternative(render_digest_html(jobs, for_date), subtype="html")
    return msg


def send_digest(
    jobs: List[JobRecord],
    for_date: date,
    *,
    smtp_factory=None,  # for tests; defaults to smtplib.SMTP_SSL
) -> bool:
    """Send the digest. Returns True if the SMTP handshake + send succeeded.

    When `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` are not configured we log a
    warning and return False. The runner treats a False here as a non-fatal
    skip (it still records the run as complete).
    """
    if not settings.email_configured:
        logger.warning("Email not configured (GMAIL_ADDRESS/GMAIL_APP_PASSWORD); skipping digest")
        return False

    msg = build_digest_message(jobs, for_date)

    try:
        open_smtp = smtp_factory or (lambda: smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20))
        with open_smtp() as smtp:
            smtp.login(settings.gmail_address, settings.gmail_app_password)
            smtp.send_message(msg)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send digest email")
        return False

    logger.info("Sent digest email to %s (%d jobs)", settings.gmail_address, len(jobs))
    return True


__all__ = [
    "send_digest",
    "build_digest_message",
    "render_digest_html",
    "render_digest_text",
]
