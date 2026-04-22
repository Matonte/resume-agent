"""Deterministic fake scraper for development + tests.

Returns realistic but hand-written fintech / distributed-systems JDs
labelled with a fake source id. This lets us exercise the whole daily
pipeline (classify -> tailor -> package -> digest) without Playwright,
real browsers, or any network traffic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from app.scrapers.base import RawJob


_FIXTURES: dict[str, List[dict]] = {
    "linkedin": [
        {
            "external_id": "ln-fintech-payments-01",
            "url": "https://www.linkedin.com/jobs/view/fake-fintech-payments-01/",
            "title": "Senior Backend Engineer, Payments Platform",
            "company": "Ledgerline Payments",
            "location": "New York, NY",
            "salary_raw": "$210k - $250k",
            "jd_full": (
                "We are hiring a Senior Backend Engineer for our Payments Platform. "
                "You will own high-throughput distributed transaction systems on AWS "
                "and Kafka, designing event-driven backend services that handle "
                "entitlements, transaction integrity, and compliance workflows. "
                "Strong background in low-latency APIs, production reliability, and "
                "fintech/regulated environments required."
            ),
        },
        {
            "external_id": "ln-distributed-infra-02",
            "url": "https://www.linkedin.com/jobs/view/fake-distributed-infra-02/",
            "title": "Senior Distributed Systems Engineer",
            "company": "Northwind Cloud",
            "location": "Remote (US)",
            "salary_raw": "$220k - $270k",
            "jd_full": (
                "Build low-latency distributed backend systems under production load. "
                "Focus on concurrency, fault tolerance, resilience engineering, and "
                "performance tuning across event-driven services. Experience with "
                "Kafka, Solace, or similar messaging is a plus."
            ),
        },
    ],
    "wttj": [
        {
            "external_id": "wttj-data-streaming-01",
            "url": "https://www.welcometothejungle.com/companies/riverrun/jobs/fake-data-streaming-01",
            "title": "Staff Backend Engineer, Streaming Platform",
            "company": "Riverrun Data",
            "location": "Jersey City, NJ",
            "salary_raw": "$240k",
            "jd_full": (
                "Design and operate high-volume real-time data platforms serving "
                "analytics workloads. You will architect streaming ingestion pipelines, "
                "tune latency across backend processing services, and improve "
                "observability for production pipelines."
            ),
        },
        {
            "external_id": "wttj-backend-02",
            "url": "https://www.welcometothejungle.com/companies/acmebank/jobs/fake-backend-02",
            "title": "Senior Backend Engineer",
            "company": "Acme Bank",
            "location": "New York, NY",
            "salary_raw": "$200k - $230k",
            "jd_full": (
                "Senior Backend Engineer to work on our financial transactions "
                "backend. Java, Spring Boot, event-driven architecture, Kafka, "
                "Oracle. Auditability and entitlements are first-class concerns."
            ),
        },
    ],
    "jobright": [
        {
            "external_id": "jr-api-platform-01",
            "url": "https://jobright.ai/jobs/fake-api-platform-01",
            "title": "Senior Backend Engineer, API Platform",
            "company": "Helix Fintech",
            "location": "Remote (US)",
            "salary_raw": "$215k",
            "jd_full": (
                "Build reliable, scalable backend services and APIs for our financial "
                "platform. You will own event-driven architecture, observability, and "
                "production performance for distributed backend services across teams."
            ),
        },
    ],
}


class FakeScraper:
    """Canned scraper that ignores queries and returns pre-written JDs."""

    # No persistent profile needed; skip the auth preflight.
    requires_auth = False

    def __init__(self, source: str) -> None:
        self.source = source

    def discover(self, preferences) -> List[RawJob]:
        rows = _FIXTURES.get(self.source, [])
        now = datetime.utcnow()
        out: List[RawJob] = []
        for i, row in enumerate(rows):
            out.append(
                RawJob(
                    source=self.source,
                    url=row["url"],
                    title=row["title"],
                    company=row["company"],
                    jd_full=row["jd_full"],
                    location=row.get("location"),
                    salary_raw=row.get("salary_raw"),
                    external_id=row.get("external_id"),
                    posted_at=now - timedelta(hours=2 * (i + 1)),
                    apply_url=row["url"],
                    raw=dict(row),
                )
            )
        return out
