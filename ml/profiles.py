from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score
from sklearn.preprocessing import StandardScaler

from ml.evaluation import TrainResult, describe_frame, safe_silhouette
from ml.features import IMPACT_VARIABLES, log_impact, recorded_impact, validate_frame

COMPONENT = "profiles"
PRIMARY_METRIC = "silhouette"
K_RANGE = range(3, 9)
STABILITY_SEEDS = range(1, 6)
STRONG_Z = 0.5
NO_RECORDED_IMPACT = "No recorded impact"
PROFILE_PENDING = "Profile pending"
MINOR_IMPACT = "Minor impact"
VARIABLE_LABELS = {
    "deceased": "Deaths",
    "injured": "Injuries",
    "missing": "Missing people",
    "people_affected": "People affected",
    "families_affected": "Families affected",
    "homes_destroyed": "Homes destroyed",
    "homes_damaged": "Homes damaged",
    "roads_damaged": "Roads damaged",
    "hectares": "Land affected",
}
REQUIRED_COLUMNS = (*IMPACT_VARIABLES, "has_impact")


def name_profiles(centroids: np.ndarray, sizes: Sequence[int]) -> list[str]:
    names = []
    for centroid in centroids:
        order = np.argsort(-centroid, kind="stable")
        strong = [i for i in order if centroid[i] >= STRONG_Z][:2]
        labels = [VARIABLE_LABELS[IMPACT_VARIABLES[i]] for i in strong]
        if not labels:
            names.append(MINOR_IMPACT)
        elif len(labels) == 1:
            names.append(labels[0])
        else:
            names.append(f"{labels[0]} and {labels[1].lower()}")
    groups = defaultdict(list)
    for index, name in enumerate(names):
        groups[name].append(index)
    for name, indices in groups.items():
        for rank, index in enumerate(sorted(indices, key=lambda i: -sizes[i])[1:], 2):
            names[index] = f"{name} ({rank})"
    return names


def _clustered_rows(frame):
    return frame["has_impact"].to_numpy(dtype=bool) & recorded_impact(frame)


@dataclass
class ProfileModel:
    scaler: StandardScaler
    kmeans: KMeans
    names: list[str]

    def assign(self, frame) -> list[str]:
        has_impact = frame["has_impact"].to_numpy(dtype=bool)
        clustered = _clustered_rows(frame)
        assigned = np.where(has_impact, NO_RECORDED_IMPACT, PROFILE_PENDING).astype(object)
        if clustered.any():
            scaled = self.scaler.transform(log_impact(frame)[clustered])
            assigned[clustered] = np.array(self.names, dtype=object)[
                self.kmeans.predict(scaled)
            ]
        return assigned.tolist()


def train_profiles(frame) -> TrainResult:
    validate_frame(frame, required=REQUIRED_COLUMNS)
    clustered = _clustered_rows(frame)
    raw = log_impact(frame)[clustered]
    scaler = StandardScaler().fit(raw)
    scaled = scaler.transform(raw)

    fits = {
        k: KMeans(n_clusters=k, n_init=10, random_state=0).fit(scaled) for k in K_RANGE
    }
    silhouettes = {k: safe_silhouette(scaled, fits[k].labels_) for k in K_RANGE}
    best = max(K_RANGE, key=lambda k: (silhouettes[k], -k))
    kmeans = fits[best]
    stability = float(
        np.mean(
            [
                adjusted_rand_score(
                    kmeans.labels_,
                    KMeans(n_clusters=best, n_init=10, random_state=seed)
                    .fit(scaled)
                    .labels_,
                )
                for seed in STABILITY_SEEDS
            ]
        )
    )

    counts = np.bincount(kmeans.labels_, minlength=best)
    names = name_profiles(kmeans.cluster_centers_, counts.tolist())
    metrics = {
        "k": int(best),
        "silhouette": float(silhouettes[best]),
        "silhouette_by_k": {str(k): float(value) for k, value in silhouettes.items()},
        "stability_ari": stability,
        "profile_sizes": {name: int(count) for name, count in zip(names, counts)},
        "no_impact_rows": int((frame["has_impact"].to_numpy(dtype=bool) & ~clustered).sum()),
    }
    return TrainResult(
        component=COMPONENT,
        model=ProfileModel(scaler, kmeans, names),
        metrics=metrics,
        primary_metric=PRIMARY_METRIC,
        trained_on=describe_frame(frame),
    )


def evaluate_profiles(model, frame) -> dict:
    validate_frame(frame, required=REQUIRED_COLUMNS)
    clustered = _clustered_rows(frame)
    scaled = StandardScaler().fit_transform(log_impact(frame)[clustered])
    position = {name: index for index, name in enumerate(model.names)}
    labels = [position[name] for name in np.asarray(model.assign(frame), dtype=object)[clustered]]
    return {"silhouette": safe_silhouette(scaled, labels)}
