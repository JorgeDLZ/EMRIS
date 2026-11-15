import math
from collections import Counter
from datetime import timedelta

import numpy as np
import pandas as pd

from ml.evaluation import classification_metrics
from ml.features import FRAME_COLUMNS

SCORE_BINS = 10
PSI_FLOOR = 1e-4
RARE_SHARE = 0.03
MODERATE_PSI = 0.10
SIGNIFICANT_PSI = 0.25
UNSEEN_ALERT = 0.10
FLAGGED_SHIFT_ALERT = 0.10
MIN_WINDOW = 30
MIN_LABELLED = 30
MAX_F1_DROP = 0.10
SIMULATED_DAYS = 90
OTHER = "Other"

STABLE = "stable"
WATCH = "watch"
RETRAIN = "retrain"
NOT_ENOUGH_DATA = "not_enough_data"
MODERATE = "moderate"
SIGNIFICANT = "significant"


def psi(reference, current):
    """Population stability index between two count (or share) mappings."""
    reference_total = sum(reference.values())
    current_total = sum(current.values())
    if reference_total <= 0 or current_total <= 0:
        raise ValueError("both distributions need at least one observation")
    total = 0.0
    for key in set(reference) | set(current):
        expected = max(reference.get(key, 0) / reference_total, PSI_FLOOR)
        actual = max(current.get(key, 0) / current_total, PSI_FLOOR)
        total += (actual - expected) * math.log(actual / expected)
    return round(total, 4)


def population_stability_index(expected, actual):
    """PSI between two categorical samples (0 = same distribution)."""
    return psi(Counter(expected), Counter(actual))


def group_rare(reference, values, min_share=RARE_SHARE):
    """Map categories below min_share of the reference (or unseen) to "Other".

    Small batches spread over many rare categories inflate the PSI by sampling
    noise alone, so rare departments or types are compared as one group.
    """
    share = pd.Series(list(reference)).value_counts(normalize=True)
    common = set(share[share >= min_share].index)
    return [value if value in common else OTHER for value in values]


def _common_categories(reference):
    total = sum(reference.values())
    return {key for key, count in reference.items() if total and count / total >= RARE_SHARE}


def grouped_counts(reference, values):
    """Counts of values with the categories that are rare in the reference grouped as "Other"."""
    common = _common_categories(reference)
    return dict(Counter(value if value in common else OTHER for value in values))


def _grouped_reference(reference):
    common = _common_categories(reference)
    grouped = Counter()
    for key, count in reference.items():
        grouped[key if key in common else OTHER] += count
    return dict(grouped)


def score_histogram(scores):
    counts = dict.fromkeys((str(index) for index in range(SCORE_BINS)), 0)
    for score in scores:
        if not math.isnan(score):
            counts[str(min(int(score * SCORE_BINS), SCORE_BINS - 1))] += 1
    return counts


def drift_level(value):
    if value is None:
        return None
    if value < MODERATE_PSI:
        return STABLE
    if value < SIGNIFICANT_PSI:
        return MODERATE
    return SIGNIFICANT


def reference_profile(frame, probabilities, threshold):
    """What monitoring compares new emergencies with, taken from the training data."""
    probabilities = np.asarray(probabilities, dtype=float)
    return {
        "type_counts": {str(k): int(v) for k, v in frame["event_type"].value_counts().items()},
        "department_counts": {str(k): int(v) for k, v in frame["department"].value_counts().items()},
        "municipalities": sorted(set(frame["municipality"]) - {""}),
        "flagged_share": round(float(np.mean(probabilities >= threshold)), 4) if len(probabilities) else None,
        "score_bins": score_histogram(probabilities),
    }


def _category_psi(reference, values):
    if not reference or len(values) == 0:
        return None
    return psi(_grouped_reference(reference), grouped_counts(reference, values))


def _share(mask):
    return round(float(np.mean(mask)), 4)


def _performance(frame, scores, threshold, labelled, available):
    rows = labelled & available
    labels = frame["is_high_impact"].to_numpy(dtype=bool)[rows] if "is_high_impact" in frame else None
    if labels is None or rows.sum() < MIN_LABELLED or not labels.any():
        return {"f1": None, "precision": None, "recall": None}
    metrics = classification_metrics(labels, scores[rows], threshold)
    return {name: round(metrics[name], 4) for name in ("f1", "precision", "recall")}


