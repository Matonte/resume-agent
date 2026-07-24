"""Test-wide fixtures.

By default we force the LLM layer OFF during the test run so the suite stays
offline regardless of the developer's `.env`. Individual tests that want to
exercise LLM-guarded code can monkeypatch `app.services.llm.is_available`
and the completion functions directly.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _disable_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    # Reload the llm module's view of availability without re-importing.
    import app.services.llm as llm
    import app.services.llm_rewrite as llm_rewrite

    monkeypatch.setattr(llm, "is_available", lambda: False)
    monkeypatch.setattr(llm_rewrite, "is_available", lambda: False)
    yield


@pytest.fixture
def isolated_outputs(tmp_path, monkeypatch):
    """Point `settings.outputs_dir` at a tmp folder for the duration of a
    test. Any code that reads `outputs/jobs.sqlite` or writes under
    `outputs/<date>/` will land inside the fixture's tmp_path."""
    from app.config import settings

    monkeypatch.setattr(settings, "outputs_dir", str(tmp_path))
    yield tmp_path


def register_and_unlock(
    client: TestClient,
    *,
    email: str | None = None,
    password: str = "password123",
    use_builtin: bool = True,
) -> str:
    """Register, mark onboarding complete, optionally use repo ``data/`` pack."""
    from app.storage.accounts import get_user_by_email, mark_onboarding_complete
    from app.storage.db import get_conn

    email = email or f"u_{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Test User"},
    )
    assert r.status_code == 200, r.text
    with get_conn() as conn:
        u = get_user_by_email(conn, email)
        assert u is not None
        if use_builtin and u.active_profile_id:
            conn.execute(
                "UPDATE resume_profiles SET use_builtin = 1 WHERE id = ?",
                (u.active_profile_id,),
            )
            conn.commit()
        mark_onboarding_complete(conn, u.id)
    return email.lower()


@pytest.fixture
def authed_client(isolated_outputs) -> TestClient:
    """Signed-in client with onboarding complete and repo builtin profile."""
    from app.main import app

    client = TestClient(app)
    register_and_unlock(client)
    return client
