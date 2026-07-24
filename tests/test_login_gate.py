"""Login gate: product surfaces require a signed-in session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_anonymous_html_redirects_to_account() -> None:
    client = TestClient(app)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location") == "/account"


def test_anonymous_api_returns_401() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/full-draft",
        json={"description": "Distributed backend role with concurrency."},
    )
    assert r.status_code == 401
    assert "Log in" in r.json()["detail"]


def test_health_and_account_remain_public() -> None:
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/account").status_code == 200
    assert "Register" in client.get("/account").text
