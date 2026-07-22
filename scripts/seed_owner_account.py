#!/usr/bin/env python3
"""Create (or refresh) an owner account and encapsulate repo candidate data.

Copies ``data/master_truth_model.json``, story/answer banks, preferences, and
``data/source_resumes/`` into the user's on-disk profile under
``OUTPUTS_DIR/user_profiles/<uid>/<pid>/``.

Usage (inside the app container or with DATABASE_URL set)::

    python scripts/seed_owner_account.py \\
      --email matonte3@gmail.com \\
      --password '...' \\
      --display-name 'Bill Matonte'

Idempotent: if the email already exists, refreshes the active profile pack and
password (when --password is given).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth.passwords import hash_password  # noqa: E402
from app.storage.accounts import (  # noqa: E402
    create_user_with_profile,
    get_profile,
    get_user_by_email,
    mark_onboarding_complete,
    profile_disk_dir,
    seed_profile_from_repo_candidate_pack,
    update_profile_candidate,
)
from app.storage.db import get_conn, init_db  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    p.add_argument("--password", default="", help="Set/reset login password")
    p.add_argument("--display-name", default="Bill Matonte")
    p.add_argument(
        "--repo-data",
        type=Path,
        default=ROOT / "data",
        help="Source directory for candidate JSON + source_resumes",
    )
    args = p.parse_args()

    email = args.email.strip().lower()
    init_db()

    with get_conn() as conn:
        existing = get_user_by_email(conn, email)
        if existing:
            user_id = existing.id
            profile_id = int(existing.active_profile_id or 0)
            if not profile_id:
                raise SystemExit(f"user {email} has no active_profile_id")
            if args.password:
                conn.execute(
                    "UPDATE users SET password_hash = ?, display_name = ? WHERE id = ?",
                    (hash_password(args.password), args.display_name.strip(), user_id),
                )
                conn.commit()
            print(f"refreshed existing user id={user_id} profile_id={profile_id}")
        else:
            if not args.password or len(args.password) < 8:
                raise SystemExit("--password required (≥8 chars) for new accounts")
            user_id, profile_id = create_user_with_profile(
                conn,
                email=email,
                password_hash=hash_password(args.password),
                display_name=args.display_name,
            )
            print(f"created user id={user_id} profile_id={profile_id}")

        disk = profile_disk_dir(user_id, profile_id)
        written = seed_profile_from_repo_candidate_pack(
            disk, repo_data=args.repo_data, copy_source_resumes=True
        )
        # Pull contact fields from truth model into profile row.
        truth_path = disk / "master_truth_model.json"
        cand_name = args.display_name
        cand_email = email
        if truth_path.is_file():
            try:
                truth = json.loads(truth_path.read_text(encoding="utf-8"))
                c = truth.get("candidate") or {}
                cand_name = (c.get("preferred_name") or cand_name).strip() or cand_name
                cand_email = (c.get("email") or cand_email).strip() or cand_email
            except Exception:
                pass
        update_profile_candidate(
            conn,
            user_id,
            profile_id,
            candidate_name=cand_name,
            candidate_email=cand_email,
        )
        mark_onboarding_complete(conn, user_id)
        prof = get_profile(conn, profile_id)

    print(
        json.dumps(
            {
                "user_id": user_id,
                "profile_id": profile_id,
                "email": email,
                "display_name": args.display_name,
                "rel_storage": prof.rel_storage if prof else None,
                "disk": str(disk),
                "written": written,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
