from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.features import FRAME_COLUMNS, IMPACT_VARIABLES

ACTIONS = {
    "Flood": ["activate_municipal_council", "evacuate_population"],
    "Wildfire": ["deploy_fire_brigade"],
    "Landslide": ["deploy_heavy_machinery", "clear_roads"],
}


def make_synthetic_frame(rows: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    records = []
    for i in range(rows):
        event_type = ["Flood", "Wildfire", "Landslide"][i % 3]
        department = ["05", "25", "68"][(i // 3) % 3]
        municipality = department + ["001", "002", "003"][(i // 9) % 3]
        record = dict.fromkeys(IMPACT_VARIABLES, 0.0)
        if event_type == "Flood":
            people = int(rng.integers(0, 120))
            record.update(
                people_affected=float(people),
                families_affected=float(people // 4),
                homes_damaged=float(people // 10),
            )
        elif event_type == "Wildfire":
            record["hectares"] = float(rng.integers(0, 60))
        else:
            record["roads_damaged"] = float(rng.integers(0, 3))
            record["homes_damaged"] = float(rng.integers(0, 5))
        record.update(
            reference=f"syn:{i}",
            occurred_on=date(2025, 1, 1) + timedelta(days=i * 365 // rows),
            event_type=event_type,
            department=department,
            municipality=municipality,
            has_impact=True,
            action_codes=list(ACTIONS[event_type]),
            is_high_impact=bool(
                record["people_affected"] >= 80
                or record["hectares"] >= 50
                or (event_type == "Flood" and municipality == "05001")
            ),
        )
        records.append(record)
    return pd.DataFrame(records, columns=list(FRAME_COLUMNS))


@pytest.fixture
def synthetic_frame() -> pd.DataFrame:
    return make_synthetic_frame()
