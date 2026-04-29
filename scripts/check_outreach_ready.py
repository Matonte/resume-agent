#!/usr/bin/env python3
"""Print whether outreach (web search + optional advisor) is ready to run.

Usage from repo root:
    python scripts/check_outreach_ready.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import settings  # noqa: E402
from app.jobs.preferences import load_preferences  # noqa: E402


def main() -> int:
    prefs = load_preferences()
    problems: list[str] = []
    ok: list[str] = []

    if prefs.outreach_for_job.enabled:
        ok.append("data/preferences.yaml: outreach_for_job.enabled is true")
    else:
        problems.append(
            "Set outreach_for_job.enabled: true in data/preferences.yaml"
        )

    if settings.web_search_configured:
        parts = []
        if settings.google_cse_api_key and settings.google_cse_cx:
            parts.append("Google CSE")
        if settings.bing_search_key:
            parts.append("Bing")
        ok.append("Web search: " + " + ".join(parts))
    else:
        problems.append(
            "Add GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX and/or BING_SEARCH_KEY to .env"
        )

    if settings.meeting_advisor_configured:
        ok.append(f"MEETING_ADVISOR_URL={settings.meeting_advisor_url}")
    else:
        ok.append(
            "MEETING_ADVISOR_URL not set (optional: interview-style advice from "
            "flask_sample will be skipped)"
        )

    if settings.llm_configured:
        ok.append("OPENAI_API_KEY is set (dossier enrichment)")
    else:
        problems.append("OPENAI_API_KEY missing — set it for LLM dossier text")

    for line in ok:
        print(f"ok  {line}")
    for line in problems:
        print(f"!!  {line}")

    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
