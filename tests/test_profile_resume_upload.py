"""Post-onboarding résumé upload into an active user profile."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.main import app
from app.storage.accounts import (
    get_user_by_email,
    mark_onboarding_complete,
    profile_disk_dir,
    profile_upload_rel_prefix,
)
from app.storage.db import get_conn

_JD = (
    "Acme Corp seeks a Senior Backend Engineer with Python, AWS, and distributed systems. "
    "You will design APIs, improve reliability, and partner with product. "
    "Requirements include 5+ years backend experience and strong testing practices."
)

_RESUME = (
    "Jane Doe\nSenior Engineer\n\nAcme — Lead Developer (2020–present)\n"
    "• Shipped payment APIs\n• Led migration to cloud\n" * 5
)


@pytest.fixture
def client(isolated_outputs) -> TestClient:
    return TestClient(app)


def _register_and_complete(client: TestClient, monkeypatch) -> tuple[str, int, int]:
    """Register, finish onboarding without LLM, confirm. Returns email, uid, pid."""
    monkeypatch.setattr(app_settings, "onboarding_allow_finish_without_llm", True)
    email = f"pu_{uuid.uuid4().hex[:12]}@example.com"
    assert client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "P"},
    ).status_code == 200

    for _ in range(3):
        assert client.post("/api/onboarding/job-sample", json={"text": _JD}).status_code == 200
    assert (
        client.post(
            "/api/onboarding/resume",
            files={"file": ("cv.txt", _RESUME.encode("utf-8"), "text/plain")},
        ).status_code
        == 200
    )
    assert client.post("/api/onboarding/finish").status_code == 200
    assert client.post("/api/onboarding/confirm").status_code == 200

    with get_conn() as conn:
        u = get_user_by_email(conn, email)
        assert u and u.active_profile_id
        return email, int(u.id), int(u.active_profile_id)


def test_upload_profile_resume_isolates_to_user_pack(client: TestClient, monkeypatch) -> None:
    _email, uid, pid = _register_and_complete(client, monkeypatch)
    body = (
        "Updated Jane Doe resume\nNebula Labs — Staff Engineer (2024–present)\n"
        "• Built RAG pipeline for resume matching\n" * 8
    )
    res = client.post(
        f"/api/profiles/{pid}/resumes",
        files={"file": ("new_cv.txt", body.encode("utf-8"), "text/plain")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["saved_as"].endswith(".txt")
    assert f"user_profiles/{uid}/{pid}/uploads/" in data["rel_path"].replace("\\", "/")

    disk = Path(app_settings.outputs_path) / data["rel_path"]
    assert disk.is_file()
    assert "Nebula Labs" in disk.read_text(encoding="utf-8")

    listed = client.get(f"/api/profiles/{pid}/resumes")
    assert listed.status_code == 200
    resumes = listed.json()["resumes"]
    assert any(r["kind"] == "profile_resume" for r in resumes)
    assert any(r["original_name"] == "new_cv.txt" for r in resumes)


def test_process_profile_resumes_without_llm(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "onboarding_allow_finish_without_llm", True)
    _email, uid, pid = _register_and_complete(client, monkeypatch)
    body = "Later resume text about Kafka and payments " * 20
    assert (
        client.post(
            f"/api/profiles/{pid}/resumes",
            files={"file": ("later.txt", body.encode("utf-8"), "text/plain")},
        ).status_code
        == 200
    )

    proc = client.post(
        f"/api/profiles/{pid}/resumes/process",
        json={"mode": "merge"},
    )
    assert proc.status_code == 200, proc.text
    out = proc.json()
    assert out["ok"] is True
    assert out["resume_files_read"] >= 1
    assert "profile" in out

    sources = profile_disk_dir(uid, pid) / "profile_upload_sources" / "resumes.txt"
    assert sources.is_file()
    assert "Kafka" in sources.read_text(encoding="utf-8")


def test_process_with_llm_updates_truth_model(client: TestClient, monkeypatch) -> None:
    import app.services.llm as llm_mod

    _email, uid, pid = _register_and_complete(client, monkeypatch)

    fake_truth = {
        "schema_version": 2,
        "candidate": {
            "preferred_name": "Jane Doe",
            "headline": "Staff Engineer",
            "years_experience": 8,
            "skills": {"languages": ["Python"]},
        },
        "profile_layers": {
            "verified_facts": [],
            "inferred_profile": [],
            "user_preferences": {"tone": "concise"},
        },
        "roles": [
            {
                "id": "nebula_staff",
                "company": "Nebula Labs",
                "title": "Staff Engineer",
                "start": "2024-01",
                "end": None,
                "is_current": True,
                "achievements": [
                    {
                        "id": "ach_rag",
                        "text": "Built RAG pipeline for resume matching",
                        "status": "verified",
                        "evidence_source": "new_cv.txt",
                        "confidence": 0.9,
                        "technologies": ["Python"],
                    }
                ],
                "core_facts": ["Built RAG pipeline for resume matching"],
                "tech": ["Python"],
                "themes": ["platform"],
            }
        ],
    }

    def fake_complete_json(*_a, **_k):
        return {"master_truth_model": fake_truth, "story_bank": []}

    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    monkeypatch.setattr(llm_mod, "complete_json", fake_complete_json)
    monkeypatch.setattr(llm_mod, "embed_texts", lambda texts: [[0.1] * 4 for _ in texts])

    body = (
        "Jane Doe\nStaff Engineer\nNebula Labs (2024–present)\n"
        "• Built RAG pipeline for resume matching\n" * 6
    )
    assert (
        client.post(
            f"/api/profiles/{pid}/resumes",
            files={"file": ("new_cv.txt", body.encode("utf-8"), "text/plain")},
        ).status_code
        == 200
    )

    proc = client.post(f"/api/profiles/{pid}/resumes/process", json={"mode": "merge"})
    assert proc.status_code == 200, proc.text
    out = proc.json()
    assert out["ok"] is True
    assert out["profile"]["has_roles"] is True
    assert any(r.get("company") == "Nebula Labs" for r in out["profile"]["roles"])

    truth_path = profile_disk_dir(uid, pid) / "master_truth_model.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert truth["roles"][0]["company"] == "Nebula Labs"
    # user_preferences preserved from fake merge helper path via existing empty prefs —
    # seed may be empty; ensure roles wrote.
    assert truth["roles"][0]["achievements"][0]["evidence_source"] == "new_cv.txt"
    assert out["chunks_written"] > 0


def test_cannot_upload_to_other_users_profile(client: TestClient, monkeypatch) -> None:
    _email_a, _uid_a, pid_a = _register_and_complete(client, monkeypatch)
    client.post("/api/auth/logout")

    email_b = f"pu2_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/api/auth/register",
        json={"email": email_b, "password": "password123", "display_name": "B"},
    ).status_code == 200
    with get_conn() as conn:
        mark_onboarding_complete(conn, get_user_by_email(conn, email_b).id)

    res = client.post(
        f"/api/profiles/{pid_a}/resumes",
        files={"file": ("steal.txt", b"secret", "text/plain")},
    )
    assert res.status_code == 404


def test_default_workspace_cannot_upload_profile_resume(client: TestClient) -> None:
    client.post("/api/auth/logout")
    res = client.post(
        "/api/profiles/1/resumes",
        files={"file": ("cv.txt", b"hello world resume text", "text/plain")},
    )
    assert res.status_code in (403, 404)


def test_upload_rejects_pdf(client: TestClient, monkeypatch) -> None:
    _email, _uid, pid = _register_and_complete(client, monkeypatch)
    res = client.post(
        f"/api/profiles/{pid}/resumes",
        files={"file": ("cv.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res.status_code == 400


def test_profile_resume_kind_included_in_rel_prefix() -> None:
    rel = profile_upload_rel_prefix(3, 3)
    assert rel.replace("\\", "/") == "user_profiles/3/3/uploads"
