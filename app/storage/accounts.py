"""Users and resume profiles (swappable candidate JSON packs)."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.services.data_context import DEFAULT_CANDIDATE_DATA_DIR

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(name: str, fallback: str = "profile") -> str:
    s = name.strip().lower().replace(" ", "-")
    s = _SLUG_RE.sub("-", s).strip("-") or fallback
    return s[:48]


USER_PROFILES_ROOT = "user_profiles"

# Files copied into each on-disk profile (candidate-specific).
PROFILE_TEMPLATE_FILES = (
    "master_truth_model.json",
    "story_bank.json",
    "application_answer_bank.json",
)


def profile_disk_dir(user_id: int, profile_id: int) -> Path:
    base = settings.outputs_path / USER_PROFILES_ROOT / str(user_id) / str(profile_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def seed_profile_from_repo_template(dest: Path) -> None:
    """Copy bundled repo `data/` JSON into a new profile folder."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in PROFILE_TEMPLATE_FILES:
        src = DEFAULT_CANDIDATE_DATA_DIR / name
        if not src.is_file():
            raise FileNotFoundError(f"missing template data file: {src}")
        shutil.copy2(src, dest / name)


@dataclass
class User:
    id: int
    email: str
    display_name: str
    password_hash: str
    active_profile_id: Optional[int]
    created_at: datetime
    requires_onboarding: bool = False
    onboarding_completed_at: Optional[datetime] = None


@dataclass
class ResumeProfile:
    id: int
    user_id: int
    name: str
    slug: str
    use_builtin: bool
    candidate_name: str
    candidate_email: str
    rel_storage: Optional[str]

    def effective_candidate_dir(self) -> Optional[Path]:
        """None means use repo `data/` (built-in workspace)."""
        if self.use_builtin:
            return None
        if not self.rel_storage:
            return None
        return settings.outputs_path / self.rel_storage


def _row_user(row: sqlite3.Row) -> User:
    def _bool_col(name: str, default: bool = False) -> bool:
        try:
            return bool(row[name])
        except (KeyError, IndexError):
            return default

    def _opt_ts(name: str) -> Optional[datetime]:
        try:
            raw = row[name]
        except (KeyError, IndexError):
            return None
        if not raw:
            return None
        s = str(raw).strip()
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    def _parse_dt(raw: object) -> datetime:
        if not raw:
            return datetime.utcnow()
        s = str(raw).strip()
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return datetime.utcnow()

    return User(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"] or "",
        password_hash=row["password_hash"] or "",
        active_profile_id=row["active_profile_id"],
        created_at=_parse_dt(row["created_at"]),
        requires_onboarding=_bool_col("requires_onboarding", False),
        onboarding_completed_at=_opt_ts("onboarding_completed_at"),
    )


