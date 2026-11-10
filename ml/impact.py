import calendar
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from ml.evaluation import (
    TrainResult,
    best_f1_threshold,
    classification_metrics,
    describe_frame,
    split_dates,
    temporal_masks,
)
from ml.features import (
    REPORT_COLUMNS,
    impact_preprocessor,
    report_time_features,
    validate_frame,
)

COMPONENT = "impact"
PRIMARY_METRIC = "f1"
LOGISTIC_REGRESSION = "logistic_regression"
GRADIENT_BOOSTING = "gradient_boosting"
BASELINE = "baseline"
TIE_MARGIN = 0.02
TOP_FACTORS = 3
DEPARTMENT_LEVEL = "Department level"
FACTOR_LABELS = {
    "event_type": "Event type",
    "department": "Department",
    "municipality": "Municipality",
    "month": "Month",
}
REQUIRED_COLUMNS = (*REPORT_COLUMNS, "is_high_impact")


@dataclass(frozen=True)
class Factor:
    feature: str
    value: str
    weight: float


class TypeLocationBaseline:
    def fit(self, frame):
        data = pd.DataFrame(
            {
                "event_type": np.asarray(frame["event_type"], dtype=object),
                "department": np.asarray(frame["department"], dtype=object),
                "municipality": np.asarray(frame["municipality"], dtype=object),
                "target": np.asarray(frame["is_high_impact"], dtype=float),
            }
        )
        located = data[data["municipality"] != ""]
        self.global_rate_ = float(data["target"].mean())
        self.type_rate_ = data.groupby("event_type")["target"].mean().to_dict()
        self.department_rate_ = (
            data.groupby(["event_type", "department"])["target"].mean().to_dict()
        )
        self.municipality_rate_ = (
            located.groupby(["event_type", "municipality"])["target"].mean().to_dict()
        )
        return self

    def score(self, frame):
        rows = zip(
            np.asarray(frame["event_type"], dtype=object),
            np.asarray(frame["department"], dtype=object),
            np.asarray(frame["municipality"], dtype=object),
        )
        return np.array([self._rate(*row) for row in rows], dtype=float)

    def _rate(self, event_type, department, municipality):
        if municipality != "" and (event_type, municipality) in self.municipality_rate_:
            return self.municipality_rate_[(event_type, municipality)]
        if (event_type, department) in self.department_rate_:
            return self.department_rate_[(event_type, department)]
        return self.type_rate_.get(event_type, self.global_rate_)


def fit_pipeline(kind, frame):
    if kind == GRADIENT_BOOSTING:
        model = HistGradientBoostingClassifier(class_weight="balanced", random_state=0)
    else:
        model = LogisticRegression(class_weight="balanced", max_iter=2000)
    pipeline = Pipeline(
        [
            ("features", impact_preprocessor(dense=kind == GRADIENT_BOOSTING)),
            ("model", model),
        ]
    )
    return pipeline.fit(report_time_features(frame), frame["is_high_impact"])


def choose_kind(f1_by_kind):
    margin = f1_by_kind[GRADIENT_BOOSTING] - f1_by_kind[LOGISTIC_REGRESSION]
    return GRADIENT_BOOSTING if margin > TIE_MARGIN else LOGISTIC_REGRESSION


def _factor_value(feature, row):
    if feature == "month":
        return calendar.month_name[pd.Timestamp(row["occurred_on"]).month]
    value = str(row[feature])
    if feature == "municipality" and value == "":
        return DEPARTMENT_LEVEL
    return value


def _top_factors(weights, row):
    ranked = sorted(weights.items(), key=lambda item: abs(item[1]), reverse=True)
    return [
        Factor(FACTOR_LABELS[feature], _factor_value(feature, row), float(weight))
        for feature, weight in ranked[:TOP_FACTORS]
    ]


