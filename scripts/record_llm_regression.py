"""Record `llm_mock_return` and `expect` blocks for offline regression cases.

Requires OPENAI_API_KEY. Calls the real model once per case, captures the raw
JSON from `complete_json`, and the final handler output after guardrails.

Usage:
    set OPENAI_API_KEY=...
    python scripts/record_llm_regression.py
    python scripts/record_llm_regression.py --case rewrite_bullets_identity

After recording, commit updated tests/llm_regression/cases/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from app.packaging import llm_cover_letter as llm_cover_letter_mod  # noqa: E402
from app.packaging.llm_cover_letter import rewrite_cover_letter  # noqa: E402
from app.services import llm as llm_mod  # noqa: E402
from app.services import llm_rewrite as llm_rewrite_mod  # noqa: E402
from app.services.llm_rewrite import rewrite_bullets, rewrite_summary  # noqa: E402

from tests.llm_regression.loader import CASES_DIR, SCHEMA_VERSION, load_cases  # noqa: E402

HANDLERS: Dict[str, Callable[..., Any]] = {
    "rewrite_bullets": rewrite_bullets,
    "rewrite_summary": rewrite_summary,
    "rewrite_cover_letter": rewrite_cover_letter,
}


def _record_one(case: Dict[str, Any]) -> Dict[str, Any]:
    captured: List[Any] = []

    orig = llm_mod.complete_json

    def capturing(*args: Any, **kwargs: Any) -> Any:
        out = orig(*args, **kwargs)
        captured.append(out)
        return out

    llm_mod.complete_json = capturing  # type: ignore[method-assign]
    llm_rewrite_mod.complete_json = capturing  # type: ignore[method-assign]
    llm_cover_letter_mod.complete_json = capturing  # type: ignore[method-assign]
    try:
        handler = case["handler"]
        fn = HANDLERS[handler]
        result = fn(**dict(case["kwargs"]))
    finally:
        llm_mod.complete_json = orig  # type: ignore[method-assign]
        llm_rewrite_mod.complete_json = orig  # type: ignore[method-assign]
        llm_cover_letter_mod.complete_json = orig  # type: ignore[method-assign]

    raw = captured[0] if captured else None
    out = dict(case)
    out["llm_mock_return"] = raw
    exp = dict(case.get("expect") or {})

    if handler == "rewrite_bullets":
        exp["final_bullets"] = result
    elif handler == "rewrite_summary":
        exp["final_summary"] = result
    elif handler == "rewrite_cover_letter":
        exp["final_cover_letter"] = result
    out["expect"] = exp
    out["schema_version"] = SCHEMA_VERSION
    out.pop("_path", None)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", help="Only record this case id")
    args = p.parse_args()

    if not llm_mod.is_available():
        print("Set OPENAI_API_KEY to record.", file=sys.stderr)
        return 1

    cases = load_cases(case_id=args.case)
    if not cases:
        print("No cases found.", file=sys.stderr)
        return 1

    for case in cases:
        path = Path(case["_path"])
        print(f"Recording {case['id']} via live API …")
        updated = _record_one(case)
        path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  wrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
