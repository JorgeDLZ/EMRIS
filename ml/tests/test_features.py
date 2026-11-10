from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.features import (
    IMPACT_VARIABLES,
    impact_preprocessor,
    log_impact,
    recorded_impact,
    report_time_features,
    validate_frame,
)
from ml.tests.conftest import make_synthetic_frame


def test_validate_frame_names_missing_columns(synthetic_frame):
    broken = synthetic_frame.drop(columns=["hectares", "reference"])
    with pytest.raises(ValueError, match="frame is missing columns: hectares, reference"):
        validate_frame(broken)
    validate_frame(synthetic_frame)


def test_report_time_features_exclude_impact(synthetic_frame):
    features = report_time_features(synthetic_frame)
    assert list(features.columns) == [
        "event_type", "department", "municipality", "month_sin", "month_cos",
    ]
    assert not set(IMPACT_VARIABLES) & set(features.columns)
    assert features.index.equals(synthetic_frame.index)
    scaled = synthetic_frame.copy()
    scaled[list(IMPACT_VARIABLES)] *= 10
    assert report_time_features(scaled).equals(features)


def test_month_cycle_wraps(synthetic_frame):
    def point(month):
        frame = synthetic_frame.iloc[:1].copy()
        frame["occurred_on"] = [date(2025, month, 15)]
        row = report_time_features(frame).iloc[0]
        return np.array([row["month_sin"], row["month_cos"]])

    assert np.linalg.norm(point(12) - point(1)) == pytest.approx(np.linalg.norm(point(1) - point(2)))
    assert tuple(point(1)) == pytest.approx((0.0, 1.0))


def test_rare_and_unknown_categories():
    frame = make_synthetic_frame()
    extra = frame.iloc[:2].copy()
    extra["municipality"] = "77777"
    frame = pd.concat([frame, extra], ignore_index=True)
    preprocessor = impact_preprocessor(dense=True)
    preprocessor.fit(report_time_features(frame))
    names = list(preprocessor.get_feature_names_out())
    infrequent = names.index("municipality__municipality_infrequent_sklearn")
    municipality = preprocessor.output_indices_["municipality"]

    seen_twice = report_time_features(frame[frame["municipality"] == "77777"].iloc[:1])
    assert preprocessor.transform(seen_twice)[0, infrequent] == 1.0

    unseen = seen_twice.copy()
    unseen["municipality"] = "99999"
    assert not preprocessor.transform(unseen)[0, municipality].any()


def test_log_impact_and_recorded_impact(synthetic_frame):
    frame = synthetic_frame.copy()
    frame.loc[frame.index[:5], list(IMPACT_VARIABLES)] = 0.0
    logged = log_impact(frame)
    recorded = recorded_impact(frame)
    assert logged.shape == (600, 9)
    assert not recorded[:5].any()
    assert (logged[:5] == 0).all()
    assert logged[5:].max() > 0
    assert np.allclose(logged, np.log1p(frame[list(IMPACT_VARIABLES)].to_numpy(dtype=float)))
