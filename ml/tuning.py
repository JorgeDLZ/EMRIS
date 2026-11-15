import pandas as pd

from ml.impact import DEFAULT_PARAMS, GRADIENT_BOOSTING, LOGISTIC_REGRESSION, cross_validate_impact

IMPACT_GRID = {
    LOGISTIC_REGRESSION: [{"C": 0.1}, {"C": 0.3}, {"C": 1.0}, {"C": 3.0}],
    GRADIENT_BOOSTING: [
        {"learning_rate": 0.05, "max_depth": 3},
        {"learning_rate": 0.1, "max_depth": 3},
        {"learning_rate": 0.05, "max_depth": None},
        {"learning_rate": 0.1, "max_depth": None},
    ],
}
COLUMNS = ["kind", "params", "pr_auc_mean", "pr_auc_std", "is_default"]


def _label(params):
    return ", ".join(f"{name}={value}" for name, value in params.items())


def tune_impact(frame):
    rows = []
    for kind, grid in IMPACT_GRID.items():
        for params in grid:
            result = cross_validate_impact(frame, kind, params)
            rows.append(
                {
                    "kind": kind,
                    "params": _label(params),
                    "pr_auc_mean": result["pr_auc_mean"],
                    "pr_auc_std": result["pr_auc_std"],
                    "is_default": params == DEFAULT_PARAMS[kind],
                }
            )
    table = pd.DataFrame(rows, columns=COLUMNS)
    return table.sort_values("pr_auc_mean", ascending=False, kind="stable").reset_index(drop=True)
