from ml.tuning import tune_impact


def test_tune_impact_covers_the_grid_sorted(synthetic_frame):
    table = tune_impact(synthetic_frame)
    assert len(table) == 8
    assert list(table.columns) == ["kind", "params", "pr_auc_mean", "pr_auc_std", "is_default"]
    assert table["pr_auc_mean"].is_monotonic_decreasing
    assert table["is_default"].sum() == 2
    assert {"C=0.3", "C=1.0"} <= set(table["params"])
