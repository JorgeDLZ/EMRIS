import io
import json
from datetime import date
from pathlib import Path

import joblib
import pandas as pd

from ml.data import load_frame
from ml.evaluation import split_dates
from ml.features import IMPACT_VARIABLES
from ml.similarity import (
    COMPONENT,
    K_NEIGHBORS,
    PRIMARY_METRIC,
    Neighbor,
    fit_similarity,
    same_type_baseline,
    suggest_actions,
    train_similarity,
)

ROOT = Path(__file__).resolve().parents[2]
UNGRD = ROOT / "data" / "ungrd_emergencies_v2.csv"
DIVIPOLA = ROOT / "data" / "divipola_dane.csv"

METRIC_KEYS = {
    "precision_at_5", "precision_at_5_without_impact", "baseline_precision_at_5",
    "test_rows", "reference_rows",
}


def query_from(frame, position, **overrides):
    query = frame.iloc[[position]].copy()
    query["reference"] = "query"
    for column, value in overrides.items():
        query[column] = value
    return query


def neighbor(codes):
    return Neighbor("ref", 0.0, "Flood", date(2025, 1, 1), tuple(codes))


def test_neighbors_prefer_same_type(synthetic_frame):
    model = fit_similarity(synthetic_frame)
    query = query_from(synthetic_frame, 0)
    found = model.neighbors(query)[0]
    assert len(found) == K_NEIGHBORS
    assert {n.event_type for n in found} == {"Flood"}
    assert [n.distance for n in found] == sorted(n.distance for n in found)


def test_query_without_impact_ignores_impact_values(synthetic_frame):
    model = fit_similarity(synthetic_frame)
    results = []
    for value in (0.0, 10000.0):
        query = query_from(synthetic_frame, 1, has_impact=False)
        for column in IMPACT_VARIABLES:
            query[column] = value
        results.append(model.neighbors(query)[0])
    assert results[0] == results[1]


def test_query_is_not_its_own_neighbor(synthetic_frame):
    model = fit_similarity(synthetic_frame)
    rows = synthetic_frame.iloc[:20]
    for row, found in zip(rows["reference"], model.neighbors(rows)):
        assert len(found) == K_NEIGHBORS
        assert row not in {n.reference for n in found}


def test_unknown_categories_still_get_neighbors(synthetic_frame):
    model = fit_similarity(synthetic_frame)
    query = query_from(
        synthetic_frame, 0,
        event_type="Meteor", department="99", municipality="99999",
    )
    assert len(model.neighbors(query)[0]) == K_NEIGHBORS


def test_suggest_actions():
    neighbors = [
        neighbor(["deploy_fire_brigade", "clear_roads"]),
        neighbor(["deploy_fire_brigade"]),
        neighbor(["clear_roads", "supply_water"]),
        neighbor(["deploy_fire_brigade", "supply_water"]),
        neighbor(["evacuate_population"]),
    ]
    assert suggest_actions(neighbors) == [
        "deploy_fire_brigade", "supply_water", "clear_roads",
    ]
    distinct = [neighbor([code]) for code in ("clear_roads", "supply_water")]
    assert suggest_actions(distinct) == []


def test_same_type_baseline():
    columns = ["event_type", "is_high_impact"]
    references = pd.DataFrame(
        [("Flood", True), ("Flood", False), ("Flood", False), ("Fire", False)],
        columns=columns,
    )
    queries = pd.DataFrame([("Flood", True), ("Fire", True)], columns=columns)
    assert same_type_baseline(references, queries) == (1 / 3 + 0) / 2


def test_evaluation_uses_only_earlier_references(synthetic_frame):
    test_start = split_dates(synthetic_frame["occurred_on"]).test_start
    frame = synthetic_frame.copy()
    frame["is_high_impact"] = frame["occurred_on"] < test_start
    result = train_similarity(frame)
    assert result.metrics["precision_at_5"] == 0.0
    assert result.metrics["baseline_precision_at_5"] == 0.0
    assert (result.model.references["occurred_on"] >= test_start).any()


def test_metrics_shape_and_joblib(synthetic_frame):
    result = train_similarity(synthetic_frame)
    assert set(result.metrics) == METRIC_KEYS
    assert result.metrics["reference_rows"] == len(synthetic_frame)
    assert result.component == COMPONENT
    assert result.primary_metric == PRIMARY_METRIC
    assert result.trained_on["rows"] == len(synthetic_frame)
    json.dumps(result.metrics)
    buffer = io.BytesIO()
    joblib.dump(result.model, buffer)
    buffer.seek(0)
    restored = joblib.load(buffer)
    rows = synthetic_frame.iloc[:10]
    assert restored.neighbors(rows) == result.model.neighbors(rows)


def test_real_data_similarity():
    m = train_similarity(load_frame(UNGRD, DIVIPOLA)).metrics
    assert m["test_rows"] == 993 and m["reference_rows"] == 6505
    assert round(m["precision_at_5"], 2) == 0.94
    assert round(m["precision_at_5_without_impact"], 2) == 0.78
    assert round(m["baseline_precision_at_5"], 2) == 0.75
