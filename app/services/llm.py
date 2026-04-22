"""Thin OpenAI wrapper.

Goals:
- Single place to build a client, pick the model, and catch errors so every
  caller can fall back cleanly.
- Lazy: if `OPENAI_API_KEY` isn't set, `is_available()` is False and no
  network call is ever made. Tests stay offline by default.
- Model-agnostic: uses the modern `client.chat.completions.create` surface
  which the installed `openai>=1.x` SDK supports across model families.

Anything that depends on the LLM must treat `complete_json` / `complete_text`
as best-effort — callers should always have a deterministic fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_client = None
_client_init_error: Optional[str] = None


def is_available() -> bool:
    return bool(settings.openai_api_key)


def _get_client():
    global _client, _client_init_error
    if _client is not None or _client_init_error is not None:
        return _client
    try:
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)
    except Exception as e:  # pragma: no cover - import/runtime edge cases
        _client_init_error = str(e)
        logger.warning("OpenAI client init failed: %s", e)
        _client = None
    return _client


def complete_text(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 800,
    temperature: float = 0.3,
    model: Optional[str] = None,
) -> Optional[str]:
    """Return the model's text response, or None if the call fails."""
    if not is_available():
        return None
    client = _get_client()
    if client is None:
        return None
    model_name = model or settings.model_name
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except TypeError:
        # Older SDKs / models may not accept max_completion_tokens; fall back.
        try:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return (resp.choices[0].message.content or "").strip() or None
        except Exception as e:  # pragma: no cover
            logger.warning("LLM call failed (fallback): %s", e)
            return None
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def complete_json(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 1200,
    temperature: float = 0.3,
    model: Optional[str] = None,
) -> Optional[Any]:
    """Ask the model for a JSON response and parse it. Returns None on any failure."""
    raw = complete_text(
        system_prompt,
        user_prompt + "\n\nReturn ONLY valid JSON. No prose, no markdown fences.",
        max_tokens=max_tokens,
        temperature=temperature,
        model=model,
    )
    if not raw:
        return None
    text = raw.strip()
    # Tolerate a model that fenced the JSON despite instructions.
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("LLM returned non-JSON payload: %s", e)
        return None


__all__ = ["is_available", "complete_text", "complete_json"]
