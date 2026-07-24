"""Archetype template persistence (SQLite) tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.resume_docx import generate_tailored_resume_bytes
from app.storage import archetype_templates as at
from app.storage.archetype_templates import upsert_archetype_docx
from app.storage.db import get_conn

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_B = REPO_ROOT / "data" / "source_resumes" / "MM_Resume_4_9_26_B (1).docx"

JD_SHORT = (
    "Senior Backend Engineer, Payments Platform. Kafka, distributed services."
)


@pytest.fixture
def client(authed_client) -> TestClient:
    return authed_client


def test_list_archetype_templates(client: TestClient) -> None:
    r = client.get("/api/archetype-templates/")
    assert r.status_code == 200
    body = r.json()
    assert "expected_filenames" in body
    assert "stored_in_database" in body
    assert "on_disk" in body
    assert "MM_Resume_4_9_26_B (1).docx" in body["expected_filenames"]


@pytest.mark.skipif(not TEMPLATE_B.is_file(), reason="template DOCX not present")
def test_resume_generates_from_db_when_disk_unavailable(
    isolated_outputs, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(at, "SOURCE_RESUMES_DIR", tmp_path)
    docx_bytes = TEMPLATE_B.read_bytes()
    with get_conn() as conn:
        upsert_archetype_docx(conn, "MM_Resume_4_9_26_B (1).docx", docx_bytes)

    blob = generate_tailored_resume_bytes(
        "B_fintech_transaction_systems",
        JD_SHORT,
    )
    assert blob[:2] == b"PK"


def test_upload_rejects_registered_user(client: TestClient) -> None:
    email = f"t_{uuid.uuid4().hex[:12]}@example.com"
    reg = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": "T",
        },
    )
    assert reg.status_code == 200, reg.text
    fake_docx = b"PK\x03\x04" + b"\x00" * 40
    res = client.post(
        "/api/archetype-templates/upload",
        files={"file": ("MM_Resume_4_9_26_A (3).docx", fake_docx, "application/octet-stream")},
    )
    assert res.status_code == 403


@pytest.mark.skipif(not TEMPLATE_B.is_file(), reason="template DOCX not present")
def test_upload_stores_and_removes_disk_copy(
    isolated_outputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default workspace (anonymous uid 1) can upload when login gate is off."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "require_login", False)
    client = TestClient(app)
    dest_dir = tmp_path / "source_resumes"
    dest_dir.mkdir()
    disk_copy = dest_dir / "MM_Resume_4_9_26_B (1).docx"
    disk_copy.write_bytes(TEMPLATE_B.read_bytes())

    import app.storage.archetype_templates as tm

    prev = tm.SOURCE_RESUMES_DIR
    tm.SOURCE_RESUMES_DIR = dest_dir
    try:
        payload = TEMPLATE_B.read_bytes()
        res = client.post(
            "/api/archetype-templates/upload",
            files={
                "file": (
                    "MM_Resume_4_9_26_B (1).docx",
                    payload,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True
        assert body["removed_from_disk"] is True
        assert not disk_copy.is_file()

        with get_conn() as conn:
            row = conn.execute(
                "SELECT byte_size FROM archetype_source_docx WHERE filename = ?",
                ("MM_Resume_4_9_26_B (1).docx",),
            ).fetchone()
        assert row and int(row[0]) == len(payload)
    finally:
        tm.SOURCE_RESUMES_DIR = prev


def test_normalize_storage_filename_rejects_traversal() -> None:
    from app.storage.archetype_templates import normalize_storage_filename

    with pytest.raises(ValueError):
        normalize_storage_filename("../secrets.docx")
