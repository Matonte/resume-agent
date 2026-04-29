"""One-time interactive login helper.

Usage:
    python scripts/login_once.py linkedin
    python scripts/login_once.py wttj
    python scripts/login_once.py jobright
    python scripts/login_once.py linkedin --sso   # org account: SSO only, no password

Opens a visible Playwright window pointed at the site's sign-in page and
blocks until you press Enter in the terminal. Session data persists under
`.playwright/profile-<site>/` or your `LINKEDIN_PROFILE_DIR` / Edge user-data
dir when configured.

Many employers enforce SSO (Sign in with Microsoft / Google / Okta). Those
flows are not supported by email/password pre-fill—use `--sso` (or
`--no-autofill`) and complete SSO in the browser yourself, then press Enter.

Run once per site after pulling the repo (or after a site signs you out).
Credentials in `.env` are optional and only used to pre-fill classic
username/password forms.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Allow running this file directly (`python scripts/login_once.py`) without
# having to set PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings  # noqa: E402
from app.scrapers.playwright_session import SUPPORTED_SITES, launch_for_login  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/login_once.py",
        description="Open a Playwright window so you can log into a job site once.",
    )
    parser.add_argument("site", choices=sorted(SUPPORTED_SITES))
    parser.add_argument(
        "--no-autofill",
        action="store_true",
        help="Don't pre-fill the form from .env even if credentials are set.",
    )
    parser.add_argument(
        "--sso",
        action="store_true",
        help=(
            "Skip password pre-fill for SSO-only accounts: use Microsoft/Google/"
            "Okta in the browser, then press Enter here when you're logged in."
        ),
    )
    args = parser.parse_args(argv)

    skip_autofill = args.no_autofill or args.sso
    email, password = ("", "")
    if not skip_autofill:
        email, password = settings.site_credentials(args.site)
        if email or password:
            print(
                f"[{args.site}] Pre-filling credentials from .env "
                f"({args.site.upper()}_EMAIL / {args.site.upper()}_PASSWORD).\n"
                f"    If this account is SSO-only, cancel and re-run with --sso."
            )
        else:
            print(
                f"[{args.site}] No credentials in .env; you'll type them into the browser."
            )
    elif args.sso:
        print(
            f"[{args.site}] SSO mode: click your org's 'Sign in with …' button "
            "and finish in the browser. .env passwords are not used."
        )
    else:
        print(f"[{args.site}] Auto-fill disabled; sign in manually in the browser.")

    try:
        launch_for_login(args.site, email=email, password=password)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"[{args.site}] Profile saved. You shouldn't need to do this again until the site logs you out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