@dataclass
class ImpactModel:
    kind: str
    pipeline: Pipeline
    threshold: float
    importance: dict | None

    def probability(self, frame):
        return self.pipeline.predict_proba(report_time_features(frame))[:, 1]

    def predict(self, frame):
        return self.probability(frame) >= self.threshold

    def explain(self, frame):
        rows = frame.reset_index(drop=True)
        if self.kind == GRADIENT_BOOSTING:
            return [_top_factors(self.importance, row) for _, row in rows.iterrows()]
        features = self.pipeline["features"]
        encoded = features.transform(report_time_features(rows))
        if hasattr(encoded, "toarray"):
            encoded = encoded.toarray()
        coefficients = self.pipeline["model"].coef_[0]
        slices = {
            name: indices
            for name, indices in features.output_indices_.items()
            if name != "remainder"
        }
        contributions = np.column_stack(
            [
                (encoded[:, indices] * coefficients[indices]).sum(axis=1)
                for indices in slices.values()
            ]
        )
        return [
            _top_factors(dict(zip(slices, weights)), row)
            for weights, (_, row) in zip(contributions, rows.iterrows())
        ]


def _group_importance(frame, pipeline, labels):
    features = report_time_features(frame)
    result = permutation_importance(
        pipeline,
        features,
        labels,
        n_repeats=5,
        random_state=0,
        scoring="average_precision",
    )
    by_column = dict(zip(features.columns, result.importances_mean))
    return {
        "event_type": float(by_column["event_type"]),
        "department": float(by_column["department"]),
        "municipality": float(by_column["municipality"]),
        "month": float(by_column["month_sin"] + by_column["month_cos"]),
    }


def _fit_candidate(name, part):
    if name == BASELINE:
        return TypeLocationBaseline().fit(part)
    return fit_pipeline(name, part)


def _candidate_scores(fitted, part):
    if isinstance(fitted, TypeLocationBaseline):
        return fitted.score(part)
    return fitted.predict_proba(report_time_features(part))[:, 1]


def train_impact(frame):
    validate_frame(frame, required=REQUIRED_COLUMNS)
    masks = temporal_masks(frame, split_dates(frame["occurred_on"]))
    labels = frame["is_high_impact"].to_numpy(dtype=bool)
    validation_labels = labels[masks["validation"].to_numpy()]
    test_labels = labels[masks["test"].to_numpy()]
    validation, test = frame[masks["validation"]], frame[masks["test"]]

    thresholds, test_metrics, train_fits = {}, {}, {}
    for name in (LOGISTIC_REGRESSION, GRADIENT_BOOSTING, BASELINE):
        fitted = _fit_candidate(name, frame[masks["fit"]])
        thresholds[name] = best_f1_threshold(
            validation_labels, _candidate_scores(fitted, validation)
        )
        train_fits[name] = _fit_candidate(name, frame[masks["train"]])
        test_metrics[name] = classification_metrics(
            test_labels, _candidate_scores(train_fits[name], test), thresholds[name]
        )

    kind = choose_kind(
        {
            LOGISTIC_REGRESSION: test_metrics[LOGISTIC_REGRESSION]["f1"],
            GRADIENT_BOOSTING: test_metrics[GRADIENT_BOOSTING]["f1"],
        }
    )
    importance = None
    if kind == GRADIENT_BOOSTING:
        importance = _group_importance(test, train_fits[GRADIENT_BOOSTING], test_labels)
    model = ImpactModel(kind, fit_pipeline(kind, frame), thresholds[kind], importance)
    chosen, baseline = test_metrics[kind], test_metrics[BASELINE]
    metrics = {
        "model": kind,
        "threshold": float(thresholds[kind]),
        "f1": chosen["f1"],
        "precision": chosen["precision"],
        "recall": chosen["recall"],
        "pr_auc": chosen["pr_auc"],
        "baseline_f1": baseline["f1"],
        "baseline_recall": baseline["recall"],
        "baseline_pr_auc": baseline["pr_auc"],
        "logistic_regression_f1": test_metrics[LOGISTIC_REGRESSION]["f1"],
        "gradient_boosting_f1": test_metrics[GRADIENT_BOOSTING]["f1"],
        "test_rows": int(masks["test"].sum()),
        "test_positives": int(test_labels.sum()),
    }
    return TrainResult(
        component=COMPONENT,
        model=model,
        metrics=metrics,
        primary_metric=PRIMARY_METRIC,
        trained_on=describe_frame(frame),
    )


def evaluate_impact(model, frame):
    validate_frame(frame, required=REQUIRED_COLUMNS)
    test = frame[temporal_masks(frame, split_dates(frame["occurred_on"]))["test"]]
    metrics = classification_metrics(
        test["is_high_impact"].to_numpy(dtype=bool),
        model.probability(test),
        model.threshold,
    )
    return {**metrics, "test_rows": int(len(test))}
