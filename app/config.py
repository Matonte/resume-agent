"""Runtime settings. Loads `.env` on import so CLI / uvicorn / pytest all
see the same values without a separate dotenv loader at the entrypoint.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# override=False: real process env wins over .env (useful in CI/tests).
load_dotenv(_ENV_PATH, override=False)


def _strip(val: str | None) -> str:
    return (val or "").strip()


_REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    openai_api_key: str = _strip(os.getenv("OPENAI_API_KEY"))
    model_name: str = _strip(os.getenv("MODEL_NAME")) or "gpt-5.4"

    gmail_address: str = _strip(os.getenv("GMAIL_ADDRESS"))
    gmail_app_password: str = _strip(os.getenv("GMAIL_APP_PASSWORD"))
    dashboard_base_url: str = _strip(os.getenv("DASHBOARD_BASE_URL")) or "http://127.0.0.1:8000"

    outputs_dir: str = _strip(os.getenv("OUTPUTS_DIR")) or str(_REPO_ROOT / "outputs")

    # Session cookie signing (set in production). Default is dev-only.
    session_secret: str = _strip(os.getenv("SESSION_SECRET")) or "dev-session-secret-change-me"

    # Anonymous / CLI default workspace user (built-in repo `data/`).
    default_user_id: int = int(_strip(os.getenv("DEFAULT_USER_ID")) or "1")

    # New-account wizard (résumé + job samples → profile JSON). Tests may set
    # ONBOARDING_ALLOW_FINISH_WITHOUT_LLM=1 to skip the LLM merge step.
    onboarding_min_resumes: int = int(_strip(os.getenv("ONBOARDING_MIN_RESUMES")) or "1")
    onboarding_min_job_samples: int = int(
        _strip(os.getenv("ONBOARDING_MIN_JOB_SAMPLES")) or "3"
    )
    onboarding_allow_finish_without_llm: bool = _strip(
        os.getenv("ONBOARDING_ALLOW_FINISH_WITHOUT_LLM")
    ).lower() in ("1", "true", "yes")

    # Scheduled daily_run uses this account unless overridden on the CLI.
    daily_run_user_id: int = int(_strip(os.getenv("DAILY_RUN_USER_ID")) or "1")
    playwright_profiles_dir: str = (
        _strip(os.getenv("PLAYWRIGHT_PROFILES_DIR")) or str(_REPO_ROOT / ".playwright")
    )
    #: Playwright `channel` for `chromium.launch_persistent_context`: unset =
    #: bundled Chromium for `.playwright/profile-*`. Set `msedge` to use the
    #: installed Microsoft Edge; set `chrome` for Google Chrome. With
    #: `*_PROFILE_DIR` overrides, defaults to `chrome` when unset (legacy).
    playwright_channel: str = _strip(os.getenv("PLAYWRIGHT_CHANNEL"))

    # --- Job-site credentials (optional; used only by scripts/login_once.py) ---
    linkedin_email: str = _strip(os.getenv("LINKEDIN_EMAIL"))
    linkedin_password: str = _strip(os.getenv("LINKEDIN_PASSWORD"))
    wttj_email: str = _strip(os.getenv("WTTJ_EMAIL"))
    wttj_password: str = _strip(os.getenv("WTTJ_PASSWORD"))
    jobright_email: str = _strip(os.getenv("JOBRIGHT_EMAIL"))
    jobright_password: str = _strip(os.getenv("JOBRIGHT_PASSWORD"))

    # --- Per-site profile overrides ---
    # When set, Playwright uses this path as `user_data_dir` for that site
    # instead of the default `.playwright/profile-<site>/` directory. Useful
    # when a site's login flow is too hostile to Playwright-driven Chromium
    # and you need to reuse an existing browser session, e.g.:
    #   Chrome: %LOCALAPPDATA%\Google\Chrome\User Data
    #   Edge:   %LOCALAPPDATA%\Microsoft\Edge\User Data
    # Set PLAYWRIGHT_CHANNEL=msedge when using an Edge user-data dir, or
    # PLAYWRIGHT_CHANNEL=chrome for Chrome. The source browser must be *closed*
    # before the agent runs.
    wttj_profile_dir: str = _strip(os.getenv("WTTJ_PROFILE_DIR"))
    linkedin_profile_dir: str = _strip(os.getenv("LINKEDIN_PROFILE_DIR"))
    jobright_profile_dir: str = _strip(os.getenv("JOBRIGHT_PROFILE_DIR"))

    # --- Web search (outreach / combination search: Google CSE + Bing) ---
    google_cse_api_key: str = _strip(os.getenv("GOOGLE_CSE_API_KEY"))
    google_cse_cx: str = _strip(os.getenv("GOOGLE_CSE_CX"))
    bing_search_key: str = _strip(os.getenv("BING_SEARCH_KEY"))

    # --- Optional whoiswhat agent (sibling repo): recruiter / HM enrichment ---
    # Add the repo root to Python's path, then set module + callable that accepts
    # (items, company_description=...) — see app.services.outreach_enrich.
    whoiswhat_agent_path: str = _strip(os.getenv("WHOISWHAT_AGENT_PATH"))
    whoiswhat_enrich_module: str = _strip(os.getenv("WHOISWHAT_ENRICH_MODULE"))
    whoiswhat_enrich_callable: str = (
        _strip(os.getenv("WHOISWHAT_ENRICH_CALLABLE")) or "enrich_contacts"
    )

    # meeting_advisor service (WhoIsWhat K + WhoIsHoss + tactical JSON).
    # Base URL only — POST goes to meeting_advisor_url + meeting_advisor_advise_path.
    # Must be the process that implements POST .../api/v1/advise (often a
    # separate port, e.g. flask_sample on :5003), NOT resume-agent's URL unless
    # you mount that route on the same server.
    meeting_advisor_url: str = _strip(os.getenv("MEETING_ADVISOR_URL"))
    #: Optional **browser redirect** for Advisor links only. When set, GET /meeting-advisor
    #: (and aliases) send the browser to this URL instead of serving resume-agent HTML.
    #: When unset, the embedded advisor page is always served; API POSTs still use
    #: ``meeting_advisor_url`` + advise path.
    meeting_advisor_ui_url: str = _strip(os.getenv("MEETING_ADVISOR_UI_URL"))
    #: Path appended to base (leading slash). Override if your advisor uses a different route.
    meeting_advisor_advise_path: str = (
        _strip(os.getenv("MEETING_ADVISOR_ADVISE_PATH")) or "/api/v1/advise"
    )

    # Contact Advisor (flask_sample `python run.py`) — people-intel: POST /api/v1/people-intel.
    # Prefer CONTACT_ADVISOR_SERVICE_URL; WHOISWHAT_SERVICE_URL is a deprecated alias.
    whoiswhat_service_url: str = _strip(
        os.getenv("CONTACT_ADVISOR_SERVICE_URL") or os.getenv("WHOISWHAT_SERVICE_URL")
    )
    whoiswhat_people_intel_path: str = (
        _strip(os.getenv("WHOISWHAT_PEOPLE_INTEL_PATH")) or "/api/v1/people-intel"
    )

    def site_credentials(self, site: str) -> tuple[str, str]:
        """Return `(email, password)` for a site. Empty strings when unset.
        Used only by the one-time login helper; scrapers rely on cookies."""
        mapping = {
            "linkedin": (self.linkedin_email, self.linkedin_password),
            "wttj": (self.wttj_email, self.wttj_password),
            "jobright": (self.jobright_email, self.jobright_password),
        }
        return mapping.get(site, ("", ""))

    def site_profile_override(self, site: str) -> str:
        """Return a configured user-data-dir override for `site`, or ""."""
        mapping = {
            "linkedin": self.linkedin_profile_dir,
            "wttj": self.wttj_profile_dir,
            "jobright": self.jobright_profile_dir,
        }
        return mapping.get(site, "")

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def email_configured(self) -> bool:
        return bool(self.gmail_address and self.gmail_app_password)

    @property
    def web_search_configured(self) -> bool:
        return bool(
            (self.google_cse_api_key and self.google_cse_cx) or self.bing_search_key
        )

    @property
    def meeting_advisor_advise_url(self) -> str:
        """Full URL for POST (base stripped of trailing slash + normalized path)."""
        base = (self.meeting_advisor_url or "").strip().rstrip("/")
        path = (self.meeting_advisor_advise_path or "/api/v1/advise").strip()
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}" if base else ""

    @property
    def meeting_advisor_configured(self) -> bool:
        return bool(self.meeting_advisor_url)

    @property
    def whoiswhat_people_intel_post_url(self) -> str:
        """Full URL for POST people-intel (public professional context synthesis)."""
        base = (self.whoiswhat_service_url or "").strip().rstrip("/")
        path = (self.whoiswhat_people_intel_path or "/api/v1/people-intel").strip()
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}" if base else ""

    @property
    def whoiswhat_people_intel_configured(self) -> bool:
        return bool((self.whoiswhat_service_url or "").strip())

    @property
    def meeting_advisor_browser_redirect_url(self) -> str:
        """Optional external URL for GET /meeting-advisor when set via ``MEETING_ADVISOR_UI_URL``.

        Empty string means serve the embedded advisor page (whether or not the API
        base ``MEETING_ADVISOR_URL`` is configured).
        """
        return (self.meeting_advisor_ui_url or "").strip().rstrip("/")

    @property
    def outputs_path(self) -> Path:
        return Path(self.outputs_dir)

    @property
    def playwright_profiles_path(self) -> Path:
        return Path(self.playwright_profiles_dir)


settings = Settings()
