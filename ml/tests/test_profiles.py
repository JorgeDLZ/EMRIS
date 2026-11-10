import io
import json
from pathlib import Path

import joblib
import numpy as np
import pytest

from ml.data import load_frame
from ml.features import IMPACT_VARIABLES
from ml.profiles import (
    COMPONENT,
    MINOR_IMPACT,
    NO_RECORDED_IMPACT,
    PRIMARY_METRIC,
    PROFILE_PENDING,
    evaluate_profiles,
    name_profiles,
    train_profiles,
)
from ml.tests.conftest import make_synthetic_frame

ROOT = Path(__file__).resolve().parents[2]
UNGRD = ROOT / "data" / "ungrd_emergencies_v2.csv"
DIVIPOLA = ROOT / "data" / "divipola_dane.csv"

METRIC_KEYS = {
    "k", "silhouette", "silhouette_by_k", "stability_ari", "profile_sizes",
    "no_impact_rows",
}


def blob_frame(rows_per_blob=60):
    frame = make_synthetic_frame(rows_per_blob * 3)
    rng = np.random.default_rng(1)
    for column in IMPACT_VARIABLES:
        frame[column] = 0.0
    for blob, column in enumerate(("people_affected", "hectares", "deceased")):
        rows = frame.index[blob * rows_per_blob:(blob + 1) * rows_per_blob]
        frame.loc[rows, column] = 2000.0 + rng.normal(0, 200, len(rows))
    return frame


def test_name_profiles():
    z = np.zeros((3, 9))
    z[1, 1], z[1, 0] = 4.4, 3.6
    z[2, 8] = 0.2
    assert name_profiles(z, [10, 5, 3]) == [
        "Minor impact", "Injuries and deaths", "Minor impact (2)",
    ]


def test_three_blobs_give_k_3():
    result = train_profiles(blob_frame())
    assert result.metrics["k"] == 3
    assert sorted(result.metrics["profile_sizes"]) == [
        "Deaths", "Land affected", "People affected",
    ]


def test_zero_and_missing_impact_are_not_clustered():
    frame = blob_frame()
    frame.loc[frame.index[:5], list(IMPACT_VARIABLES)] = 0.0
    frame.loc[frame.index[-4:], "has_impact"] = False
    result = train_profiles(frame)
    names = result.model.assign(frame)
    assert names[:5] == [NO_RECORDED_IMPACT] * 5
    assert names[-4:] == [PROFILE_PENDING] * 4
    assert NO_RECORDED_IMPACT not in result.metrics["profile_sizes"]
    assert PROFILE_PENDING not in result.metrics["profile_sizes"]
    assert result.metrics["no_impact_rows"] == 5
    assert sum(result.metrics["profile_sizes"].values()) == len(frame) - 9


def test_metrics_shape(synthetic_frame):
    result = train_profiles(synthetic_frame)
    assert set(result.metrics) == METRIC_KEYS
    assert set(result.metrics["silhouette_by_k"]) == {str(k) for k in range(3, 9)}
    assert result.component == COMPONENT
    assert result.primary_metric == PRIMARY_METRIC
    assert result.trained_on["rows"] == len(synthetic_frame)
    json.dumps(result.metrics)


def test_evaluate_matches_training(synthetic_frame):
    result = train_profiles(synthetic_frame)
    evaluated = evaluate_profiles(result.model, synthetic_frame)
    assert evaluated["silhouette"] == pytest.approx(result.metrics["silhouette"])


def test_model_survives_joblib(synthetic_frame):
    model = train_profiles(synthetic_frame).model
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    buffer.seek(0)
    assert joblib.load(buffer).assign(synthetic_frame) == model.assign(synthetic_frame)


def test_real_data_profiles():
    m = train_profiles(load_frame(UNGRD, DIVIPOLA)).metrics
    assert m["k"] == 3 and m["no_impact_rows"] == 688
    assert m["profile_sizes"] == {
        "Minor impact": 4638,
        "Families affected and people affected": 1015,
        "Injuries and deaths": 164,
    }
    assert round(m["silhouette"], 2) == 0.51 and m["stability_ari"] > 0.9