def _alerts(indicators):
    alerts = []
    for key, label in (("type", "Event-type"), ("department", "Department"), ("score", "Score")):
        level = indicators[f"{key}_drift"]
        if level in (MODERATE, SIGNIFICANT):
            alerts.append(f"{label} distribution drifted (PSI {indicators[f'{key}_psi']:.2f}, {level})")
    unseen = indicators["unseen_share"]
    if unseen is not None and unseen > UNSEEN_ALERT:
        alerts.append(f"{unseen:.0%} of emergencies come from municipalities not seen in training")
    flagged, reference_flagged = indicators["flagged_share"], indicators["reference_flagged_share"]
    if _flagged_shift(flagged, reference_flagged):
        alerts.append(f"Share flagged as high impact moved from {reference_flagged:.0%} to {flagged:.0%}")
    if _f1_dropped(indicators.get("f1"), indicators.get("reference_f1")):
        alerts.append(
            f"F1 on closed emergencies fell from {indicators['reference_f1']:.2f} to {indicators['f1']:.2f}"
        )
    return alerts


def _flagged_shift(flagged, reference_flagged):
    if flagged is None or reference_flagged is None:
        return False
    return abs(flagged - reference_flagged) > FLAGGED_SHIFT_ALERT


def _f1_dropped(f1, reference_f1):
    return f1 is not None and reference_f1 is not None and reference_f1 - f1 > MAX_F1_DROP


def compute_indicators(reference, frame, scores, threshold, labelled):
    scores = np.asarray(scores, dtype=float)
    labelled = np.asarray(labelled, dtype=bool)
    available = ~np.isnan(scores)
    rows = len(frame)
    type_psi = _category_psi(reference.get("type_counts"), frame["event_type"])
    department_psi = _category_psi(reference.get("department_counts"), frame["department"])
    score_reference = reference.get("score_bins")
    score_psi = None
    if score_reference and sum(score_reference.values()) and available.any():
        score_psi = psi(score_reference, score_histogram(scores[available]))
    municipalities = reference.get("municipalities")
    unseen_share = None
    if municipalities is not None and rows:
        located = frame["municipality"][frame["municipality"] != ""]
        unseen_share = _share(~located.isin(set(municipalities))) if len(located) else 0.0
    reference_flagged = reference.get("flagged_share")
    indicators = {
        "emergencies": int(rows),
        "type_psi": type_psi,
        "type_drift": drift_level(type_psi),
        "department_psi": department_psi,
        "department_drift": drift_level(department_psi),
        "score_psi": score_psi,
        "score_drift": drift_level(score_psi),
        "unavailable_share": _share(~available) if rows else None,
        "unseen_share": unseen_share,
        "flagged_share": _share(scores[available] >= threshold) if available.any() else None,
        "reference_flagged_share": None if reference_flagged is None else float(reference_flagged),
        "labelled": int(labelled.sum()),
        **_performance(frame, scores, threshold, labelled, available),
        "reference_f1": reference.get("reference_f1"),
    }
    indicators["alerts"] = _alerts(indicators)
    return indicators


def assess(indicators):
    if (indicators.get("emergencies") or 0) < MIN_WINDOW:
        return NOT_ENOUGH_DATA
    drifts = [indicators.get(key) for key in ("type_drift", "department_drift", "score_drift")]
    if SIGNIFICANT in drifts or _f1_dropped(indicators.get("f1"), indicators.get("reference_f1")):
        return RETRAIN
    unseen = indicators.get("unseen_share")
    if (
        MODERATE in drifts
        or (unseen is not None and unseen > UNSEEN_ALERT)
        or _flagged_shift(indicators.get("flagged_share"), indicators.get("reference_flagged_share"))
    ):
        return WATCH
    return STABLE


def simulate_operational_frame(reference, start, rows=300, shifted_type=None, shift_share=0.5, seed=0):
    """A batch of invented emergencies drawn from the reference rows, dated from start."""
    rng = np.random.default_rng(seed)
    shifted = round(rows * shift_share) if shifted_type else 0
    positions = rng.choice(len(reference), rows - shifted)
    if shifted:
        pool = np.flatnonzero(reference["event_type"].to_numpy() == shifted_type)
        if not len(pool):
            raise ValueError(f"no reference rows of type {shifted_type}")
        positions = np.concatenate([rng.choice(pool, shifted), positions])
    sample = reference.iloc[rng.permutation(positions)].reset_index(drop=True)
    offsets = np.linspace(0, SIMULATED_DAYS - 1, rows).round().astype(int)
    sample["reference"] = [f"simulated:{index}" for index in range(rows)]
    sample["occurred_on"] = [start + timedelta(days=int(offset)) for offset in offsets]
    return sample[list(FRAME_COLUMNS)]
