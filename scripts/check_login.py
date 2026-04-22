"""Check whether each site's persistent Playwright profile is still logged in.

Usage:
    python scripts/check_login.py              # probe all three sites
    python scripts/check_login.py linkedin     # just one
    python scripts/check_login.py wttj jobright

Exit codes:
    0 - all probed sites are logged in.
    1 - one or more sites are logged out or errored.
    2 - bad arguments.

For each site we open a headless Playwright browser under
`.playwright/profile-<site>/`, visit that site's "home" URL, and check
whether we got bounced to a sign-in page. Runs fast (a few seconds per
site) and doesn't touch any scrapers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Allow running this file directly (`python scripts/check_login.py`) without
# having to set PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.scrapers.playwright_session import SUPPORTED_SITES, check_login  # noqa: E402

# Ensure non-ASCII URLs / notes don't crash on a cp1252 Windows console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - older Pythons / piped stdout
    pass


_STATUS_GLYPH = {True: "OK  ", False: "FAIL"}


def _format_row(result: dict) -> str:
    site = result["site"]
    if result.get("error"):
        glyph = "ERR "
        extra = result["error"]
    else:
        glyph = _STATUS_GLYPH[bool(result.get("logged_in"))]
        extra = result.get("notes") or ""
    final = result.get("final_url") or "-"
    return f"  [{glyph}] {site:<9} final_url={final}\n          {extra}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/check_login.py",
        description="Probe each site's persistent Playwright profile to see whether it's still logged in.",
    )
    parser.add_argument(
        "sites",
        nargs="*",
        choices=sorted(SUPPORTED_SITES),
        help=f"Specific sites to check (default: all of {sorted(SUPPORTED_SITES)}).",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Open a visible browser window so you can see what the probe sees.",
    )
    args = parser.parse_args(argv)

    sites = list(args.sites) if args.sites else sorted(SUPPORTED_SITES)
    print(f"\nChecking {len(sites)} site(s): {', '.join(sites)}\n")

    any_fail = False
    for site in sites:
        try:
            result = check_login(site, headless=not args.visible)
        except Exception as exc:  # noqa: BLE001
            result = {
                "site": site,
                "logged_in": False,
                "error": f"{type(exc).__name__}: {exc}",
                "final_url": None,
                "notes": "check_login raised",
            }
        print(_format_row(result))
        if not result.get("logged_in") or result.get("error"):
            any_fail = True

    if any_fail:
        print(
            "\nAt least one site is not usable. Re-run "
            "`python scripts/login_once.py <site>` for anything flagged FAIL or ERR."
        )
        return 1
    print("\nAll checked sites look logged in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
