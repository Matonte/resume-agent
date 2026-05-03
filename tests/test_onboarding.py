"""Onboarding wizard: uploads, finish, and page gate."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.main import app

_JD = (
    "Acme Corp seeks a Senior Backend Engineer with Python, AWS, and distributed systems. "
    "You will design APIs, improve reliability, and partner with product. "
    "Requirements include 5+ years backend experience and strong testing practices."
)


@pytest.fixture
def client(isolated_outputs) -> TestClient:
    return TestClient(app)


def test_new_user_needs_onboarding_in_me(client: TestClient) -> None:
    email = f"ob_{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "N"},
    )
    assert r.status_code == 200, r.text
    me = client.get("/api/auth/me").json()
    assert me["email"] == email.lower()
    assert me["needs_onboarding"] is True
    assert me["requires_onboarding"] is True


def test_onboarding_gate_redirects_tailor(client: TestClient) -> None:
    email = f"og_{uuid.uuid4().hex[:12]}@example.com"
    assert client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "G"},
    ).status_code == 200
    r = client.get("/tailor", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers.get("location") == "/onboarding"


def test_onboarding_finish_without_llm(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "onboarding_allow_finish_without_llm", True)
    email = f"of_{uuid.uuid4().hex[:12]}@example.com"
    assert client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "F"},
    ).status_code == 200

    for _ in range(3):
        jr = client.post("/api/onboarding/job-sample", json={"text": _JD})
        assert jr.status_code == 200, jr.text

    resume_body = (
        "Jane Doe\nSenior Engineer\n\nAcme — Lead Developer (2020–present)\n"
        "• Shipped payment APIs\n• Led migration to cloud\n" * 5
    )
    fr = client.post(
        "/api/onboarding/resume",
        files={"file": ("cv.txt", resume_body.encode("utf-8"), "text/plain")},
    )
    assert fr.status_code == 200, fr.text

    fin = client.post("/api/onboarding/finish")
    assert fin.status_code == 200, fin.text
    assert fin.json()["ok"] is True

    me = client.get("/api/auth/me").json()
    assert me["needs_onboarding"] is False

    r = client.get("/tailor", follow_redirects=False)
    assert r.status_code == 200


def test_default_workspace_not_gated(client: TestClient) -> None:
    client.post("/api/auth/logout")
    r = client.get("/tailor", follow_redirects=False)
    assert r.status_code == 200


def test_tailoring_endpoints_403_before_onboarding_complete(client: TestClient) -> None:
    email = f"blk_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "B"},
    ).status_code == 200

    mt = client.post(
        "/api/manual-tailor",
        json={
            "description": (
                "Stripe is hiring a Senior Backend Engineer for payment infrastructure. "
                "Python, AWS, distributed systems required. " * 2
            ),
            "use_llm": False,
        },
    )
    assert mt.status_code == 403

    dr = client.post(
        "/api/draft-resume",
        json={
            "job_description": "Distributed systems and event pipelines " * 8,
            "archetype_id": "B_fintech_transaction_systems",
        },
    )
    assert dr.status_code == 403

    fd = client.post(
        "/api/full-draft",
        json={"description": "Distributed backend role, low latency and concurrency."},
    )
    assert fd.status_code == 403

    gr = client.post(
        "/api/generate-resume",
        json={"description": "Distributed backend role and APIs " * 10},
    )
    assert gr.status_code == 403
