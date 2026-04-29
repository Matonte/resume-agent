"""Load JSON case files for LLM regression."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

CASES_DIR = Path(__file__).resolve().parent / "cases"
SCHEMA_VERSION = 1


def load_cases(*, case_id: str | None = None) -> List[Dict[str, Any]]:
    if not CASES_DIR.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{path}: unsupported schema_version {data.get('schema_version')}")
        cid = data.get("id", path.stem)
        data["_path"] = str(path)
        if case_id is not None and cid != case_id:
            continue
        out.append(data)
    return out
