"""Archetype DOCX templates: persist uploads in SQLite and drop on-disk copies."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.config import settings
from app.storage.archetype_templates import (
    SOURCE_RESUMES_DIR,
    delete_disk_template,
    expected_template_filenames,
    list_disk_template_filenames,
    list_stored_template_filenames,
    normalize_storage_filename,
    upsert_archetype_docx,
)
from app.storage.db import get_conn

router = APIRouter(prefix="/api/archetype-templates", tags=["archetype-templates"])

MAX_DOCX_BYTES = 15 * 1024 * 1024


def _require_workspace_owner(request: Request) -> None:
    uid = int(request.session.get("user_id", settings.default_user_id))
    if uid != settings.default_user_id:
        raise HTTPException(
            status_code=403,
            detail="Only the default workspace user can upload archetype DOCX templates.",
        )


@router.get("/")
def list_archetype_templates() -> dict[str, Any]:
    with get_conn() as conn:
        stored = list_stored_template_filenames(conn)
    return {
        "expected_filenames": sorted(expected_template_filenames()),
        "stored_in_database": stored,
        "on_disk": list_disk_template_filenames(),
        "source_resumes_dir": str(SOURCE_RESUMES_DIR),
    }


@router.post("/upload")
async def upload_archetype_template(
    request: Request,
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
) -> dict[str, Any]:
    _require_workspace_owner(request)
    raw_name = (filename or file.filename or "").strip()
    try:
        fn = normalize_storage_filename(raw_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    allowed = expected_template_filenames()
    if fn not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Filename {fn!r} is not listed as source_resume in "
                f"data/archetypes/archetypes.json. Expected one of: {sorted(allowed)}"
            ),
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > MAX_DOCX_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 15 MB)")
    if data[:2] != b"PK":
        raise HTTPException(status_code=400, detail="not a valid DOCX (zip) file")

    with get_conn() as conn:
        upsert_archetype_docx(conn, fn, data)
    removed = delete_disk_template(fn)

    return {
        "ok": True,
        "filename": fn,
        "byte_size": len(data),
        "removed_from_disk": removed,
    }


__all__ = ["router"]
