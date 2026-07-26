"""Turn onboarding uploads into profile JSON (master_truth_model, story_bank).

Merged content must come **only** from the user's uploaded résumés and job samples —
never from another tenant's profile or the repo owner's bundled ``data/`` workspace.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document

from app.config import settings
from app.services import llm as llm_mod
from app.services.evidence_schema import SCHEMA_VERSION, normalize_truth_model

logger = logging.getLogger(__name__)


def read_resume_file(path: Path) -> str:
    """Extract plain text from a résumé file (.docx, .txt, or .pdf)."""
    suf = path.suffix.lower()
    if suf == ".docx":
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if (p.text or "").strip())
    if suf == ".pdf":
        return _read_pdf_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PDF support requires the pypdf package. Install requirements.txt."
        ) from exc
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not open PDF: {exc}") from exc
    parts: List[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        chunk = text.strip()
        if chunk:
            parts.append(chunk)
    joined = "\n\n".join(parts).strip()
    if not joined:
        raise ValueError(
            "No extractable text found in this PDF. "
            "Try a text-based PDF (not a scanned image) or upload .docx / .txt."
        )
    return joined


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


def load_resume_texts_for_profile(conn, profile_id: int) -> List[str]:
    """Read résumé text for a single profile (onboarding + post-onboarding uploads)."""
    rows = conn.execute(
        """
        SELECT kind, rel_path FROM user_onboarding_assets
        WHERE profile_id = ? AND kind IN ('resume', 'profile_resume')
        ORDER BY id ASC
        """,
        (profile_id,),
    ).fetchall()
    root = settings.outputs_path
    resumes: List[str] = []
    for row in rows:
        path = root / row["rel_path"]
        if not path.is_file():
            logger.warning("missing profile résumé asset: %s", path)
            continue
        try:
            text = read_resume_file(path)
            if text.strip():
                resumes.append(text)
        except OSError as e:
            logger.warning("failed to read profile résumé %s: %s", path, e)
    return resumes


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
        truth = normalize_truth_model(truth, default_source="onboarding_resume")
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


def merge_profile_from_resumes(
    *,
    profile_dir: Path,
    resume_texts: List[str],
    mode: str = "merge",
) -> Tuple[bool, str]:
    """Update an existing profile pack from résumé text (post-onboarding).

    ``mode``:
      - ``merge`` (default): keep ``user_confirmed`` facts and preferences; add/update from résumés
      - ``replace``: rebuild truth/stories from résumé text (still uses current JSON as schema template)

    Returns ``(ok, user_visible_message)``.
    """
    truth_path = profile_dir / "master_truth_model.json"
    story_path = profile_dir / "story_bank.json"
    if not truth_path.is_file():
        return False, "Profile folder is missing master_truth_model.json"
    if not resume_texts:
        return False, "No readable résumé text to process."

    mode_norm = (mode or "merge").strip().lower()
    if mode_norm not in {"merge", "replace"}:
        return False, "mode must be 'merge' or 'replace'"

    existing_truth: Dict[str, Any] = json.loads(truth_path.read_text(encoding="utf-8"))
    existing_story: List[Any] = []
    if story_path.is_file():
        try:
            loaded = json.loads(story_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing_story = loaded
        except (OSError, json.JSONDecodeError):
            existing_story = []

    resume_blob = "\n\n---RESUME_BREAK---\n\n".join(resume_texts)[:14000]

    if llm_mod.is_available():
        if mode_norm == "replace":
            merged = _llm_build_truth_and_stories(
                template_truth=existing_truth,
                template_story=existing_story,
                resume_blob=resume_blob,
                job_blob="",
            )
            default_source = "profile_resume"
        else:
            merged = _llm_merge_into_existing_truth(
                existing_truth=existing_truth,
                existing_story=existing_story,
                resume_blob=resume_blob,
            )
            default_source = "profile_resume"
        if not merged:
            return (
                False,
                "Could not update profile JSON from the LLM. Check OPENAI_API_KEY and try again.",
            )
        truth = merged.get("master_truth_model")
        stories = merged.get("story_bank")
        if not isinstance(truth, dict) or not truth.get("roles"):
            return False, "LLM output was missing roles; try again with a clearer résumé."
        if not isinstance(stories, list):
            stories = existing_story
        # Preserve user preferences layer across merges.
        if mode_norm == "merge":
            truth = _preserve_user_layers(existing_truth, truth)
        truth = normalize_truth_model(truth, default_source=default_source)
        truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
        story_path.write_text(json.dumps(stories, indent=2), encoding="utf-8")
        verb = "Replaced" if mode_norm == "replace" else "Merged"
        return True, f"{verb} profile from uploaded résumé(s)."

    if settings.onboarding_allow_finish_without_llm:
        raw_dir = profile_dir / "profile_upload_sources"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "resumes.txt").write_text(
            "\n\n---\n\n".join(resume_texts), encoding="utf-8"
        )
        return (
            True,
            "Saved raw résumé text under profile_upload_sources/ (no LLM). "
            "Set OPENAI_API_KEY and process again to update the truth model.",
        )

    return (
        False,
        "OpenAI is not configured. Set OPENAI_API_KEY to update your profile from résumés, "
        "or set ONBOARDING_ALLOW_FINISH_WITHOUT_LLM=1 for local dev without generation.",
    )


def _preserve_user_layers(
    existing: Dict[str, Any], incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """Keep user_preferences and user_confirmed achievements when merging."""
    out = dict(incoming)
    ex_layers = existing.get("profile_layers") if isinstance(existing.get("profile_layers"), dict) else {}
    in_layers = out.get("profile_layers") if isinstance(out.get("profile_layers"), dict) else {}
    prefs = ex_layers.get("user_preferences")
    if isinstance(prefs, dict):
        out["profile_layers"] = {
            **in_layers,
            "user_preferences": prefs,
            "inferred_profile": in_layers.get("inferred_profile")
            if isinstance(in_layers.get("inferred_profile"), list)
            else ex_layers.get("inferred_profile") or [],
            "verified_facts": in_layers.get("verified_facts")
            if isinstance(in_layers.get("verified_facts"), list)
            else ex_layers.get("verified_facts") or [],
        }

    # Index existing user_confirmed achievements by id / normalized text.
    confirmed: Dict[str, Dict[str, Any]] = {}
    for role in existing.get("roles") or []:
        if not isinstance(role, dict):
            continue
        for ach in role.get("achievements") or []:
            if not isinstance(ach, dict):
                continue
            if str(ach.get("status") or "").strip() != "user_confirmed":
                continue
            key = str(ach.get("id") or "").strip() or str(ach.get("text") or "").strip().lower()
            if key:
                confirmed[key] = ach

    if not confirmed:
        return out

    roles = out.get("roles") if isinstance(out.get("roles"), list) else []
    for role in roles:
        if not isinstance(role, dict):
            continue
        achs = role.get("achievements")
        if not isinstance(achs, list):
            continue
        for i, ach in enumerate(achs):
            if not isinstance(ach, dict):
                continue
            key = str(ach.get("id") or "").strip() or str(ach.get("text") or "").strip().lower()
            prior = confirmed.get(key)
            if prior:
                achs[i] = {**ach, **prior, "status": "user_confirmed"}
    return out


def _llm_merge_into_existing_truth(
    *,
    existing_truth: Dict[str, Any],
    existing_story: List[Any],
    resume_blob: str,
) -> Optional[Dict[str, Any]]:
    system = (
        "You update resume-agent JSON used for tailoring. "
        "Merge NEW résumé text into the EXISTING master_truth_model and story_bank. "
        "Rules: "
        "1) Keep achievements with status user_confirmed unless the résumé clearly contradicts them — "
        "then flag via inferred notes, do not silently drop confirmed text. "
        "2) Preserve profile_layers.user_preferences exactly. "
        "3) Add new employers/roles/achievements only when supported by the résumé text. "
        "4) Update dates, titles, skills, and tech when the résumé is clearer. "
        "5) Do not invent employers, industries, years of experience, or metrics absent from "
        "both existing JSON and résumé. If years_experience is unknown, omit it or leave 0 — never guess. "
        "6) Prefer omitting unclear claims over inventing them; put low-confidence guesses only under "
        "profile_layers.inferred_profile with confidence < 0.55. "
        "Return one JSON object with exactly two keys: "
        '"master_truth_model" and "story_bank". '
        f"master_truth_model.schema_version must be {SCHEMA_VERSION}. "
        "Each role: id (stable slug), company, title, location, start, end, is_current, "
        "achievements (objects with id, text, status verified|inferred|user_confirmed, "
        "evidence_source, confidence, technologies[]), tech[], themes[]. "
        "Also set core_facts to achievement texts as plain strings. "
        "story_bank is an array of {id, title, summary, situation, task, actions, results, tags, best_for}."
    )
    user = json.dumps(
        {
            "mode": "merge",
            "existing_master_truth_model": existing_truth,
            "existing_story_bank": existing_story,
            "resume_text": resume_blob,
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        return llm_mod.complete_json(
            system,
            user,
            max_tokens=12000,
            temperature=0.2,
        )
    except Exception:  # noqa: BLE001
        logger.exception("profile résumé LLM merge failed")
        return None


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
        "Never invent years of experience — set candidate.years_experience only when the résumé states it "
        "(or leave 0 / omit). Never invent industries or employers not supported by the résumé. "
        "Job posting samples may guide skills emphasis, themes, and story angles — never invent employers "
        "or roles not supported by the résumé. "
        "When unsure, omit the claim or put it under profile_layers.inferred_profile with low confidence "
        "instead of writing it as a verified achievement. "
        "Return one JSON object with exactly two keys: "
        '"master_truth_model" and "story_bank". '
        f"master_truth_model.schema_version must be {SCHEMA_VERSION}. "
        "master_truth_model must include candidate (with preferred_name, skills buckets as in typical resumes), "
        "profile_layers: {verified_facts: [], inferred_profile: [], user_preferences: {}}, "
        "and roles[]; each role: id (stable slug), company, title, location, start, end, is_current, "
        "achievements (4–8 objects), tech[], themes[], optional signature_project. "
        "Each achievement MUST be "
        '{id, text, status: "verified"|"inferred", evidence_source, confidence (0-1), technologies[]}. '
        "evidence_source should name which résumé block or filename the claim came from when possible. "
        "Also set core_facts to the same achievement texts as plain strings for compatibility. "
        "Put guesswork (seniority, target roles) only under profile_layers.inferred_profile, never as verified achievements. "
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
    "load_resume_texts_for_profile",
    "load_upload_texts_for_user",
    "merge_onboarding_profile",
    "merge_profile_from_resumes",
    "read_resume_file",
]
