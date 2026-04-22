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


class Settings(BaseModel):
    openai_api_key: str = _strip(os.getenv("OPENAI_API_KEY"))
    model_name: str = _strip(os.getenv("MODEL_NAME")) or "gpt-5.4"

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
