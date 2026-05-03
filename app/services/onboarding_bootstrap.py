"""Turn onboarding uploads into profile JSON (master_truth_model, story_bank)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document

from app.config import settings
from app.services import llm as llm_mod

logger = logging.getLogger(__name__)


def read_resume_file(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".docx":
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if (p.text or "").strip())
    return path.read_text(encoding="utf-8", errors="replace")


def load_upload_texts_for_user(conn, user_id: int) -> Tuple[List[str], List[str]]:
    """Read text from all onboarding asset files for this user."""
    rows = conn.execute(
        """
        SELECT kind, rel_path FROM user_onboarding_assets
        WHERE user_id = ? ORDER BY id ASC
        """,
        (user_id,),
    ).fetchall()
    root = settings.outputs_path
    resumes: List[str] = []
    jobs: List[str] = []
    for row in rows:
        rel = row["rel_path"]
        kind = row["kind"]
        path = root / rel
        if not path.is_file():
            logger.warning("missing onboarding asset file: %s", path)
            continue
        try:
            if kind == "resume":
                resumes.append(read_resume_file(path))
            elif kind == "job_sample":
                jobs.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            logger.warning("failed to read onboarding asset %s: %s", path, e)
    return resumes, jobs


def merge_onboarding_profile(
    *,
    profile_dir: Path,
    resume_texts: List[str],
    job_sample_texts: List[str],
) -> Tuple[bool, str]:
    """Write `master_truth_model.json` and `story_bank.json` under ``profile_dir``.

    Returns ``(ok, user_visible_message)``.
    """
    truth_path = profile_dir / "master_truth_model.json"
    story_path = profile_dir / "story_bank.json"
    if not truth_path.is_file():
        return False, "Profile folder is missing master_truth_model.json"

    template_truth: Dict[str, Any] = json.loads(
        truth_path.read_text(encoding="utf-8")
    )
    template_story: List[Any] = []
    if story_path.is_file():
        template_story = json.loads(story_path.read_text(encoding="utf-8"))

    if llm_mod.is_available():
        merged = _llm_build_truth_and_stories(
            template_truth=template_truth,
            template_story=template_story,
            resume_blob="\n\n---RESUME_BREAK---\n\n".join(resume_texts)[:14000],
            job_blob="\n\n---JD_BREAK---\n\n".join(job_sample_texts)[:14000],
        )
        if not merged:
            return (
                False,
                "Could not generate profile JSON from the LLM. Check OPENAI_API_KEY and try again.",
            )
        truth = merged.get("master_truth_model")
        stories = merged.get("story_bank")
        if not isinstance(truth, dict) or not truth.get("roles"):
            return False, "LLM output was missing roles; try again with a clearer résumé."
        if not isinstance(stories, list):
            stories = template_story
        truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
        story_path.write_text(json.dumps(stories, indent=2), encoding="utf-8")
        return True, "Saved your profile from the résumé and job samples."

    if settings.onboarding_allow_finish_without_llm:
        raw_dir = profile_dir / "onboarding_sources"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "resumes.txt").write_text(
            "\n\n---\n\n".join(resume_texts), encoding="utf-8"
        )
        (raw_dir / "job_samples.txt").write_text(
            "\n\n---\n\n".join(job_sample_texts), encoding="utf-8"
        )
        return (
            True,
            "Saved raw text under onboarding_sources/ (no LLM). "
            "Set OPENAI_API_KEY and use Finish again, or edit JSON by hand.",
        )

    return (
        False,
        "OpenAI is not configured. Set OPENAI_API_KEY to generate your profile, "
        "or set ONBOARDING_ALLOW_FINISH_WITHOUT_LLM=1 for local dev without generation.",
    )


def _llm_build_truth_and_stories(
    *,
    template_truth: Dict[str, Any],
    template_story: List[Any],
    resume_blob: str,
    job_blob: str,
) -> Optional[Dict[str, Any]]:
    system = (
        "You build resume-agent JSON used for tailoring. "
        "Use ONLY employers, titles, dates, metrics, tools, and projects that appear in the résumé text. "
        "Job posting samples may guide skills emphasis, themes, and story angles — never invent employers "
        "or roles not supported by the résumé. "
        "Return one JSON object with exactly two keys: "
        '"master_truth_model" and "story_bank". '
        "master_truth_model must include candidate (with preferred_name, skills buckets as in typical resumes) "
        "and roles[]; each role: company, title, location, start, end, is_current, "
        "core_facts (4–8 outcome bullets), tech[], themes[], optional signature_project. "
        "story_bank is an array of {id, title, summary, situation, task, actions, results, tags, best_for} "
        "derived from real résumé content; ids like slug_lowercase."
    )
    user = json.dumps(
        {
            "template_truth_top_keys": list(template_truth.keys()),
            "template_story_count": len(template_story),
            "resume_text": resume_blob,
            "job_samples": job_blob,
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        return llm_mod.complete_json(
            system,
            user,
            max_tokens=12000,
            temperature=0.25,
        )
    except Exception:  # noqa: BLE001
        logger.exception("onboarding LLM merge failed")
        return None


__all__ = [
    "load_upload_texts_for_user",
    "merge_onboarding_profile",
    "read_resume_file",
]
