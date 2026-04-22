import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

def load_json(relative_path: str):
    path = DATA_DIR / relative_path
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_truth_model():
    return load_json("master_truth_model.json")

def load_archetypes():
    return load_json("archetypes/archetypes.json")

def load_story_bank():
    return load_json("story_bank.json")

def load_answer_bank():
    return load_json("application_answer_bank.json")

def load_classification_examples():
    return load_json("training/classification_examples.json")

def load_rewrite_examples():
    return load_json("training/rewrite_examples.json")
