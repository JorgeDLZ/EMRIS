import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.data import load_frame
from ml.evaluation import (
    CV_FOLDS,
    SplitDates,
    TrainResult,
    best_f1_threshold,
    classification_metrics,
    describe_frame,
    rolling_origin_folds,
    safe_silhouette,
    split_dates,
    temporal_masks,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

Y_TRUE = np.array([0, 0, 1, 1])
SCORES = np.array([0.1, 0.4, 0.35, 0.8])


def test_split_on_real_dates():
    frame = load_frame(DATA / "ungrd_emergencies_v2.csv", DATA / "divipola_dane.csv")
    assert split_dates(frame["occurred_on"]) == SplitDates(date(2025, 9, 1), date(2025, 10, 1))


def test_test_rows_never_precede_training_rows(synthetic_frame):
    masks = temporal_masks(synthetic_frame, split_dates(synthetic_frame["occurred_on"]))
    dates = synthetic_frame["occurred_on"]
    assert dates[masks["train"]].max() < dates[masks["test"]].min()
    assert (masks["fit"] | masks["validation"]).equals(masks["train"])
    assert not (masks["fit"] & masks["validation"]).any()
    assert not (masks["train"] & masks["test"]).any()
    assert masks["fit"].any() and masks["validation"].any() and masks["test"].any()


def test_too_short_history_is_rejected(synthetic_frame):
    short = synthetic_frame[
        synthetic_frame["occurred_on"].map(lambda d: d.month <= 4)
    ]
    with pytest.raises(ValueError, match="need at least 5 months"):
        split_dates(short["occurred_on"])


def test_best_threshold():
    assert best_f1_threshold(Y_TRUE, SCORES) == 0.35


def test_threshold_without_positives():
    assert best_f1_threshold(np.zeros(4, dtype=int), SCORES) == 0.5
    assert best_f1_threshold(np.zeros(0, dtype=int), np.zeros(0)) == 0.5


def test_classification_metrics():
    metrics = classification_metrics(Y_TRUE, SCORES, 0.35)
    assert metrics["precision"] == pytest.approx(2 / 3)
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == pytest.approx(0.8)
    assert metrics["pr_auc"] == pytest.approx(5 / 6)
    json.dumps(metrics)
    empty = classification_metrics(np.zeros(4, dtype=int), SCORES, 0.35)
    assert empty["pr_auc"] == 0.0 and empty["f1"] == 0.0


def test_safe_silhouette():
    assert safe_silhouette(np.array([[0.0], [1.0], [2.0]]), np.array([0, 0, 0])) == -1.0
    blobs = np.array([[0.0, 0.0], [0.1, 0.0], [10.0, 10.0], [10.1, 10.0]])
    assert safe_silhouette(blobs, np.array([0, 0, 1, 1])) > 0.9


def test_train_result_score_and_describe(synthetic_frame):
    result = TrainResult("impact", object(), {"f1": 0.7, "pr_auc": 0.6}, "f1", {"rows": 3})
    assert result.score == 0.7
    described = describe_frame(synthetic_frame)
    assert described["rows"] == 600 and described["start"] == "2025-01-01"
    assert described["end"].startswith("2025-12")


def test_rolling_origin_folds_expand_month_by_month(synthetic_frame):
    split = split_dates(synthetic_frame["occurred_on"])
    folds = rolling_origin_folds(synthetic_frame["occurred_on"], split.test_start)
    dates = pd.to_datetime(synthetic_frame["occurred_on"])
    assert len(folds) == CV_FOLDS
    months = [dates[f["validation"]].dt.month.unique().tolist() for f in folds]
    assert months == [[5], [6], [7], [8], [9]]
    for fold in folds:
        assert dates[fold["fit"]].max() < dates[fold["validation"]].min()
        assert not (fold["validation"] & (dates >= pd.Timestamp(split.test_start))).any()
    assert all(a["fit"].sum() < b["fit"].sum() for a, b in zip(folds, folds[1:]))


def test_rolling_origin_folds_need_enough_months(synthetic_frame):
    with pytest.raises(ValueError, match="need at least 6 months before the test period"):
        rolling_origin_folds(synthetic_frame["occurred_on"], date(2025, 3, 1))
