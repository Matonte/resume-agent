"""Optional daily scrape/tailor loop tied to the web server process.

When ``DAILY_RUN_WITH_SERVER=1``, a background thread invokes ``run_daily`` on a
fixed interval **only while uvicorn is running**. If you use this, **disable**
any second scheduler that also launches ``daily_run`` (host cron, Kubernetes
CronJob, Windows Task Scheduler, etc.) — otherwise both will fire.

Use **uvicorn --workers 1** when this is enabled (multiple workers would start
multiple schedulers).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Avoid hammering scrapers / LLM if misconfigured; tests may monkeypatch lower.
_MIN_EMBEDDED_INTERVAL_SEC = 300

_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None
_run_lock = threading.Lock()


def _invoke_daily_run() -> None:
    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "embedded daily_run skipped: previous run still in progress "
            "(consider raising DAILY_RUN_EMBEDDED_INTERVAL_SECONDS)"
        )
        return
    try:
        from app.jobs.runner import run_daily

        summary = run_daily(send_email=True, use_llm=True, check_auth=True)
        logger.info(
            "embedded daily_run finished run_id=%s scraped=%s kept=%s "
            "email_sent=%s errors=%d",
            summary.run_id,
            summary.scraped,
            summary.kept,
            summary.email_sent,
            len(summary.errors),
        )
        for err in summary.errors:
            logger.warning("embedded daily_run error: %s", err)
    except Exception:  # noqa: BLE001
        logger.exception("embedded daily_run crashed")
    finally:
        _run_lock.release()


def _loop(stop_event: threading.Event, interval_sec: int) -> None:
    logger.info(
        "embedded daily_run scheduler running (interval=%ss); "
        "disable any external scheduler that also runs daily_run to avoid duplicates",
        interval_sec,
    )
    while True:
        if stop_event.wait(timeout=interval_sec):
            logger.info("embedded daily_run scheduler stopped")
            return
        _invoke_daily_run()


def start_embedded_daily_run_scheduler() -> None:
    """Start background scheduler if ``settings.daily_run_with_server``."""
    global _thread, _stop_event

    if not settings.daily_run_with_server:
        return
    if _thread is not None and _thread.is_alive():
        return

    interval = max(_MIN_EMBEDDED_INTERVAL_SEC, int(settings.daily_run_embedded_interval_seconds))
    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_loop,
        args=(_stop_event, interval),
        name="resume-agent-embedded-daily-run",
        daemon=True,
    )
    _thread.start()


def stop_embedded_daily_run_scheduler() -> None:
    """Signal the scheduler thread to exit and wait briefly."""
    global _thread, _stop_event

    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=35)
        _thread = None
        _stop_event = None


__all__ = [
    "start_embedded_daily_run_scheduler",
    "stop_embedded_daily_run_scheduler",
]
