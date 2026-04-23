"""Request-scoped candidate data directory.

Shared archetypes / training data always load from the repo `data/`
tree. Candidate-specific JSON (`master_truth_model.json`,
`story_bank.json`, `application_answer_bank.json`) load from the
active resume profile directory, which defaults to the repo `data/`
folder for the built-in owner workspace.

HTTP middleware sets the context from the signed-in user's active
profile; CLI / tests leave it unset so `effective_candidate_data_dir()`
falls back to the repo `data/` directory.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE_DATA_DIR: Path = _REPO_ROOT / "data"

_candidate_dir: ContextVar[Optional[Path]] = ContextVar("candidate_data_dir", default=None)


def set_candidate_data_dir(path: Optional[Path]) -> None:
    """Set the directory containing profile JSON files for this context."""
    _candidate_dir.set(path)


def push_candidate_dir(path: Optional[Path]):
    """Return a token for `reset_candidate_token` (async middleware)."""
    return _candidate_dir.set(path)


def reset_candidate_token(token) -> None:
    _candidate_dir.reset(token)


def get_candidate_data_dir() -> Path:
    """Resolved candidate data root (never None)."""
    p = _candidate_dir.get()
    return p if p is not None else DEFAULT_CANDIDATE_DATA_DIR


@contextmanager
def candidate_data_dir(path: Optional[Path]) -> Iterator[None]:
    token = _candidate_dir.set(path)
    try:
        yield
    finally:
        _candidate_dir.reset(token)


__all__ = [
    "DEFAULT_CANDIDATE_DATA_DIR",
    "candidate_data_dir",
    "get_candidate_data_dir",
    "push_candidate_dir",
    "reset_candidate_token",
    "set_candidate_data_dir",
]
