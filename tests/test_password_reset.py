"""Password reset (forgot password) flow."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.password_reset import create_password_reset_token
from app.config import settings
from app.main import app
from app.storage.db import get_conn, init_db


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "outputs_dir", str(tmp_path / "out"))
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "mysql_host", "")
    monkeypatch.setattr(settings, "onboarding_allow_finish_without_llm", True)
    monkeypatch.setattr(settings, "expose_password_reset_token", True)
    init_db()
    return TestClient(app)


def test_forgot_password_unknown_email_still_ok(client: TestClient) -> None:
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "dev_reset_token" not in body


def test_forgot_and_reset_password(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = {}

    def fake_send(to_email, subject, *, text_body, html_body=None, smtp_factory=None):
        sent["to"] = to_email
        sent["subject"] = subject
        sent["text"] = text_body
        return True

    monkeypatch.setattr("app.notify.email.send_simple_email", fake_send)
    monkeypatch.setattr(settings, "gmail_address", "sender@example.com")
    monkeypatch.setattr(settings, "gmail_app_password", "app-pass")

    email = "resetme@example.com"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": "oldpassword", "display_name": "Reset Me"},
    )
    assert reg.status_code == 200
    client.post("/api/auth/logout")

    r = client.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    body = r.json()
    assert body["email_sent"] is True
    assert body["dev_reset_token"]
    assert sent["to"] == email
    assert "/account?reset=" in sent["text"]

    token = body["dev_reset_token"]
    bad = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "short"},
    )
    assert bad.status_code == 422

    ok = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "newpassword99"},
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == email
    assert ok.json()["user"]["authenticated"] is True

    # Token is single-use
    reuse = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "anotherpass99"},
    )
    assert reuse.status_code == 400

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": "newpassword99"},
    )
    assert login.status_code == 200


def test_expired_or_bogus_token_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/auth/reset-password",
        json={"token": "definitely-not-a-real-token-value", "password": "newpassword99"},
    )
    assert r.status_code == 400


def test_create_token_helper_roundtrip(client: TestClient) -> None:
    email = "helper@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "oldpassword", "display_name": "H"},
    )
    with get_conn() as conn:
        from app.storage.accounts import get_user_by_email

        u = get_user_by_email(conn, email)
        assert u is not None
        raw = create_password_reset_token(conn, u.id)
    r = client.post(
        "/api/auth/reset-password",
        json={"token": raw, "password": "brandnewpass1"},
    )
    assert r.status_code == 200
