from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score
from sklearn.preprocessing import StandardScaler

from ml.evaluation import TrainResult, describe_frame, safe_silhouette
from ml.features import IMPACT_VARIABLES, log_impact, validate_frame
from ml.seismic import SeismicFeatures

COMPONENT = "municipal_risk"
PRIMARY_METRIC = "silhouette"
MIN_EMERGENCIES = 3
K_RANGE = range(3, 6)
TYPE_SHARES = 3
RESAMPLES = 20
RESAMPLE_FRACTION = 0.8
INSUFFICIENT_HISTORY = "Insufficient history"
SEVERITY_FEATURES = (
    "log_emergencies", "share_high_impact", "mean_impact",
    "log_shallow_events", "max_shallow_magnitude",
)
REQUIRED_COLUMNS = (
    "occurred_on", "event_type", "municipality", "is_high_impact", *IMPACT_VARIABLES,
)


def top_event_types(frame, n: int = TYPE_SHARES) -> list[str]:
    counts = frame.loc[frame["municipality"] != "", "event_type"].value_counts()
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [name for name, _ in ranked[:n]]


def _share_column(type_name: str) -> str:
    return "share_" + type_name.lower().replace(" ", "_")


def municipal_features(
    frame, seismic: Mapping[str, SeismicFeatures], type_names: Sequence[str]
) -> pd.DataFrame:
    rows = frame.loc[frame["municipality"] != ""]
    codes = rows["municipality"]
    counts = codes.value_counts()
    eligible = sorted(counts.index[counts >= MIN_EMERGENCIES])
    rows = rows.loc[codes.isin(eligible)]
    by_code = rows.groupby("municipality")
    features = pd.DataFrame(index=pd.Index(eligible, name="municipality"))
    features["log_emergencies"] = np.log1p(counts.loc[eligible].to_numpy(dtype=float))
    for type_name in type_names:
        features[_share_column(type_name)] = (
            (rows["event_type"] == type_name).groupby(rows["municipality"]).mean()
        )
    features["share_high_impact"] = by_code["is_high_impact"].apply(
        lambda values: float(np.mean(values.astype(bool)))
    )
    impact = pd.Series(log_impact(rows).sum(axis=1), index=rows.index)
    features["mean_impact"] = impact.groupby(rows["municipality"]).mean()
    zero = SeismicFeatures()
    entries = [seismic.get(code, zero) for code in eligible]
    features["log_shallow_events"] = np.log1p(
        [entry.shallow_event_count for entry in entries]
    )
    features["max_shallow_magnitude"] = [entry.max_shallow_magnitude for entry in entries]
    return features.astype(float)


def _severity(features: pd.DataFrame, scaled: np.ndarray) -> np.ndarray:
    columns = [features.columns.get_loc(name) for name in SEVERITY_FEATURES]
    return scaled[:, columns].mean(axis=1)


def _ward_labels(scaled: np.ndarray, k: int) -> np.ndarray:
    return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(scaled)


def _ranked(labels: np.ndarray, severity: np.ndarray) -> np.ndarray:
    order = sorted(set(labels), key=lambda label: severity[labels == label].mean())
    rank = {label: position for position, label in enumerate(order, 1)}
    return np.array([rank[label] for label in labels])


def assign_levels(features: pd.DataFrame, k: int) -> dict[str, int]:
    scaled = StandardScaler().fit_transform(features)
    levels = _ranked(_ward_labels(scaled, k), _severity(features, scaled))
    return {code: int(level) for code, level in zip(features.index, levels)}


@dataclass
class RiskModel:
    levels: dict[str, int]
    scores: dict[str, float]
    k: int
    type_names: list[str]

    def level_of(self, code: str) -> int | None:
        return self.levels.get(code)


def train_municipal_risk(frame, seismic: Mapping[str, SeismicFeatures]) -> TrainResult:
    validate_frame(frame, required=REQUIRED_COLUMNS)
    type_names = top_event_types(frame)
    features = municipal_features(frame, seismic, type_names)
    scaled = StandardScaler().fit_transform(features)

    fits = {k: _ward_labels(scaled, k) for k in K_RANGE}
    silhouettes = {k: safe_silhouette(scaled, fits[k]) for k in K_RANGE}
    best = max(K_RANGE, key=lambda k: (silhouettes[k], -k))
    severity = _severity(features, scaled)
    levels = _ranked(fits[best], severity)

    rng = np.random.default_rng(0)
    size = len(features)
    aris = []
    for _ in range(RESAMPLES):
        chosen = rng.choice(size, int(RESAMPLE_FRACTION * size), replace=False)
        aris.append(adjusted_rand_score(fits[best][chosen], _ward_labels(scaled[chosen], best)))

    counts = frame.loc[frame["municipality"] != "", "municipality"].value_counts()
    metrics = {
        "k": int(best),
        "silhouette": float(silhouettes[best]),
        "silhouette_by_k": {str(k): float(value) for k, value in silhouettes.items()},
        "stability_ari": float(np.mean(aris)),
        "level_sizes": {str(level): int((levels == level).sum()) for level in range(1, best + 1)},
        "municipalities": int(size),
        "insufficient_history": int((counts < MIN_EMERGENCIES).sum()),
        "type_shares": list(type_names),
    }
    model = RiskModel(
        levels={code: int(level) for code, level in zip(features.index, levels)},
        scores={code: float(score) for code, score in zip(features.index, severity)},
        k=int(best),
        type_names=list(type_names),
    )
    return TrainResult(
        component=COMPONENT,
        model=model,
        metrics=metrics,
        primary_metric=PRIMARY_METRIC,
        trained_on=describe_frame(frame),
    )


def evaluate_municipal_risk(model: RiskModel, frame, seismic: Mapping[str, SeismicFeatures]) -> dict:
    validate_frame(frame, required=REQUIRED_COLUMNS)
    features = municipal_features(frame, seismic, model.type_names)
    features = features.loc[features.index.isin(model.levels)]
    scaled = StandardScaler().fit_transform(features)
    labels = [model.levels[code] for code in features.index]
    return {"silhouette": safe_silhouette(scaled, labels)}
