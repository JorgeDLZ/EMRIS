import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_monitoring_script_writes_labelled_outputs(tmp_path):
    subprocess.run(
        [sys.executable, "scripts/monitoring_test.py", "--rows", "60", "--out", str(tmp_path)],
        check=True,
        cwd=ROOT,
        capture_output=True,
    )
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["data"] == "SIMULATED"
    assert set(summary["batches"]) == {"normal", "drift"}
    assert all("status" in batch and "alerts" in batch for batch in summary["batches"].values())
    assert (tmp_path / "predictions.jsonl").read_text(encoding="utf-8").count('"data": "SIMULATED"') == 120
