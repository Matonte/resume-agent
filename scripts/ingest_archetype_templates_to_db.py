#!/usr/bin/env python3
"""Copy ``data/source_resumes/*.docx`` into ``outputs/jobs.sqlite`` (``archetype_source_docx``).

Optional ``--delete`` removes each file after a successful insert so the repo can run
without checked-in templates once the DB is populated.

Usage (repo root)::

    python scripts/ingest_archetype_templates_to_db.py
    python scripts/ingest_archetype_templates_to_db.py --delete
"""

from __future__ import annotations

import argparse

from app.storage.archetype_templates import ingest_templates_from_disk
from app.storage.db import get_conn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Remove each .docx from data/source_resumes after storing it in SQLite",
    )
    args = parser.parse_args()
    with get_conn() as conn:
        summary = ingest_templates_from_disk(conn, delete_files=args.delete)
    print(summary)


if __name__ == "__main__":
    main()
