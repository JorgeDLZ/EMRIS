from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    silhouette_score,
)

TEST_MONTHS = 3
DEFAULT_THRESHOLD = 0.5


@dataclass(frozen=True)
class SplitDates:
    validation_start: date
    test_start: date


def split_dates(occurred_on):
    months = pd.to_datetime(occurred_on).dt.to_period("M")
    first, last = months.min(), months.max()
    span = (last - first).n + 1
    if span < TEST_MONTHS + 2:
        raise ValueError(
            f"need at least {TEST_MONTHS + 2} months of data to evaluate; got {span}"
        )
    return SplitDates(
        validation_start=(last - TEST_MONTHS).to_timestamp().date(),
        test_start=(last - (TEST_MONTHS - 1)).to_timestamp().date(),
    )


def temporal_masks(frame, split):
    dates = pd.to_datetime(frame["occurred_on"])
    validation_start = pd.Timestamp(split.validation_start)
    test_start = pd.Timestamp(split.test_start)
    return {
        "fit": dates < validation_start,
        "validation": (dates >= validation_start) & (dates < test_start),
        "train": dates < test_start,
        "test": dates >= test_start,
    }


def best_f1_threshold(y_true, scores):
    if not np.any(y_true):
        return DEFAULT_THRESHOLD
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(
        2 * precision[:-1] * recall[:-1], denominator,
        out=np.zeros_like(denominator), where=denominator > 0,
    )
    return float(thresholds[int(np.argmax(f1))])


def classification_metrics(y_true, scores, threshold):
    predicted = scores >= threshold
    has_positive = bool(np.any(y_true))
    return {
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, scores)) if has_positive else 0.0,
    }


def safe_silhouette(X, labels):
    distinct = len(set(labels))
    if distinct < 2 or distinct >= len(labels):
        return -1.0
    return float(silhouette_score(X, labels))


def describe_frame(frame):
    return {
        "rows": int(len(frame)),
        "start": str(min(frame["occurred_on"])),
        "end": str(max(frame["occurred_on"])),
    }


@dataclass
class TrainResult:
    component: str
    model: object
    metrics: dict
    primary_metric: str
    trained_on: dict

    @property
    def score(self):
        return float(self.metrics[self.primary_metric])
