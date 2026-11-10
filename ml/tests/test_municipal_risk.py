import io
import json
from datetime import date
from pathlib import Path

import joblib
import pandas as pd
import pytest

from ml.data import load_frame, municipality_centroids, read_divipola
from ml.features import FRAME_COLUMNS, IMPACT_VARIABLES
from ml.municipal_risk import (
    COMPONENT,
    PRIMARY_METRIC,
    SEVERITY_FEATURES,
    assign_levels,
    evaluate_municipal_risk,
    municipal_features,
    top_event_types,
    train_municipal_risk,
)
from ml.seismic import read_catalog, seismic_features

ROOT = Path(__file__).resolve().parents[2]
UNGRD = ROOT / "data" / "ungrd_emergencies_v2.csv"
DIVIPOLA = ROOT / "data" / "divipola_dane.csv"
SGC = ROOT / "data" / "sgc_seismicity_m25.csv"

METRIC_KEYS = {
    "k", "silhouette", "silhouette_by_k", "stability_ari", "level_sizes",
    "municipalities", "insufficient_history", "type_shares",
}
TYPES = ["Flood", "Wildfire", "Landslide"]


def rows(code, count, people=0.0, high=False, event_type=None):
    records = []
    for i in range(count):
        record = dict.fromkeys(FRAME_COLUMNS, None)
        record.update(dict.fromkeys(IMPACT_VARIABLES, 0.0))
        record.update(
            reference=f"{code}:{i}",
            occurred_on=date(2025, 1, 1),
            event_type=event_type or TYPES[i % 3],
            department=code[:2],
            municipality=code,
            people_affected=people,
            has_impact=True,
            action_codes=[],
            is_high_impact=high,
        )
        records.append(record)
    return records


def build_frame(records):
    return pd.DataFrame(records, columns=list(FRAME_COLUMNS))


def severity_groups():
    records = []
    for group, (count, people, high) in enumerate([(3, 0.0, False), (8, 10.0, False), (20, 500.0, True)]):
        for i in range(6):
            records += rows(f"{group + 1:02d}{i:03d}", count, people, high)
    return build_frame(records)


def test_features_need_three_emergencies(synthetic_frame):
    frame = pd.concat(
        [synthetic_frame, build_frame(rows("99001", 2) + rows("", 5))], ignore_index=True
    )
    features = municipal_features(frame, {}, top_event_types(frame))
    assert "99001" not in features.index and "" not in features.index
    assert len(features) == 9
    result = train_municipal_risk(frame, {})
    assert result.model.level_of("99001") is None
    assert result.model.level_of("05001") in {1, 2, 3, 4, 5}
    assert result.metrics["insufficient_history"] == 1


def test_top_event_types():
    frame = build_frame(
        rows("05001", 2, event_type="Flood")
        + rows("05001", 2, event_type="Fire")
        + rows("05001", 1, event_type="Wildfire")
        + rows("", 9, event_type="Earthquake")
    )
    assert top_event_types(frame) == ["Fire", "Flood", "Wildfire"]
    assert top_event_types(frame, 1) == ["Fire"]


def test_missing_seismic_entry_gets_zeros(synthetic_frame):
    features = municipal_features(synthetic_frame, {}, top_event_types(synthetic_frame))
    assert list(features.columns) == [
        "log_emergencies", "share_flood", "share_landslide", "share_wildfire",
        "share_high_impact", "mean_impact", "log_shallow_events", "max_shallow_magnitude",
    ]
    assert (features["log_shallow_events"] == 0).all()
    assert (features["max_shallow_magnitude"] == 0).all()
    assert len(train_municipal_risk(synthetic_frame, {}).model.levels) == 9


def test_levels_follow_severity():
    frame = severity_groups()
    features = municipal_features(frame, {}, top_event_types(frame))
    levels = assign_levels(features, 3)
    for group in range(3):
        assert {levels[f"{group + 1:02d}{i:03d}"] for i in range(6)} == {group + 1}
    scores = train_municipal_risk(frame, {}).model.scores
    means = [
        sum(scores[f"{group + 1:02d}{i:03d}"] for i in range(6)) / 6 for group in range(3)
    ]
    assert means[0] < means[1] < means[2]


def test_metrics_shape_evaluate_and_joblib(synthetic_frame):
    result = train_municipal_risk(synthetic_frame, {})
    assert result.component == COMPONENT
    assert result.primary_metric == PRIMARY_METRIC
    assert set(result.metrics) == METRIC_KEYS
    json.dumps(result.metrics)
    assert set(result.model.scores) == set(result.model.levels)
    assert len(SEVERITY_FEATURES) == 5
    evaluated = evaluate_municipal_risk(result.model, synthetic_frame, {})
    assert evaluated["silhouette"] == pytest.approx(result.metrics["silhouette"])
    buffer = io.BytesIO()
    joblib.dump(result.model, buffer)
    buffer.seek(0)
    assert joblib.load(buffer).levels == result.model.levels


def test_missing_columns_are_rejected(synthetic_frame):
    with pytest.raises(ValueError, match="municipality"):
        train_municipal_risk(synthetic_frame.drop(columns=["municipality"]), {})


def test_real_data_municipal_risk():
    frame = load_frame(UNGRD, DIVIPOLA)
    seismic = seismic_features(
        municipality_centroids(read_divipola(DIVIPOLA)), read_catalog(SGC)
    )
    result = train_municipal_risk(frame, seismic)
    m = result.metrics
    assert (m["municipalities"], m["insufficient_history"], m["k"]) == (620, 319, 3)
    assert m["type_shares"] == ["Wildfire", "Landslide", "Flood"]
    assert m["level_sizes"] == {"1": 321, "2": 229, "3": 70}
    assert round(m["silhouette"], 2) == 0.21
    assert result.model.level_of("68418") == 1
    assert not any(
        code.startswith("68") for code, level in result.model.levels.items() if level == 3
    )
