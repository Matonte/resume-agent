"""Fit-score tests: ensure the score stays in [0, 10], that a strongly-
aligned JD scores much higher than noise, and that seniority gaps dock points.
"""

from app.services.fit_score import compute_fit_score


def test_score_bounds_empty():
    fit = compute_fit_score("")
    assert 0.0 <= fit.score <= 10.0
    assert fit.band in {"Excellent", "Strong", "OK", "Weak", "Poor"}


def test_strong_fintech_match_is_high():
    jd = (
        "Senior Backend Engineer, Payments Platform. Build financial transaction systems "
        "with auditability, compliance, entitlements, and distributed services for a large bank."
    )
    fit = compute_fit_score(jd)
    assert fit.score >= 6.5, f"expected Strong+ fit, got {fit.score}"


def test_noise_is_low():
    fit = compute_fit_score("Lorem ipsum dolor sit amet consectetur adipiscing elit.")
    assert fit.score <= 5.0, f"expected low fit for noise, got {fit.score}"


def test_excessive_seniority_requirement_docks_points():
    low = compute_fit_score(
        "Distributed systems role, low latency and concurrency."
    )
    high = compute_fit_score(
        "Distributed systems role, low latency and concurrency. 20+ years experience required."
    )
    assert high.score <= low.score, (
        f"20+ years requirement should not raise score: low={low.score}, high={high.score}"
    )


def test_reasons_are_populated():
    fit = compute_fit_score("Kafka streaming pipelines and real-time ingestion")
    assert len(fit.reasons) >= 2
    assert any("archetype" in r.lower() for r in fit.reasons)
