"""Semi-auto apply flow.

Given a `JobRecord` that has already been tailored (`artifact_dir` points
to `resume.docx`, `cover_letter.docx`, and `screening.json`), open a
non-headless Playwright window under the site's persistent profile,
navigate to the apply URL, try to upload the resume + cover letter, and
paste screening answers into matching form fields.

We STOP BEFORE SUBMITTING. The human reviews the filled form and clicks
Submit themselves. This is the single biggest risk-reduction in the
pipeline: the machine never hits "apply" without you.

Runs in a background thread so the HTTP request returns immediately; the
browser window is the user-facing side effect. We spawn one window per
call and do not track it afterwards.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.scrapers.playwright_session import sync_context
from app.storage.db import JobRecord

logger = logging.getLogger(__name__)


# Form fields we always try to match screening answers against. Loose enough
# to catch most application forms' first free-text "tell us about yourself"
# prompt.
_ANSWER_SELECTORS = (
    "textarea",
    "div[contenteditable='true']",
)


def _load_screening(path: Path) -> List[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _fill_files(page, resume: Path, cover: Path) -> None:
    """Find the first file-upload input and feed it the resume + cover letter.
    If the form has two separate inputs, try to split."""
    inputs = page.locator("input[type='file']").element_handles()
    if not inputs:
        logger.info("apply: no file inputs found on %s", page.url)
        return
    if len(inputs) == 1:
        try:
            inputs[0].set_input_files(str(resume))
            logger.info("apply: attached resume to single file input")
        except Exception:  # pragma: no cover
            logger.exception("apply: failed to attach resume")
        return
    try:
        inputs[0].set_input_files(str(resume))
    except Exception:  # pragma: no cover
        logger.exception("apply: failed to attach resume")
    try:
        inputs[1].set_input_files(str(cover))
    except Exception:  # pragma: no cover
        logger.exception("apply: failed to attach cover letter")


def _paste_first_answer(page, answer: str) -> bool:
    """Best-effort: put the first screening answer into the first empty
    textarea on the page. Returns True on success."""
    if not answer:
        return False
    for sel in _ANSWER_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            try:
                loc.fill(answer, timeout=2000)
                return True
            except Exception:
                # contenteditable divs can't take fill(); use type() instead.
                try:
                    loc.click(timeout=1500)
                    page.keyboard.type(answer, delay=5)
                    return True
                except Exception:  # pragma: no cover
                    continue
        except Exception:
            continue
    return False


def _run_apply_window(job: JobRecord) -> None:
    apply_url = (job.apply_url or job.url or "").strip()
    artifact_dir = Path(job.artifact_dir or "")
    resume = artifact_dir / "resume.docx"
    cover = artifact_dir / "cover_letter.docx"
    screening = _load_screening(artifact_dir / "screening.json")

    if not resume.exists():
        logger.error("apply: resume missing at %s", resume)
        return

    try:
        with sync_context(job.source, headless=False) as (_pw, context):
            page = context.new_page()
            page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            _fill_files(page, resume, cover if cover.exists() else resume)
            if screening:
                _paste_first_answer(page, screening[0].get("answer", ""))
            logger.info(
                "apply: form prefilled for %s (%s). Waiting on human submit.",
                job.id, job.title,
            )
            # Keep the window open for up to 60 minutes so the user can review
            # and submit. After that we close the context.
            page.wait_for_timeout(60 * 60 * 1000)
    except Exception:
        logger.exception("apply: Playwright flow failed for %s", job.id)


def prepare_apply(job: JobRecord, *, background: bool = True) -> None:
    """Public entry point called by the dashboard router.

    `background=True` (default) spawns a daemon thread so the HTTP request
    that invoked this returns immediately. Tests can pass `background=False`
    to run synchronously against a mocked `sync_context`."""
    if not job.artifact_dir:
        raise RuntimeError(f"job {job.id} has no artifact_dir; run the daily tailor first")
    if not background:
        _run_apply_window(job)
        return
    thread = threading.Thread(
        target=_run_apply_window, args=(job,), daemon=True, name=f"apply-{job.id}",
    )
    thread.start()


__all__ = ["prepare_apply"]
