#!/usr/bin/env python3
"""Smoke-test meeting advisor + sibling classifier services (flask_sample).

Resume-agent calls meeting advisor HTTP API (default POST /api/v1/advise).
Optionally prints Contact Advisor people-intel schema GET when CONTACT_ADVISOR_SERVICE_URL (or WHOISWHAT_SERVICE_URL) is set.

Usage (from resume-agent repo root):
    python scripts/check_meeting_advisor_stack.py

Exit 0 if advisor POST succeeds; 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    # Loads .env via app.config
    from app.config import settings

    base = (settings.meeting_advisor_url or "").strip().rstrip("/")
    advise = settings.meeting_advisor_advise_url

    if not base:
        print("MEETING_ADVISOR_URL is not set in .env — resume-agent cannot reach an advisor.")
        return 1

    print(f"Resume-agent posts to: {advise!r}")
    browser = (settings.meeting_advisor_browser_redirect_url or "").strip()
    if browser:
        print(
            "Resume-agent browser (GET /meeting-advisor): redirects to external UI "
            f"{browser!r} — MEETING_ADVISOR_UI_URL is set."
        )

    timeout = httpx.Timeout(30.0, connect=5.0)
    with httpx.Client(timeout=timeout) as client:
        health_url = f"{base}/health"
        try:
            r = client.get(health_url)
            print(f"GET  {health_url}  -> {r.status_code}")
            if r.status_code != 200:
                print(f"  body (first 200 chars): {(r.text or '')[:200]!r}")
        except httpx.RequestError as e:
            print(f"GET  {health_url}  FAILED: {e}")
            print("  Is meeting_advisor running?  e.g. flask_sample: python run_meeting_advisor.py")
            return 1

        for label, url in (
            ("Contact Advisor (K)", "http://127.0.0.1:5000/health"),
            ("WhoIsHoss", "http://127.0.0.1:5002/health"),
        ):
            try:
                hr = client.get(url)
                print(f"GET  {url}  ({label}) -> {hr.status_code}")
                if hr.status_code != 200:
                    print(
                        f"  {label} not healthy — advisor may return empty k_profile / hoss_profile. "
                        f"Start: flask_sample `python run.py` and `python run_whoishoss.py`"
                    )
            except httpx.RequestError as e:
                print(f"GET  {url}  ({label}) FAILED: {e}")

        payload = {
            "subject_name": "Smoke Test Contact",
            "notes": "x" * 80,
            "source_hint": "",
            "context": {"setting": "interview", "your_role": "engineer", "stakes": "low", "goals": "sanity check"},
        }
        try:
            pr = client.post(advise, json=payload)
            print(f"POST {advise}  -> {pr.status_code}")
            if pr.status_code != 200:
                print(f"  body (first 500 chars): {(pr.text or '')[:500]!r}")
                return 1
            data = pr.json()
            if isinstance(data, dict):
                if data.get("k_error"):
                    print(f"  k_error: {data['k_error']!r}")
                if data.get("hoss_error"):
                    print(f"  hoss_error: {data['hoss_error']!r}")
                if data.get("advice"):
                    print("  advice: present")
        except httpx.RequestError as e:
            print(f"POST {advise}  FAILED: {e}")
            return 1

        wi_base = (settings.whoiswhat_service_url or "").strip().rstrip("/")
        if wi_base:
            schema_url = f"{wi_base}/api/v1/people-intel/schema"
            try:
                sr = client.get(schema_url)
                print(f"GET  {schema_url}  (people-intel schema) -> {sr.status_code}")
            except httpx.RequestError as e:
                print(f"GET  {schema_url}  FAILED: {e}")
        else:
            print(
                "WHOISWHAT_SERVICE_URL unset — resume-agent outreach skips people-intel "
                "(set CONTACT_ADVISOR_SERVICE_URL or WHOISWHAT_SERVICE_URL to flask_sample "
                "Contact Advisor base, e.g. http://127.0.0.1:5000)."
            )

    print("OK: advisor accepted POST /api/v1/advise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
