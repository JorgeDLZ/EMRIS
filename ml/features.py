import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder

IMPACT_VARIABLES = (
    "deceased", "injured", "missing", "people_affected", "families_affected",
    "homes_destroyed", "homes_damaged", "roads_damaged", "hectares",
)
REPORT_COLUMNS = ("occurred_on", "event_type", "department", "municipality")
FRAME_COLUMNS = (
    "reference", *REPORT_COLUMNS, *IMPACT_VARIABLES,
    "has_impact", "action_codes", "is_high_impact",
)
MIN_CATEGORY_COUNT = 3


def validate_frame(frame: pd.DataFrame, required=FRAME_COLUMNS) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"frame is missing columns: {', '.join(missing)}")


def report_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    months = pd.to_datetime(frame["occurred_on"]).dt.month.to_numpy()
    angle = 2 * np.pi * (months - 1) / 12
    return pd.DataFrame(
        {
            "event_type": frame["event_type"],
            "department": frame["department"],
            "municipality": frame["municipality"],
            "month_sin": np.sin(angle),
            "month_cos": np.cos(angle),
        },
        index=frame.index,
    )


def _one_hot(dense: bool, handle_unknown: str) -> OneHotEncoder:
    return OneHotEncoder(
        handle_unknown=handle_unknown,
        min_frequency=MIN_CATEGORY_COUNT,
        sparse_output=not dense,
    )


def impact_preprocessor(dense: bool = False) -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("event_type", _one_hot(dense, "infrequent_if_exist"), ["event_type"]),
            ("department", _one_hot(dense, "ignore"), ["department"]),
            ("municipality", _one_hot(dense, "ignore"), ["municipality"]),
            ("month", "passthrough", ["month_sin", "month_cos"]),
        ]
    )


def log_impact(frame: pd.DataFrame) -> np.ndarray:
    return np.log1p(frame[list(IMPACT_VARIABLES)].to_numpy(dtype=float))


def recorded_impact(frame: pd.DataFrame) -> np.ndarray:
    return (frame[list(IMPACT_VARIABLES)].to_numpy(dtype=float) > 0).any(axis=1)
