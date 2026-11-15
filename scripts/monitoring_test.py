"""Initial monitoring test for the impact estimator, run on SIMULATED reports.

Every report scored here is invented for the test: it is labelled "SIMULATED"
in the log, in the CSV and in the summary, and none of it touches the database.

Two batches stand in for January 2026:
- normal: reports drawn from the January 2025 history;
- drift: the same, with floods and landslides four times as likely, as in an
  unusually rainy month.

Each prediction is written to a JSON-lines log, and the batch indicators
(volume, share flagged, PSI of event type and department, unseen
municipalities) are compared with January 2025 to raise alerts.

    python scripts/monitoring_test.py --rows 200 --out monitoring_output
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
from ml.monitoring import monitoring_indicators  # noqa: E402

LABEL = "SIMULATED"
REPORT_FIELDS = ["event_type", "department", "municipality"]
RAINY_TYPES = {"Flood", "Flash flood", "Landslide"}
DRIFT_WEIGHT = 4.0
SIMULATED_MONTH = (2026, 1)

logger = logging.getLogger("emris.monitoring")


def simulate_reports(reference, rows, rng, drift):
    weights = np.where(reference["event_type"].isin(RAINY_TYPES), DRIFT_WEIGHT, 1.0) if drift else None
    picked = reference.sample(n=rows, replace=True, weights=weights, random_state=rng)
    year, month = SIMULATED_MONTH
    days = rng.integers(1, 32, size=rows)
    reports = picked[REPORT_FIELDS].reset_index(drop=True)
    reports.insert(0, "occurred_on", [date(year, month, int(day)) for day in days])
    reports.insert(0, "reference", [f"{LABEL}-{'DRIFT' if drift else 'NORMAL'}-{i + 1:04d}" for i in range(rows)])
    return reports


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
    parser.add_argument("--rows", type=int, default=200)
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

    january = frame[pd.to_datetime(frame["occurred_on"]).dt.month == 1]
    reference_flagged = float(np.mean(model.predict(january)))
    rng = np.random.default_rng(args.seed)

    summary = {"data": LABEL, "reference": "January 2025 (real history)", "model": version, "batches": {}}
    scored = []
    for batch, drift in (("normal", False), ("drift", True)):
        reports = simulate_reports(january, args.rows, rng, drift)
        rows, flagged = score_batch(model, version, reports, batch, log_path)
        scored.append(rows)
        indicators = monitoring_indicators(january, reports, flagged, reference_flagged)
        summary["batches"][batch] = indicators
        for alert in indicators["alerts"]:
            logger.warning("%s batch '%s' ALERT: %s", LABEL, batch, alert)
        if not indicators["alerts"]:
            logger.info("%s batch '%s': no alerts", LABEL, batch)

    pd.concat(scored).to_csv(args.out / "predictions_simulated.csv", index=False)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{LABEL} OPERATIONAL DATA - monitoring test summary")
    print(f"Reference: January 2025, {len(january)} real reports, {reference_flagged:.1%} flagged")
    for batch, indicators in summary["batches"].items():
        print(
            f"  {batch:<7} predictions={indicators['predictions']}  flagged={indicators['flagged_share']:.1%}  "
            f"PSI type={indicators['psi_event_type']:.3f}  PSI department={indicators['psi_department']:.3f}  "
            f"unseen municipalities={indicators['unseen_municipalities']:.1%}  alerts={len(indicators['alerts'])}"
        )
        for alert in indicators["alerts"]:
            print(f"           ! {alert}")
    print(f"Files: {log_path}, {args.out / 'predictions_simulated.csv'}, {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