def _row_profile(row: sqlite3.Row) -> ResumeProfile:
    return ResumeProfile(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        slug=row["slug"],
        use_builtin=bool(row["use_builtin"]),
        candidate_name=row["candidate_name"] or "",
        candidate_email=row["candidate_email"] or "",
        rel_storage=row["rel_storage"],
    )


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[User]:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_user(row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> Optional[User]:
    row = conn.execute(
        "SELECT * FROM users WHERE lower(email) = lower(?)", (email.strip(),)
    ).fetchone()
    return _row_user(row) if row else None


def get_profile(conn: sqlite3.Connection, profile_id: int) -> Optional[ResumeProfile]:
    row = conn.execute("SELECT * FROM resume_profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_profile(row) if row else None


def get_profile_for_user(
    conn: sqlite3.Connection, user_id: int, profile_id: int
) -> Optional[ResumeProfile]:
    row = conn.execute(
        "SELECT * FROM resume_profiles WHERE id = ? AND user_id = ?",
        (profile_id, user_id),
    ).fetchone()
    return _row_profile(row) if row else None


def list_profiles(conn: sqlite3.Connection, user_id: int) -> List[ResumeProfile]:
    rows = conn.execute(
        "SELECT * FROM resume_profiles WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    ).fetchall()
    return [_row_profile(r) for r in rows]


def set_active_profile(conn: sqlite3.Connection, user_id: int, profile_id: int) -> None:
    p = get_profile_for_user(conn, user_id, profile_id)
    if not p:
        raise ValueError("profile not found")
    conn.execute(
        "UPDATE users SET active_profile_id = ? WHERE id = ?",
        (profile_id, user_id),
    )
    conn.commit()


def create_user_with_profile(
    conn: sqlite3.Connection,
    *,
    email: str,
    password_hash: str,
    display_name: str,
) -> tuple[int, int]:
    """Register a new account: user row + first on-disk profile from templates."""
    cur = conn.execute(
        """
        INSERT INTO users (
            email, password_hash, display_name, active_profile_id, requires_onboarding
        )
        VALUES (?, ?, ?, NULL, 1)
        """,
        (email.strip().lower(), password_hash, display_name.strip()),
    )
    user_id = int(cur.lastrowid)
    name = "Primary"
    slug = slugify(name)
    cur = conn.execute(
        """
        INSERT INTO resume_profiles (
            user_id, name, slug, use_builtin, candidate_name, candidate_email, rel_storage
        ) VALUES (?, ?, ?, 0, '', '', '')
        """,
        (user_id, name, slug),
    )
    profile_id = int(cur.lastrowid)
    disk = profile_disk_dir(user_id, profile_id)
    seed_profile_from_repo_template(disk)
    rel = str(Path(USER_PROFILES_ROOT) / str(user_id) / str(profile_id))
    conn.execute(
        "UPDATE resume_profiles SET rel_storage = ? WHERE id = ?",
        (rel, profile_id),
    )
    conn.execute(
        "UPDATE users SET active_profile_id = ? WHERE id = ?",
        (profile_id, user_id),
    )
    conn.commit()
    return user_id, profile_id


def create_extra_profile(conn: sqlite3.Connection, user_id: int, name: str) -> ResumeProfile:
    base_slug = slugify(name, fallback="profile")
    cur = conn.execute(
        """
        INSERT INTO resume_profiles (
            user_id, name, slug, use_builtin, candidate_name, candidate_email, rel_storage
        ) VALUES (?, ?, ?, 0, '', '', '')
        """,
        (user_id, name.strip(), base_slug),
    )
    profile_id = int(cur.lastrowid)
    slug = f"{base_slug}-{profile_id}"
    conn.execute(
        "UPDATE resume_profiles SET slug = ? WHERE id = ?",
        (slug, profile_id),
    )
    disk = profile_disk_dir(user_id, profile_id)
    seed_profile_from_repo_template(disk)
    rel = str(Path(USER_PROFILES_ROOT) / str(user_id) / str(profile_id))
    conn.execute(
        "UPDATE resume_profiles SET rel_storage = ? WHERE id = ?",
        (rel, profile_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM resume_profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_profile(row)


def update_profile_candidate(
    conn: sqlite3.Connection,
    user_id: int,
    profile_id: int,
    *,
    candidate_name: Optional[str] = None,
    candidate_email: Optional[str] = None,
) -> None:
    p = get_profile_for_user(conn, user_id, profile_id)
    if not p:
        raise ValueError("profile not found")
    sets = []
    params: list = []
    if candidate_name is not None:
        sets.append("candidate_name = ?")
        params.append(candidate_name)
    if candidate_email is not None:
        sets.append("candidate_email = ?")
        params.append(candidate_email)
    if not sets:
        return
    params.extend([profile_id, user_id])
    conn.execute(
        f"UPDATE resume_profiles SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
        params,
    )
    conn.commit()


def user_must_complete_onboarding(u: User, *, default_user_id: int = 1) -> bool:
    """New accounts must finish the onboarding wizard before using the app."""
    if u.id == default_user_id:
        return False
    if not u.requires_onboarding:
        return False
    return u.onboarding_completed_at is None


def onboarding_upload_rel_prefix(user_id: int, profile_id: int) -> str:
    return str(Path(USER_PROFILES_ROOT) / str(user_id) / str(profile_id) / "onboarding_uploads")


def ensure_onboarding_upload_dir(user_id: int, profile_id: int) -> Path:
    base = settings.outputs_path / onboarding_upload_rel_prefix(user_id, profile_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def insert_onboarding_asset(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    profile_id: int,
    kind: str,
    rel_path: str,
    original_name: str = "",
    byte_size: int = 0,
    extra_json: Optional[dict] = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO user_onboarding_assets (
            user_id, profile_id, kind, rel_path, original_name, byte_size, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            profile_id,
            kind,
            rel_path,
            original_name,
            byte_size,
            json.dumps(extra_json or {}),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def count_onboarding_assets(conn: sqlite3.Connection, user_id: int, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM user_onboarding_assets WHERE user_id = ? AND kind = ?",
        (user_id, kind),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def mark_onboarding_complete(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute(
        "UPDATE users SET onboarding_completed_at = datetime('now') WHERE id = ?",
        (user_id,),
    )
    conn.commit()


__all__ = [
    "PROFILE_TEMPLATE_FILES",
    "USER_PROFILES_ROOT",
    "ResumeProfile",
    "User",
    "create_extra_profile",
    "create_user_with_profile",
    "ensure_onboarding_upload_dir",
    "get_profile",
    "get_profile_for_user",
    "get_user_by_email",
    "get_user_by_id",
    "insert_onboarding_asset",
    "list_profiles",
    "onboarding_upload_rel_prefix",
    "profile_disk_dir",
    "count_onboarding_assets",
    "mark_onboarding_complete",
    "seed_profile_from_repo_template",
    "set_active_profile",
    "slugify",
    "update_profile_candidate",
    "user_must_complete_onboarding",
]
