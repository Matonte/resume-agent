"""Best-effort parsing of 'Posted X ago' style strings into UTC datetimes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

_REL_RE = re.compile(
    r"(?P<n>\d+)\s*(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago",
    re.IGNORECASE,
)


def parse_relative_posted_at(text: str, *, now: Optional[datetime] = None) -> Optional[datetime]:
    """Return an approximate UTC datetime from phrases like '3 days ago'."""
    if not text:
        return None
    now = now or datetime.utcnow()
    low = text.lower()
    if "just now" in low or "moments ago" in low:
        return now
    m = _REL_RE.search(text)
    if not m:
        return None
    n = int(m.group("n"))
    unit = m.group("unit").lower()
    if unit.startswith("second"):
        delta = timedelta(seconds=n)
    elif unit.startswith("minute"):
        delta = timedelta(minutes=n)
    elif unit.startswith("hour"):
        delta = timedelta(hours=n)
    elif unit.startswith("day"):
        delta = timedelta(days=n)
    elif unit.startswith("week"):
        delta = timedelta(weeks=n)
    elif unit.startswith("month"):
        delta = timedelta(days=30 * n)
    elif unit.startswith("year"):
        delta = timedelta(days=365 * n)
    else:
        return None
    return now - delta
