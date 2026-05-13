"""Per-profile résumé RAG: chunk uploaded assets, embed, retrieve for tailoring."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import List, Sequence, Tuple

from app.config import settings
from app.services import llm
from app.services.onboarding_bootstrap import read_resume_file

logger = logging.getLogger(__name__)

_EMBED_BATCH = 64


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    chunks: List[str] = []
    i = 0
    n = len(t)
    while i < n:
        end = min(n, i + max_chars)
        piece = t[i:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        i = max(i + max_chars - overlap, i + 1)
    return chunks


def delete_chunks_for_profile(conn: sqlite3.Connection, profile_id: int) -> None:
    conn.execute("DELETE FROM resume_rag_chunks WHERE profile_id = ?", (profile_id,))
    conn.commit()


def _list_resume_assets(
    conn: sqlite3.Connection, profile_id: int
) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, rel_path, original_name FROM user_onboarding_assets
        WHERE profile_id = ? AND kind IN ('resume', 'profile_resume')
        ORDER BY id ASC
        """,
        (profile_id,),
    ).fetchall()


def rebuild_profile_rag(conn: sqlite3.Connection, profile_id: int, user_id: int) -> int:
    """Rebuild chunk + embedding rows from onboarding résumé uploads. Returns chunk count."""
    root = settings.outputs_path
    planned: List[Tuple[int, str, int, str]] = []
    for row in _list_resume_assets(conn, profile_id):
        aid = int(row["id"])
        rel = row["rel_path"]
        label = (row["original_name"] or rel or "").strip() or str(aid)
        path = root / rel
        if not path.is_file():
            logger.warning("resume_rag: missing asset file %s", path)
            continue
        try:
            full = read_resume_file(path)
        except OSError as e:
            logger.warning("resume_rag: failed to read %s: %s", path, e)
            continue
        for idx, piece in enumerate(chunk_text(full)):
            planned.append((aid, label, idx, piece))

    if not planned:
        delete_chunks_for_profile(conn, profile_id)
        return 0

    texts = [p[3] for p in planned]
    all_emb: List[List[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        got = llm.embed_texts(batch)
        if got is None:
            logger.warning("resume_rag: embedding failed; leaving existing chunks unchanged")
            return -1
        all_emb.extend(got)

    if len(all_emb) != len(planned):
        logger.warning("resume_rag: embedding count mismatch")
        return -1

    delete_chunks_for_profile(conn, profile_id)
    for (asset_id, label, chunk_idx, piece), emb in zip(planned, all_emb):
        conn.execute(
            """
            INSERT INTO resume_rag_chunks (
                profile_id, user_id, asset_id, chunk_index, label, text, embedding_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                user_id,
                asset_id,
                chunk_idx,
                label,
                piece,
                json.dumps(emb),
            ),
        )
    conn.commit()
    return len(planned)


def retrieve_rag_context(
    conn: sqlite3.Connection,
    profile_id: int,
    query_text: str,
    *,
    top_k: int = 8,
) -> str:
    """Return a formatted excerpt blob for LLM grounding, or empty string."""
    rows = conn.execute(
        "SELECT text, embedding_json FROM resume_rag_chunks WHERE profile_id = ?",
        (profile_id,),
    ).fetchall()
    if not rows:
        return ""

    qemb = llm.embed_texts([(query_text or "").strip()[:8000]])
    if not qemb or len(qemb) != 1:
        return ""

    qv = qemb[0]
    scored: List[Tuple[float, str]] = []
    for row in rows:
        try:
            ev = json.loads(row["embedding_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ev, list):
            continue
        scored.append((_cosine(qv, [float(x) for x in ev]), row["text"]))

    scored.sort(key=lambda t: t[0], reverse=True)
    parts: List[str] = []
    for i, (_, txt) in enumerate(scored[:top_k]):
        parts.append(f"[{i + 1}] {(txt or '').strip()}")
    return "\n\n".join(parts)


__all__ = [
    "chunk_text",
    "delete_chunks_for_profile",
    "rebuild_profile_rag",
    "retrieve_rag_context",
]
