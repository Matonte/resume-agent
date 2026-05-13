"""Archetype DOCX templates: SQLite blobs preferred over ``data/source_resumes/``.

After templates are uploaded (or ingested), files may be removed from disk;
:class:`~docx.Document` is opened from bytes via ``generate_tailored_resume_bytes``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional, Set

from app.services.data_loader import load_archetypes

_REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RESUMES_DIR = _REPO_ROOT / "data" / "source_resumes"

# Fall back when archetypes.json ``source_resume`` is missing — matches resume_docx legacy logic.
ARCHETYPE_RESUME_PREFIX_MAP = {
    "A_general_ai_platform": "MM_Resume_4_9_26_A",
    "B_fintech_transaction_systems": "MM_Resume_4_9_26_B",
    "C_data_streaming_systems": "MM_Resume_4_9_26_C",
    "D_distributed_systems": "MM_Resume_4_9_26_D",
    "E_staff_backend": "MM_Resume_4_9_26_E",
    "E_core_backend": "MM_Resume_4_9_26_E",
    "E_resume": "MM_Resume_4_9_26_E",
}


def expected_template_filenames() -> Set[str]:
    """Filenames referenced by ``data/archetypes/archetypes.json``."""
    archetypes = load_archetypes()
    out: Set[str] = set()
    for meta in archetypes.values():
        if not isinstance(meta, dict):
            continue
        fn = (meta.get("source_resume") or "").strip()
        if fn:
            out.add(fn)
    return out


def normalize_storage_filename(raw: str) -> str:
    """Single basename, ``.docx``, no path traversal."""
    s = raw.strip()
    if ".." in s or s.startswith(("/", "\\")):
        raise ValueError("invalid filename")
    name = Path(s).name
    if not name.lower().endswith(".docx"):
        raise ValueError("filename must end with .docx")
    if not name:
        raise ValueError("invalid filename")
    return name


def get_archetype_docx_blob(conn: sqlite3.Connection, filename: str) -> Optional[bytes]:
    row = conn.execute(
        "SELECT data FROM archetype_source_docx WHERE filename = ?",
        (filename,),
    ).fetchone()
    if not row or row[0] is None:
        return None
    return bytes(row[0])


def upsert_archetype_docx(conn: sqlite3.Connection, filename: str, data: bytes) -> None:
    conn.execute(
        """
        INSERT INTO archetype_source_docx (filename, data, byte_size, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(filename) DO UPDATE SET
            data = excluded.data,
            byte_size = excluded.byte_size,
            updated_at = datetime('now')
        """,
        (filename, data, len(data)),
    )
    conn.commit()


def list_stored_template_filenames(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT filename FROM archetype_source_docx ORDER BY filename ASC"
    ).fetchall()
    return [str(r[0]) for r in rows]


def list_disk_template_filenames() -> List[str]:
    if not SOURCE_RESUMES_DIR.is_dir():
        return []
    return sorted(p.name for p in SOURCE_RESUMES_DIR.glob("*.docx"))


def delete_disk_template(filename: str) -> bool:
    """Remove ``data/source_resumes/<filename>`` if present. Returns True if a file was deleted."""
    path = SOURCE_RESUMES_DIR / normalize_storage_filename(filename)
    if path.is_file():
        path.unlink()
        return True
    return False


def ordered_template_filenames(archetype_id: str, conn: sqlite3.Connection) -> List[str]:
    """Ordered candidates for DB lookup (basename matching archetypes.json + prefix variants)."""
    archetypes = load_archetypes()
    meta = archetypes.get(archetype_id) or archetypes.get("A_general_ai_platform") or {}
    names: List[str] = []

    fn = (meta.get("source_resume") or "").strip()
    if fn:
        names.append(fn)

    prefix = ARCHETYPE_RESUME_PREFIX_MAP.get(archetype_id)
    if prefix:
        for p in sorted(SOURCE_RESUMES_DIR.glob(f"{prefix}*.docx")):
            names.append(p.name)
        cur = conn.execute(
            """
            SELECT filename FROM archetype_source_docx
            WHERE filename GLOB ?
            ORDER BY filename ASC
            """,
            (prefix + "*",),
        )
        for row in cur.fetchall():
            names.append(str(row[0]))

    seen: Set[str] = set()
    out: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def disk_template_candidate_paths(archetype_id: str) -> List[Path]:
    """On-disk paths to try last (after DB), matching legacy resolver behavior."""
    archetypes = load_archetypes()
    meta = archetypes.get(archetype_id) or archetypes.get("A_general_ai_platform") or {}
    candidates: List[Path] = []
    filename = meta.get("source_resume")
    if filename:
        candidates.append(SOURCE_RESUMES_DIR / filename)

    prefix = ARCHETYPE_RESUME_PREFIX_MAP.get(archetype_id)
    if prefix:
        for p in sorted(SOURCE_RESUMES_DIR.glob(f"{prefix}*.docx")):
            candidates.append(p)

    seen: Set[str] = set()
    out: List[Path] = []
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def ingest_templates_from_disk(conn: sqlite3.Connection, *, delete_files: bool = False) -> dict:
    """Insert every ``*.docx`` under ``data/source_resumes`` into the DB."""
    ingested = 0
    deleted = 0
    if not SOURCE_RESUMES_DIR.is_dir():
        return {"ingested": 0, "deleted_from_disk": 0}
    for path in sorted(SOURCE_RESUMES_DIR.glob("*.docx")):
        data = path.read_bytes()
        upsert_archetype_docx(conn, path.name, data)
        ingested += 1
        if delete_files:
            path.unlink()
            deleted += 1
    return {"ingested": ingested, "deleted_from_disk": deleted}


__all__ = [
    "ARCHETYPE_RESUME_PREFIX_MAP",
    "SOURCE_RESUMES_DIR",
    "delete_disk_template",
    "disk_template_candidate_paths",
    "expected_template_filenames",
    "get_archetype_docx_blob",
    "ingest_templates_from_disk",
    "list_disk_template_filenames",
    "list_stored_template_filenames",
    "normalize_storage_filename",
    "ordered_template_filenames",
    "upsert_archetype_docx",
]
