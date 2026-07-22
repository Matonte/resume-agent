"""Multi-user auth and resume profile tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.data_context import get_candidate_data_dir, push_candidate_dir, reset_candidate_token
from app.storage.accounts import get_profile_for_user
from app.storage.db import get_conn


@pytest.fixture
def client(isolated_outputs) -> TestClient:
    return TestClient(app)


def test_register_login_me_logout(client: TestClient) -> None:
    email = f"u_{uuid.uuid4().hex[:12]}@example.com"
    r = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": "Tester",
        },
    )
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["id"]
    assert uid >= 2

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == email.lower()

    client.post("/api/auth/logout")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["id"] == 1

    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me").json()["email"] == email.lower()


def test_profiles_list_and_activate(client: TestClient) -> None:
    email = f"p_{uuid.uuid4().hex[:12]}@example.com"
    assert client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "P"},
    ).status_code == 200

    r = client.get("/api/profiles")
    assert r.status_code == 200
    profs = r.json()["profiles"]
    assert len(profs) >= 1
    pid1 = profs[0]["id"]

    r = client.post("/api/profiles", json={"name": "Second pack"})
    assert r.status_code == 200, r.text
    pid2 = r.json()["id"]
    assert pid2 != pid1

    assert client.post(f"/api/profiles/{pid1}/activate").status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["active_profile_id"] == pid1


def test_candidate_data_context_per_profile(isolated_outputs, monkeypatch) -> None:
    from app.storage.accounts import create_user_with_profile
    from app.auth.passwords import hash_password
    import json

    with get_conn() as conn:
        uid, pid = create_user_with_profile(
            conn,
            email=f"ctx_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("x"),
            display_name="Ctx",
        )
        p = get_profile_for_user(conn, uid, pid)
    assert p is not None
    disk = p.effective_candidate_dir()
    assert disk is not None
    truth = json.loads((disk / "master_truth_model.json").read_text(encoding="utf-8"))
    assert truth.get("roles") == []
    assert "matonte" not in json.dumps(truth).lower()
    token = push_candidate_dir(disk)
    try:
        assert get_candidate_data_dir() == disk
    finally:
        reset_candidate_token(token)
    assert get_candidate_data_dir().name == "data"


def test_rag_profile_id_when_default_user_is_tenant(isolated_outputs) -> None:
    """DEFAULT_USER_ID pointing at a real tenant must still enable per-profile RAG."""
    from app.auth.passwords import hash_password
    from app.storage.accounts import create_user_with_profile, rag_profile_id_for_user

    with get_conn() as conn:
        uid, pid = create_user_with_profile(
            conn,
            email=f"rag_{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("password123"),
            display_name="Rag",
        )
        assert rag_profile_id_for_user(conn, uid, default_user_id=uid) == pid
        assert rag_profile_id_for_user(conn, 1, default_user_id=1) is None


def test_me_authenticated_flag(client: TestClient) -> None:
    client.post("/api/auth/logout")
    anon = client.get("/api/auth/me").json()
    assert anon["authenticated"] is False

    email = f"authflag_{uuid.uuid4().hex[:10]}@example.com"
    assert (
        client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123", "display_name": "A"},
        ).status_code
        == 200
    )
    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True
    assert me["email"] == email.lower()
