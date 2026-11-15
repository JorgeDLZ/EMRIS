"""Initial monitoring test for the impact estimator, run on SIMULATED reports.

Every report scored here is invented for the test: it is labelled "SIMULATED"
in the log, in the CSV and in the summary, and none of it touches the database.

Two batches stand in for the first 90 days of 2026, both drawn from the 2025
history the model is trained on:
- normal: rows sampled at random;
- drift: half of the rows forced to the second most frequent event type.

Each prediction is written to a JSON-lines log, and the batch indicators
(event-type and department PSI, score PSI, share flagged as high impact,
unseen municipalities, F1 on the simulated labels) are compared with the
training data to give a status: stable, watch, retrain or not enough data.

    python scripts/monitoring_test.py --rows 300 --out monitoring_output
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data import load_frame  # noqa: E402
from ml.impact import train_impact  # noqa: E402
from ml.monitoring import (  # noqa: E402
    assess,
    compute_indicators,
    reference_profile,
    simulate_operational_frame,
)

LABEL = "SIMULATED"
SIMULATED_START = date(2026, 1, 1)

logger = logging.getLogger("emris.monitoring")


def score_batch(model, version, reports, batch, log_path):
    probabilities = model.probability(reports)
    flagged = probabilities >= model.threshold
    factors = model.explain(reports)
    rows = []
    with log_path.open("a", encoding="utf-8") as log:
        for (_, report), probability, high, top in zip(reports.iterrows(), probabilities, flagged, factors):
            entry = {
                "data": LABEL,
                "batch": batch,
                "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": version,
                "input": {
                    "reference": report["reference"],
                    "occurred_on": str(report["occurred_on"]),
                    "event_type": report["event_type"],
                    "department": report["department"],
                    "municipality": report["municipality"],
                },
                "probability": round(float(probability), 4),
                "high_impact": bool(high),
                "factors": [f"{factor.feature}: {factor.value}" for factor in top],
            }
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            rows.append({**entry["input"], "data": LABEL, "batch": batch,
                         "probability": entry["probability"], "high_impact": entry["high_impact"]})
    logger.info("%s batch '%s': %d predictions logged", LABEL, batch, len(rows))
    return pd.DataFrame(rows), flagged


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=ROOT / "monitoring_output")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.out / "predictions.jsonl"
    log_path.unlink(missing_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(args.out / "monitoring.log", mode="w")],
    )

    frame = load_frame(ROOT / "data" / "ungrd_emergencies_v2.csv", ROOT / "data" / "divipola_dane.csv")
    result = train_impact(frame)
    model = result.model
    version = f"impact/{result.metrics['model']}/threshold={model.threshold:.3f}"
    logger.info("Model trained on %s to %s: %s", result.trained_on["start"], result.trained_on["end"], version)

    reference = {
        **reference_profile(frame, model.probability(frame), model.threshold),
        "reference_f1": round(result.metrics["f1"], 4),
    }
    shifted_type = frame["event_type"].value_counts().index[1]
    summary = {
        "data": LABEL,
        "reference": f"2025 history (real), {len(frame)} records",
        "model": version,
        "drift_type": shifted_type,
        "batches": {},
    }
    scored = []
    for offset, (batch, shift) in enumerate((("normal", None), ("drift", shifted_type))):
        reports = simulate_operational_frame(
            frame, SIMULATED_START, rows=args.rows, shifted_type=shift, seed=args.seed + offset
        )
        rows, _ = score_batch(model, version, reports, batch, log_path)
        scored.append(rows)
        indicators = compute_indicators(
            reference, reports, model.probability(reports), model.threshold, np.ones(len(reports), dtype=bool)
        )
        indicators["status"] = assess(indicators)
        summary["batches"][batch] = indicators
        for alert in indicators["alerts"]:
            logger.warning("%s batch '%s' ALERT: %s", LABEL, batch, alert)
        logger.info("%s batch '%s': status %s", LABEL, batch, indicators["status"])

    pd.concat(scored).to_csv(args.out / "predictions_simulated.csv", index=False)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{LABEL} OPERATIONAL DATA - monitoring test summary")
    print(f"Reference: {summary['reference']}, {reference['flagged_share']:.1%} flagged; drift batch shifted to {shifted_type}")
    for batch, indicators in summary["batches"].items():
        print(
            f"  {batch:<7} emergencies={indicators['emergencies']}  flagged={indicators['flagged_share']:.1%}  "
            f"PSI type={indicators['type_psi']:.3f}  PSI department={indicators['department_psi']:.3f}  "
            f"PSI score={indicators['score_psi']:.3f}  unseen municipalities={indicators['unseen_share']:.1%}  "
            f"F1={indicators['f1']}  status={indicators['status']}"
        )
        for alert in indicators["alerts"]:
            print(f"           ! {alert}")
    print(f"Files: {log_path}, {args.out / 'predictions_simulated.csv'}, {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
