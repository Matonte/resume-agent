"""Tests for per-profile résumé RAG chunking and persistence."""

from __future__ import annotations

import json
import uuid

from app.storage.accounts import (
    create_user_with_profile,
    ensure_onboarding_upload_dir,
    insert_onboarding_asset,
    onboarding_upload_rel_prefix,
)
from app.storage.db import get_conn


def test_chunk_text_non_empty() -> None:
    from app.services.resume_rag import chunk_text

    parts = chunk_text("word " * 400, max_chars=80, overlap=10)
    assert len(parts) >= 2
    assert all(len(p) <= 80 for p in parts)


def test_rebuild_and_retrieve_rag(isolated_outputs, monkeypatch) -> None:
    import app.services.llm as llm_mod
    import app.services.resume_rag as rr

    def fake_embed(texts: list[str]):
        # Deterministic "vectors": length scales with text hash so different chunks differ.
        out = []
        for t in texts:
            n = len(t) % 5 + 1
            vec = [float((ord(c) % 7) / 10.0) for c in t[:12]] + [float(n)]
            out.append(vec)
        return out

    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    monkeypatch.setattr(llm_mod, "embed_texts", fake_embed)

    email = f"rag_{uuid.uuid4().hex[:10]}@example.com"
    with get_conn() as conn:
        uid, pid = create_user_with_profile(
            conn,
            email=email,
            password_hash="x",
            display_name="RAG Tester",
        )
        disk = ensure_onboarding_upload_dir(uid, pid)
        cv = disk / "cv.txt"
        long_txt = (
            "Led migration of payment ingestion to Kafka streaming pipelines. "
            * 30
        )
        cv.write_text(long_txt, encoding="utf-8")
        rel = f"{onboarding_upload_rel_prefix(uid, pid)}/{cv.name}"
        insert_onboarding_asset(
            conn,
            user_id=uid,
            profile_id=pid,
            kind="resume",
            rel_path=rel,
            original_name=cv.name,
            byte_size=len(long_txt.encode("utf-8")),
        )

        n = rr.rebuild_profile_rag(conn, pid, uid)
        assert n > 0

        row = conn.execute(
            "SELECT COUNT(*) AS c FROM resume_rag_chunks WHERE profile_id = ?",
            (pid,),
        ).fetchone()
        assert row and int(row["c"]) == n

        blob = rr.retrieve_rag_context(conn, pid, "Kafka streaming payment ingestion")
        assert "Kafka" in blob or "streaming" in blob

        sample = conn.execute(
            "SELECT embedding_json FROM resume_rag_chunks WHERE profile_id = ? LIMIT 1",
            (pid,),
        ).fetchone()
        assert sample
        vec = json.loads(sample["embedding_json"])
        assert isinstance(vec, list)
        assert len(vec) >= 1
