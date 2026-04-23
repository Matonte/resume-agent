"""Unit tests for relative 'posted ago' parsing."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.scrapers.posted_at_heuristic import parse_relative_posted_at


def test_parse_just_now() -> None:
    fixed = datetime(2026, 4, 22, 12, 0, 0)
    assert parse_relative_posted_at("Posted just now", now=fixed) == fixed


def test_parse_days_weeks() -> None:
    fixed = datetime(2026, 4, 22, 12, 0, 0)
    assert parse_relative_posted_at("3 days ago", now=fixed) == fixed - timedelta(days=3)
    assert parse_relative_posted_at("2 weeks ago", now=fixed) == fixed - timedelta(weeks=2)


def test_parse_from_blob() -> None:
    fixed = datetime(2026, 4, 22, 12, 0, 0)
    blob = "Acme · Remote · Reposted 1 week ago · Promoted"
    got = parse_relative_posted_at(blob, now=fixed)
    assert got == fixed - timedelta(weeks=1)
