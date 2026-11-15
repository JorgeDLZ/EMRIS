import pandas as pd
import pytest

from ml.monitoring import PSI_ALERT, group_rare, monitoring_indicators, population_stability_index


def test_psi_is_zero_for_identical_distributions():
    sample = ["Flood", "Wildfire", "Wildfire", "Landslide"]
    assert population_stability_index(sample, sample) == pytest.approx(0.0)


def test_psi_detects_a_shift():
    reference = ["Wildfire"] * 80 + ["Flood"] * 20
    shifted = ["Wildfire"] * 20 + ["Flood"] * 80
    assert population_stability_index(reference, shifted) > PSI_ALERT


def test_psi_handles_new_categories():
    assert population_stability_index(["Flood"] * 10, ["Flood"] * 9 + ["Tsunami"]) > 0


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
    indicators = monitoring_indicators(reference, reports, [True] * 8 + [False] * 2, 0.2)
    assert indicators["predictions"] == 10
    assert indicators["unseen_municipalities"] == pytest.approx(0.5)
    assert len(indicators["alerts"]) == 3


def test_indicators_stay_quiet_without_drift():
    reference = _frame(["Wildfire"] * 8 + ["Flood"] * 2, ["25001"] * 10)
    indicators = monitoring_indicators(reference, reference, [False] * 8 + [True] * 2, 0.2)
    assert indicators["alerts"] == []


def test_group_rare_merges_small_and_unseen_categories():
    reference = ["A"] * 97 + ["B"] * 3 + ["C"]
    assert group_rare(reference, ["A", "B", "C", "D"], min_share=0.05) == ["A", "Other", "Other", "Other"]
