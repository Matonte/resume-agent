import json
from pathlib import Path

data_dir = Path(__file__).resolve().parents[1] / "data"
truth = json.loads((data_dir / "master_truth_model.json").read_text())
archetypes = json.loads((data_dir / "archetypes" / "archetypes.json").read_text())
stories = json.loads((data_dir / "story_bank.json").read_text())

print(f"Roles: {len(truth['roles'])}")
print(f"Archetypes: {len(archetypes)}")
print(f"Stories: {len(stories)}")
