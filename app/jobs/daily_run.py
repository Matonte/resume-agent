"""CLI entrypoint run by Windows Task Scheduler at 9:00 AM.

Usage:
    python -m app.jobs.daily_run
    python -m app.jobs.daily_run --no-email
    python -m app.jobs.daily_run --no-llm
    python -m app.jobs.daily_run --sources jobright,wttj

Exits 0 on success (even with partial errors). Exits 1 only when the run
itself could not start (bad preferences, missing DB, etc.).
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from app.jobs.preferences import Preferences, load_preferences
from app.jobs.runner import RunSummary, run_daily
from app.scrapers.base import Scraper
from app.scrapers.registry import get_scraper


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m app.jobs.daily_run",
        description="Run the daily job-hunt orchestration.",
    )
    p.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending the digest email even if SMTP is configured.",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM polishing (faster, deterministic output).",
    )
    p.add_argument(
        "--sources",
        default=None,
        help=(
            "Comma-separated source ids to run (linkedin,wttj,jobright). "
            "Default: all enabled sources from preferences.yaml."
        ),
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="Force the fake scrapers for every source (offline smoke test).",
    )
    p.add_argument(
        "--skip-auth-check",
        action="store_true",
        help=(
            "Skip the per-site login preflight. The preflight normally opens "
            "each site in a headless browser and drops any source whose "
            "cookie has expired; this flag disables it entirely."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    p.add_argument(
        "--user-id",
        type=int,
        default=None,
        help=(
            "Workspace user id for artifacts + DB scoping "
            "(default: DAILY_RUN_USER_ID env or 1)."
        ),
    )
    return p.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _resolve_scrapers(
    prefs: Preferences,
    *,
    only: Optional[List[str]],
    fake: bool,
) -> List[Scraper]:
    enabled = prefs.enabled_sources()
    if only:
        enabled = [s for s in enabled if s in only]
    return [get_scraper(source, fake=fake) for source in enabled]


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    prefs = load_preferences()
    only = [s.strip() for s in args.sources.split(",")] if args.sources else None

    scrapers = _resolve_scrapers(prefs, only=only, fake=args.fake)

    # Fake scrapers don't need a live login, so --fake implies no preflight.
    check_auth = not (args.skip_auth_check or args.fake)

    summary: RunSummary = run_daily(
        scrapers=scrapers,
        preferences=prefs,
        send_email=not args.no_email,
        use_llm=not args.no_llm,
        check_auth=check_auth,
        user_id=args.user_id,
    )

    print(
        f"daily-run {summary.run_id}: "
        f"scraped={summary.scraped} filtered={summary.filtered} "
        f"tailored={summary.tailored} kept={summary.kept} "
        f"email_sent={summary.email_sent} errors={len(summary.errors)}"
    )
    for err in summary.errors:
        print(f"  - error: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
