from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.actions import ACTION_VOCABULARY
from ml.evaluation import TrainResult, describe_frame, split_dates
from ml.features import FRAME_COLUMNS, log_impact, report_time_features, validate_frame

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


@dataclass(frozen=True)
class Neighbor:
    reference: str
    distance: float
    event_type: str
    occurred_on: date
    action_codes: tuple[str, ...]


def _features(encoders, scaler, frame, with_impact):
    times = report_time_features(frame)
    blocks = [
        WEIGHTS[column] * encoders[column].transform(times[[column]])
        for column in CATEGORICAL_COLUMNS
    ]
    blocks.append(WEIGHTS["month"] * times[["month_sin", "month_cos"]].to_numpy())
    if with_impact:
        blocks.append(WEIGHTS["impact"] * scaler.transform(log_impact(frame)))
    return np.hstack(blocks)


def _assemble(encoders, scaler, references):
    with_impact = references["has_impact"].to_numpy(dtype=bool)
    return SimilarityModel(
        encoders=encoders,
        scaler=scaler,
        references=references,
        index_with_impact=NearestNeighbors(n_neighbors=K_NEIGHBORS + 1).fit(
            _features(encoders, scaler, references[with_impact], True)
        ),
        index_without_impact=NearestNeighbors(n_neighbors=K_NEIGHBORS + 1).fit(
            _features(encoders, scaler, references, False)
        ),
    )


@dataclass
class SimilarityModel:
    encoders: dict[str, OneHotEncoder]
    scaler: StandardScaler
    references: pd.DataFrame
    index_with_impact: NearestNeighbors
    index_without_impact: NearestNeighbors

    def feature_matrix(self, frame, with_impact: bool) -> np.ndarray:
        return _features(self.encoders, self.scaler, frame, with_impact)

    def _search(self, frame):
        has_impact = frame["has_impact"].to_numpy(dtype=bool)
        own_ids = frame["reference"].to_numpy(dtype=object)
        reference_ids = self.references["reference"].to_numpy(dtype=object)
        found = [None] * len(frame)
        for with_impact in (True, False):
            rows = np.flatnonzero(has_impact == with_impact)
            if not rows.size:
                continue
            if with_impact:
                index = self.index_with_impact
                positions = np.flatnonzero(self.references["has_impact"].to_numpy(dtype=bool))
            else:
                index = self.index_without_impact
                positions = np.arange(len(self.references))
            distances, indices = index.kneighbors(
                self.feature_matrix(frame.iloc[rows], with_impact),
                n_neighbors=min(K_NEIGHBORS + 1, index.n_samples_fit_),
            )
            for row, row_distances, row_indices in zip(rows, distances, indices):
                chosen = positions[row_indices]
                keep = reference_ids[chosen] != own_ids[row]
                found[row] = (chosen[keep][:K_NEIGHBORS], row_distances[keep][:K_NEIGHBORS])
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


def fit_similarity(frame) -> SimilarityModel:
    validate_frame(frame)
    references = frame[list(FRAME_COLUMNS)].reset_index(drop=True)
    encoders = {
        column: OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(
            report_time_features(references)[[column]]
        )
        for column in CATEGORICAL_COLUMNS
    }
    with_impact = references["has_impact"].to_numpy(dtype=bool)
    scaler = StandardScaler().fit(log_impact(references[with_impact]))
    return _assemble(encoders, scaler, references)


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


def evaluate_similarity(model, frame) -> dict:
    validate_frame(frame)
    test_start = split_dates(frame["occurred_on"]).test_start
    queries = frame[frame["occurred_on"] >= test_start].reset_index(drop=True)
    references = model.references
    eligible = references[
        (references["occurred_on"] < test_start)
        & ~references["reference"].isin(queries["reference"])
    ].reset_index(drop=True)
    temporary = _assemble(model.encoders, model.scaler, eligible)

    def precision(rows):
        found = temporary._search(rows)
        shares = []
        for (_, row), (positions, _) in zip(rows.iterrows(), found):
            chosen = eligible.iloc[positions]
            matches = (chosen["event_type"].to_numpy(dtype=object) == row["event_type"]) & (
                chosen["is_high_impact"].to_numpy(dtype=bool) == bool(row["is_high_impact"])
            )
            shares.append(float(matches.mean()) if len(matches) else 0.0)
        return float(np.mean(shares))

    with_impact = queries[queries["has_impact"].to_numpy(dtype=bool)]
    return {
        "precision_at_5": precision(with_impact),
        "precision_at_5_without_impact": precision(
            queries.assign(has_impact=False)
        ),
        "baseline_precision_at_5": same_type_baseline(eligible, queries),
        "test_rows": int(len(queries)),
    }


def train_similarity(frame) -> TrainResult:
    validate_frame(frame)
    model = fit_similarity(frame)
    metrics = evaluate_similarity(model, frame)
    metrics["reference_rows"] = int(len(model.references))
    return TrainResult(
        component=COMPONENT,
        model=model,
        metrics=metrics,
        primary_metric=PRIMARY_METRIC,
        trained_on=describe_frame(frame),
    )
