from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import pairwise_distances
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from ml.actions import ACTION_VOCABULARY
from ml.evaluation import TrainResult, describe_frame, split_dates
from ml.features import IMPACT_VARIABLES, report_time_features, validate_frame

COMPONENT = "similarity"
PRIMARY_METRIC = "precision_at_5"
K_NEIGHBORS = 5
MIN_ACTION_SUPPORT = 2
WEIGHTS = {
    "event_type": 5.0,
    "department": 1.0,
    "municipality": 1.0,
    "month": 1.0,
    "impact": 1.0,
}
CATEGORICAL_COLUMNS = ("event_type", "department", "municipality")
REFERENCE_COLUMNS = (
    "reference", "occurred_on", "event_type", "action_codes", "has_impact",
    "is_high_impact",
)
BATCH_SIZE = 512
DISTANCE_DECIMALS = 9


@dataclass(frozen=True)
class Neighbor:
    reference: str
    distance: float
    event_type: str
    occurred_on: date
    action_codes: tuple[str, ...]


def _feature_input(frame):
    features = report_time_features(frame)
    for column in IMPACT_VARIABLES:
        features[column] = frame[column].to_numpy(dtype=float)
    return features


def _feature_transformer(with_impact):
    transformers = [
        (column, OneHotEncoder(handle_unknown="ignore"), [column])
        for column in CATEGORICAL_COLUMNS
    ]
    transformers.append(("month", "passthrough", ["month_sin", "month_cos"]))
    if with_impact:
        impact = make_pipeline(FunctionTransformer(np.log1p), StandardScaler())
        transformers.append(("impact", impact, list(IMPACT_VARIABLES)))
    return ColumnTransformer(
        transformers,
        sparse_threshold=1.0,
        transformer_weights={name: WEIGHTS[name] for name, _, _ in transformers},
    )


def _nearest(query_matrix, reference_matrix, positions, own_ids, reference_ids):
    distances = np.round(
        pairwise_distances(query_matrix, reference_matrix), DISTANCE_DECIMALS
    )
    tie_break = np.broadcast_to(positions, distances.shape)
    order = np.lexsort((tie_break, distances), axis=-1)
    found = []
    for row_distances, row_order, own_id in zip(distances, order, own_ids):
        chosen = row_order[: K_NEIGHBORS + 1]
        chosen = chosen[reference_ids[positions[chosen]] != own_id][:K_NEIGHBORS]
        found.append((positions[chosen], row_distances[chosen]))
    return found


@dataclass
class SimilarityModel:
    features_with_impact: ColumnTransformer
    features_without_impact: ColumnTransformer
    references: pd.DataFrame
    matrix_with_impact: object
    matrix_without_impact: object

    def feature_matrix(self, frame, with_impact: bool):
        if with_impact:
            return self.features_with_impact.transform(_feature_input(frame))
        return self.features_without_impact.transform(_feature_input(frame))

    def _candidates(self, with_impact, eligible):
        if with_impact:
            positions = np.flatnonzero(self.references["has_impact"].to_numpy(dtype=bool))
            keep = eligible[positions]
            return self.matrix_with_impact[keep], positions[keep]
        positions = np.flatnonzero(eligible)
        return self.matrix_without_impact[positions], positions

    def _search(self, frame, eligible=None):
        if eligible is None:
            eligible = np.ones(len(self.references), dtype=bool)
        has_impact = frame["has_impact"].to_numpy(dtype=bool)
        own_ids = frame["reference"].to_numpy(dtype=object)
        reference_ids = self.references["reference"].to_numpy(dtype=object)
        found = [None] * len(frame)
        for with_impact in (True, False):
            rows = np.flatnonzero(has_impact == with_impact)
            if not rows.size:
                continue
            matrix, positions = self._candidates(with_impact, eligible)
            for start in range(0, rows.size, BATCH_SIZE):
                batch = rows[start : start + BATCH_SIZE]
                query_matrix = self.feature_matrix(frame.iloc[batch], with_impact)
                results = _nearest(
                    query_matrix, matrix, positions, own_ids[batch], reference_ids
                )
                for row, result in zip(batch, results):
                    found[row] = result
        return found

    def neighbors(self, frame) -> list[list[Neighbor]]:
        references = self.references
        return [
            [
                Neighbor(
                    reference=str(references["reference"].iloc[position]),
                    distance=float(distance),
                    event_type=str(references["event_type"].iloc[position]),
                    occurred_on=references["occurred_on"].iloc[position],
                    action_codes=tuple(references["action_codes"].iloc[position]),
                )
                for position, distance in zip(positions, distances)
            ]
            for positions, distances in self._search(frame)
        ]


