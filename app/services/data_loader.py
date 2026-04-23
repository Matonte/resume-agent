import json
from pathlib import Path

from app.services.data_context import DEFAULT_CANDIDATE_DATA_DIR, get_candidate_data_dir

DATA_DIR: Path = DEFAULT_CANDIDATE_DATA_DIR


def _load_json(root: Path, relative_path: str):
    path = root / relative_path
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_json(relative_path: str, *, shared: bool = False):
    """Load JSON from repo `data/`. When shared=False, use the active
    candidate profile directory (session / middleware)."""
    root = DATA_DIR if shared else get_candidate_data_dir()
    return _load_json(root, relative_path)


def load_truth_model():
    return load_json("master_truth_model.json")


def load_story_bank():
    return load_json("story_bank.json")


def load_answer_bank():
    return load_json("application_answer_bank.json")


def load_archetypes():
    return load_json("archetypes/archetypes.json", shared=True)


def load_classification_examples():
    return load_json("training/classification_examples.json", shared=True)


def load_rewrite_examples():
    return load_json("training/rewrite_examples.json", shared=True)
