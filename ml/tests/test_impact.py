import calendar
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from ml.data import load_frame
from ml.evaluation import split_dates
from ml.features import IMPACT_VARIABLES
from ml.impact import (
    FACTOR_LABELS,
    GRADIENT_BOOSTING,
    LOGISTIC_REGRESSION,
    TOP_FACTORS,
    ImpactModel,
    TypeLocationBaseline,
    choose_kind,
    evaluate_impact,
    fit_pipeline,
    train_impact,
)
from ml.tests.conftest import make_synthetic_frame

ROOT = Path(__file__).resolve().parents[2]
UNGRD = ROOT / "data" / "ungrd_emergencies_v2.csv"
DIVIPOLA = ROOT / "data" / "divipola_dane.csv"

METRIC_KEYS = {
    "model", "threshold", "f1", "precision", "recall", "pr_auc", "baseline_f1",
    "baseline_recall", "baseline_pr_auc", "logistic_regression_f1",
    "gradient_boosting_f1", "test_rows", "test_positives",
}


def tiny_frame(rows):
    return pd.DataFrame(
        rows, columns=["event_type", "department", "municipality", "is_high_impact"]
    )


def test_baseline_falls_back_through_levels():
    train = tiny_frame([
        ("Flood", "05", "05001", True),
        ("Flood", "05", "05001", False),
        ("Flood", "05", "05002", True),
        ("Flood", "05", "05002", True),
        ("Flood", "25", "25001", False),
        ("Flood", "25", "25001", False),
        ("Fire", "25", "25001", False),
    ])
    baseline = TypeLocationBaseline().fit(train)
    query = tiny_frame([
        ("Flood", "05", "05002", False),
        ("Flood", "05", "05003", False),
        ("Flood", "99", "99001", False),
        ("Meteor", "99", "99001", False),
    ])
    scores = baseline.score(query)
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.75)
    assert scores[2] == pytest.approx(0.5)
    assert scores[3] == pytest.approx(3 / 7)


def test_baseline_skips_department_level_rows():
    train = tiny_frame([
        ("Flood", "05", "", True),
        ("Flood", "05", "", True),
        ("Flood", "05", "05001", False),
        ("Flood", "25", "25001", False),
        ("Flood", "25", "25001", False),
    ])
    baseline = TypeLocationBaseline().fit(train)
    scores = baseline.score(tiny_frame([("Flood", "05", "", False)]))
    assert scores[0] == pytest.approx(2 / 3)


def test_choose_kind():
    assert choose_kind({LOGISTIC_REGRESSION: 0.50, GRADIENT_BOOSTING: 0.515}) == LOGISTIC_REGRESSION
    assert choose_kind({LOGISTIC_REGRESSION: 0.50, GRADIENT_BOOSTING: 0.53}) == GRADIENT_BOOSTING


def test_train_returns_result(synthetic_frame):
    result = train_impact(synthetic_frame)
    assert result.component == "impact"
    assert result.primary_metric == "f1"
    assert set(result.metrics) == METRIC_KEYS
    json.dumps(result.metrics)
    probabilities = result.model.probability(synthetic_frame)
    assert probabilities.shape == (600,)
    assert ((probabilities >= 0) & (probabilities <= 1)).all()


def test_empty_validation_month_uses_default_threshold():
    frame = make_synthetic_frame()
    frame = frame[frame["occurred_on"].map(lambda d: d.month != 9)]
    result = train_impact(frame)
    assert result.metrics["threshold"] == 0.5


def test_prediction_ignores_impact_data(synthetic_frame):
    model = train_impact(synthetic_frame).model
    cleared = synthetic_frame.copy()
    cleared[list(IMPACT_VARIABLES)] = 0.0
    np.testing.assert_array_equal(
        model.probability(synthetic_frame), model.probability(cleared)
    )


def test_unknown_categories_do_not_break_prediction(synthetic_frame):
    model = train_impact(synthetic_frame).model
    unseen = synthetic_frame.head(1).copy()
    unseen["event_type"] = "Meteor"
    unseen["department"] = "99"
    unseen["municipality"] = "99999"
    assert model.probability(unseen).shape == (1,)


def test_logistic_explanation(synthetic_frame):
    pipeline = fit_pipeline(LOGISTIC_REGRESSION, synthetic_frame)
    model = ImpactModel(LOGISTIC_REGRESSION, pipeline, 0.5, None)
    explanations = model.explain(synthetic_frame.head(5))
    assert len(explanations) == 5
    month_names = set(calendar.month_name)
    for factors in explanations:
        assert len(factors) == TOP_FACTORS
        assert {f.feature for f in factors} <= set(FACTOR_LABELS.values())
        weights = [abs(f.weight) for f in factors]
        assert weights == sorted(weights, reverse=True)
        for factor in factors:
            if factor.feature == FACTOR_LABELS["month"]:
                assert factor.value in month_names


def test_logistic_explanation_with_dense_features(synthetic_frame):
    small = synthetic_frame[
        synthetic_frame["event_type"].isin(["Flood", "Wildfire"])
        & synthetic_frame["municipality"].isin(["05001", "25001"])
    ]
    pipeline = fit_pipeline(LOGISTIC_REGRESSION, small)
    assert not pipeline["features"].sparse_output_
    model = ImpactModel(LOGISTIC_REGRESSION, pipeline, 0.5, None)
    explanations = model.explain(small.head(4))
    assert [len(factors) for factors in explanations] == [TOP_FACTORS] * 4


def test_gradient_boosting_explanation_uses_importance(synthetic_frame):
    importance = {"event_type": 0.3, "department": 0.1, "municipality": 0.05, "month": 0.0}
    model = ImpactModel(
        GRADIENT_BOOSTING, fit_pipeline(GRADIENT_BOOSTING, synthetic_frame), 0.5, importance
    )
    for factors in model.explain(synthetic_frame.head(3)):
        assert [f.feature for f in factors] == ["Event type", "Department", "Municipality"]


def test_evaluate_reports_test_period(synthetic_frame):
    model = train_impact(synthetic_frame).model
    metrics = evaluate_impact(model, synthetic_frame)
    assert {"f1", "precision", "recall", "pr_auc", "test_rows"} <= set(metrics)
    test_start = split_dates(synthetic_frame["occurred_on"]).test_start
    expected = int((pd.to_datetime(synthetic_frame["occurred_on"]) >= pd.Timestamp(test_start)).sum())
    assert metrics["test_rows"] == expected


def test_model_survives_joblib(synthetic_frame):
    model = train_impact(synthetic_frame).model
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    buffer.seek(0)
    restored = joblib.load(buffer)
    np.testing.assert_array_equal(
        model.probability(synthetic_frame), restored.probability(synthetic_frame)
    )


def test_real_data_impact():
    result = train_impact(load_frame(UNGRD, DIVIPOLA))
    m = result.metrics
    assert m["model"] == LOGISTIC_REGRESSION
    assert (m["test_rows"], m["test_positives"]) == (993, 193)
    assert round(m["f1"], 2) == 0.51 and round(m["baseline_f1"], 2) == 0.48
    assert m["pr_auc"] > m["baseline_pr_auc"]