def _fit(frame):
    frame = frame.reset_index(drop=True)
    inputs = _feature_input(frame)
    with_impact = frame["has_impact"].to_numpy(dtype=bool)
    features_with_impact = _feature_transformer(True).fit(inputs[with_impact])
    features_without_impact = _feature_transformer(False).fit(inputs)
    references = frame[list(REFERENCE_COLUMNS)].copy()
    references["action_codes"] = references["action_codes"].map(tuple)
    return SimilarityModel(
        features_with_impact=features_with_impact,
        features_without_impact=features_without_impact,
        references=references,
        matrix_with_impact=features_with_impact.transform(inputs[with_impact]),
        matrix_without_impact=features_without_impact.transform(inputs),
    )


def fit_similarity(frame) -> SimilarityModel:
    validate_frame(frame)
    return _fit(frame)


def suggest_actions(neighbors: Sequence[Neighbor]) -> list[str]:
    counts = Counter(code for n in neighbors for code in set(n.action_codes))
    order = {code: position for position, code in enumerate(ACTION_VOCABULARY)}
    supported = [code for code, count in counts.items() if count >= MIN_ACTION_SUPPORT]
    return sorted(supported, key=lambda code: (-counts[code], order[code]))


def same_type_baseline(references, queries) -> float:
    high_rate = references.groupby("event_type")["is_high_impact"].mean()
    shares = []
    for event_type, is_high in zip(queries["event_type"], queries["is_high_impact"]):
        if event_type not in high_rate.index:
            shares.append(0.0)
        else:
            rate = float(high_rate[event_type])
            shares.append(rate if is_high else 1.0 - rate)
    return float(np.mean(shares))


def _evaluate(model, frame):
    test_start = split_dates(frame["occurred_on"]).test_start
    queries = frame[frame["occurred_on"] >= test_start].reset_index(drop=True)
    references = model.references
    eligible = (
        (references["occurred_on"] < test_start)
        & ~references["reference"].isin(queries["reference"])
    ).to_numpy(dtype=bool)
    event_types = references["event_type"].to_numpy(dtype=object)
    high_impact = references["is_high_impact"].to_numpy(dtype=bool)

    def precision(rows):
        shares = []
        found = model._search(rows, eligible)
        for event_type, is_high, (positions, _) in zip(
            rows["event_type"], rows["is_high_impact"], found
        ):
            matches = (event_types[positions] == event_type) & (
                high_impact[positions] == bool(is_high)
            )
            shares.append(float(matches.mean()) if len(matches) else 0.0)
        return float(np.mean(shares))

    with_impact = queries[queries["has_impact"].to_numpy(dtype=bool)]
    return {
        "precision_at_5": precision(with_impact),
        "precision_at_5_without_impact": precision(queries.assign(has_impact=False)),
        "baseline_precision_at_5": same_type_baseline(references[eligible], queries),
        "test_rows": int(len(queries)),
    }


def evaluate_similarity(model, frame) -> dict:
    validate_frame(frame)
    return _evaluate(model, frame)


def train_similarity(frame) -> TrainResult:
    validate_frame(frame)
    model = _fit(frame)
    metrics = _evaluate(model, frame)
    metrics["reference_rows"] = int(len(model.references))
    return TrainResult(
        component=COMPONENT,
        model=model,
        metrics=metrics,
        primary_metric=PRIMARY_METRIC,
        trained_on=describe_frame(frame),
    )
