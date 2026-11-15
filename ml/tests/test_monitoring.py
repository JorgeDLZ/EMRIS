import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.monitoring import (
    NOT_ENOUGH_DATA,
    RETRAIN,
    SIGNIFICANT_PSI,
    STABLE,
    WATCH,
    assess,
    compute_indicators,
    drift_level,
    group_rare,
    population_stability_index,
    psi,
    score_histogram,
    simulate_operational_frame,
)


def reference_for(frame, score_bins, flagged_share=0.3, reference_f1=0.5):
    return {
        "type_counts": frame["event_type"].value_counts().to_dict(),
        "department_counts": frame["department"].value_counts().to_dict(),
        "municipalities": sorted(set(frame["municipality"]) - {""}),
        "flagged_share": flagged_share,
        "reference_f1": reference_f1,
        "score_bins": score_bins,
    }


def test_psi_is_zero_for_identical_distributions():
    sample = ["Flood", "Wildfire", "Wildfire", "Landslide"]
    assert population_stability_index(sample, sample) == pytest.approx(0.0)


def test_psi_detects_a_shift():
    reference = ["Wildfire"] * 80 + ["Flood"] * 20
    shifted = ["Wildfire"] * 20 + ["Flood"] * 80
    assert population_stability_index(reference, shifted) > SIGNIFICANT_PSI


def test_psi_handles_new_categories():
    assert population_stability_index(["Flood"] * 10, ["Flood"] * 9 + ["Tsunami"]) > 0


def test_psi_is_zero_for_identical_and_large_for_disjoint():
    assert psi({"Flood": 50, "Wildfire": 50}, {"Flood": 5, "Wildfire": 5}) == 0.0
    assert psi({"Flood": 100}, {"Wildfire": 100}) > SIGNIFICANT_PSI


def test_psi_rejects_empty_sides():
    with pytest.raises(ValueError):
        psi({"Flood": 0}, {"Flood": 3})


def test_score_histogram_bins():
    assert score_histogram([0.0, 0.05, 0.95, 1.0, float("nan")]) == {
        **{str(i): 0 for i in range(10)}, "0": 2, "9": 2,
    }


def test_drift_levels():
    assert [drift_level(v) for v in (None, 0.05, 0.10, 0.24, 0.25)] == [
        None, "stable", "moderate", "moderate", "significant",
    ]


def test_group_rare_merges_small_and_unseen_categories():
    reference = ["A"] * 97 + ["B"] * 3 + ["C"]
    assert group_rare(reference, ["A", "B", "C", "D"], min_share=0.05) == ["A", "Other", "Other", "Other"]


def _frame(types, municipalities):
    return pd.DataFrame(
        {
            "event_type": types,
            "department": ["25"] * len(types),
            "municipality": municipalities,
        }
    )


def test_indicators_raise_alerts_on_drift():
    reference = _frame(["Wildfire"] * 8 + ["Flood"] * 2, ["25001"] * 10)
    reports = _frame(["Flood"] * 8 + ["Wildfire"] * 2, ["25001"] * 5 + ["99999"] * 5)
    scores = np.array([0.9] * 8 + [0.1] * 2)
    indicators = compute_indicators(
        reference_for(reference, score_bins=None, flagged_share=0.2), reports, scores, 0.5,
        np.zeros(10, dtype=bool),
    )
    assert indicators["emergencies"] == 10
    assert indicators["unseen_share"] == pytest.approx(0.5)
    assert len(indicators["alerts"]) == 3


def test_indicators_stay_quiet_without_drift():
    reference = _frame(["Wildfire"] * 8 + ["Flood"] * 2, ["25001"] * 10)
    scores = np.array([0.1] * 8 + [0.9] * 2)
    indicators = compute_indicators(
        reference_for(reference, score_bins=None, flagged_share=0.2), reference, scores, 0.5,
        np.zeros(10, dtype=bool),
    )
    assert indicators["alerts"] == []


def test_empty_window_is_not_enough_data(synthetic_frame):
    empty = synthetic_frame.iloc[0:0]
    indicators = compute_indicators(
        reference_for(synthetic_frame, score_bins=None), empty, np.array([]), 0.5, np.array([], dtype=bool)
    )
    assert indicators["emergencies"] == 0
    assert indicators["type_psi"] is None and indicators["f1"] is None
    assert assess(indicators) == NOT_ENOUGH_DATA
    json.dumps(indicators, allow_nan=False)


def test_unavailable_scores_are_counted_not_scored(synthetic_frame):
    window = synthetic_frame.iloc[:40]
    scores = np.full(40, np.nan)
    scores[:30] = 0.9
    indicators = compute_indicators(
        reference_for(synthetic_frame, score_bins=score_histogram([0.9] * 10)),
        window, scores, 0.5, np.ones(40, dtype=bool),
    )
    assert indicators["unavailable_share"] == 0.25
    json.dumps(indicators, allow_nan=False)


def test_shifted_simulation_is_flagged_for_retraining(synthetic_frame):
    simulated = simulate_operational_frame(synthetic_frame, date(2026, 1, 1), shifted_type="Wildfire")
    assert len(simulated) == 300 and simulated["reference"].str.startswith("simulated:").all()
    assert (simulated["event_type"] == "Wildfire").mean() >= 0.5
    assert simulated["occurred_on"].min() == date(2026, 1, 1)
    assert simulated["occurred_on"].max() == date(2026, 3, 31)
    indicators = compute_indicators(
        reference_for(synthetic_frame, score_bins=None), simulated,
        np.full(300, 0.5), 0.5, np.zeros(300, dtype=bool),
    )
    assert indicators["type_drift"] in {"moderate", "significant"}
    assert indicators["alerts"]


def test_unseen_municipalities_and_flagged_shift_ask_to_watch(synthetic_frame):
    window = synthetic_frame.iloc[:40].assign(municipality="99999")
    indicators = compute_indicators(
        reference_for(synthetic_frame, score_bins=None, flagged_share=0.2),
        window, np.full(40, 0.9), 0.5, np.zeros(40, dtype=bool),
    )
    assert indicators["unseen_share"] == 1.0
    assert indicators["flagged_share"] == 1.0
    assert assess({**indicators, "type_drift": "stable", "department_drift": "stable"}) == WATCH
    json.dumps(indicators, allow_nan=False)


def test_f1_drop_recommends_retraining():
    assert assess({"emergencies": 100, "type_drift": "stable", "score_drift": None,
                   "f1": 0.30, "reference_f1": 0.51}) == RETRAIN
    assert assess({"emergencies": 100, "type_drift": "stable", "score_drift": "stable",
                   "f1": 0.48, "reference_f1": 0.51}) == STABLE
