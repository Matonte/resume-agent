"""Tests for employer name resolution (Unknown -> JD / URL hints)."""

from __future__ import annotations

from app.services.company_resolve import (
    company_hint_from_jd,
    company_hint_from_listing_url,
    is_placeholder_company,
    resolve_company_for_packaging,
)


def test_placeholder_detection() -> None:
    assert is_placeholder_company("Unknown")
    assert is_placeholder_company("UNKNOWN")
    assert is_placeholder_company("")
    assert not is_placeholder_company("Acme Bank")


def test_greenhouse_url() -> None:
    u = "https://boards.greenhouse.io/ledgerline/jobs/12345"
    assert company_hint_from_listing_url(u) == "Ledgerline"


def test_resolve_from_jd_about() -> None:
    jd = "About Ledgerline Payments\n\nWe move money for fintechs.\n\nRole: Engineer"
    assert (
        resolve_company_for_packaging("Unknown", jd, "") == "Ledgerline Payments"
    )


def test_resolve_company_pipe_pattern() -> None:
    jd = "Northwind Labs | Senior Backend Engineer\n\nRemote — US"
    assert resolve_company_for_packaging("", jd, "") == "Northwind Labs"


def test_resolve_keeps_real_company() -> None:
    assert resolve_company_for_packaging("Stripe", "About OtherCo", "") == "Stripe"
