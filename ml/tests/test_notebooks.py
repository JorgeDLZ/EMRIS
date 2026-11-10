import json
from pathlib import Path

NOTEBOOKS = Path(__file__).resolve().parents[2] / "notebooks"
EXPECTED = [
    "01_exploration",
    "02_impact_estimator",
    "03_emergency_profiles",
    "04_similar_emergencies",
    "05_municipal_risk",
]


def test_notebooks_exist_with_cleared_outputs():
    paths = sorted(NOTEBOOKS.glob("*.ipynb"))
    assert [path.stem for path in paths] == EXPECTED
    for path in paths:
        notebook = json.loads(path.read_text(encoding="utf-8"))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                assert cell["outputs"] == [], path.name
                assert cell["execution_count"] is None, path.name
