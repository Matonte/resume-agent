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

    # Scheduled daily_run uses this account unless overridden on the CLI.
    daily_run_user_id: int = int(_strip(os.getenv("DAILY_RUN_USER_ID")) or "1")
    playwright_profiles_dir: str = (
        _strip(os.getenv("PLAYWRIGHT_PROFILES_DIR")) or str(_REPO_ROOT / ".playwright")
    )

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
    # and you need to reuse an existing browser session (e.g. your real
    # Chrome user-data dir on Windows:
    # %LOCALAPPDATA%\Google\Chrome\User Data). Requires the source browser
    # to be *closed* before the agent runs.
    wttj_profile_dir: str = _strip(os.getenv("WTTJ_PROFILE_DIR"))
    linkedin_profile_dir: str = _strip(os.getenv("LINKEDIN_PROFILE_DIR"))
    jobright_profile_dir: str = _strip(os.getenv("JOBRIGHT_PROFILE_DIR"))

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
    def outputs_path(self) -> Path:
        return Path(self.outputs_dir)

    @property
    def playwright_profiles_path(self) -> Path:
        return Path(self.playwright_profiles_dir)


settings = Settings()
