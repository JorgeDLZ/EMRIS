import ast
import subprocess
import sys
from pathlib import Path

import pandas as pd

from ml.data import clean_ungrd, high_impact_mask, parse_number

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

COLUMNS = [
    "FECHA", "DEPARTAMENTO", "MUNICIPIO", "EVENTO", "FALLECIDOS", "HERIDOS",
    "DESAPARECIDOS", "PERSONAS", "FAMILIAS", "VIVIENDAS DESTRUIDAS",
    "VIVIVIENDAS AVERIADAS", "VIAS", "PPUENTES VEHICULARES",
    "PPUENTES PEATONALES", "HECTAREAS", "COMENTARIOS", "CODIGO EMERGENCIA",
]


def write_csv(path, rows):
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame.to_csv(path, index=False, quoting=1)
    return path


def row(**overrides):
    base = {column: "0" for column in COLUMNS}
    base.update(
        FECHA="2025 Jun 06 12:00:00 AM",
        DEPARTAMENTO="ANTIOQUIA",
        MUNICIPIO="MEDELLIN",
        EVENTO="INUNDACION",
        COMENTARIOS="No Registra",
    )
    base.update(overrides)
    return [base[column] for column in COLUMNS]


def test_parse_number():
    assert parse_number("20,045") == 20045.0
    assert parse_number("No Registra") == 0.0
    assert parse_number("") == 0.0


def test_high_impact_rule_on_synthetic_rows():
    frame = pd.DataFrame(
        {
            "event_type": ["Flood"] * 12 + ["Wildfire"] * 2,
            "deceased": [0.0] * 14,
            "injured": [0.0] * 14,
            "missing": [0.0] * 14,
            "homes_destroyed": [0.0] * 14,
            "people_affected": [0.0] * 14,
            "hectares": [0.0] * 14,
        }
    )
    frame.loc[0, "deceased"] = 1
    frame.loc[1, "injured"] = 1
    frame.loc[2, "missing"] = 1
    frame.loc[3, "homes_destroyed"] = 1
    frame.loc[4:10, "people_affected"] = [1, 2, 3, 4, 5, 6, 7]
    frame.loc[11, "hectares"] = 50
    frame.loc[12, "hectares"] = 10
    frame.loc[13, "hectares"] = 10

    mask = high_impact_mask(frame)

    assert mask[0] and mask[1] and mask[2] and mask[3]
    assert mask[10] and not mask[9]
    assert mask[11]
    assert mask[12] and mask[13]
    assert not mask[4:9].any()


def test_high_impact_percentile_ignores_zero_rows():
    frame = pd.DataFrame(
        {
            "event_type": ["Flood"] * 12,
            "deceased": [0.0] * 12,
            "injured": [0.0] * 12,
            "missing": [0.0] * 12,
            "homes_destroyed": [0.0] * 12,
            "people_affected": [0.0] * 10 + [5.0, 10.0],
            "hectares": [0.0] * 12,
        }
    )

    mask = high_impact_mask(frame)

    assert mask.tolist() == [False] * 11 + [True]


def test_unknown_label_and_bad_date_are_discarded_with_reason(tmp_path):
    path = write_csv(
        tmp_path / "small.csv",
        [
            row(),
            row(EVENTO="No Registra"),
            row(EVENTO="UNKNOWN LABEL"),
            row(FECHA="not a date"),
        ],
    )

    result = clean_ungrd(path)

    assert len(result.records) == 1
    assert result.discarded["unknown event type"] == 2
    assert result.discarded["invalid date"] == 1
    assert result.records.iloc[0]["event_type"] == "Flood"


def test_department_level_row_has_no_municipality(tmp_path):
    path = write_csv(
        tmp_path / "small.csv",
        [row(MUNICIPIO="DEPARTAMENTO"), row(MUNICIPIO="Medellín")],
    )

    records = clean_ungrd(path).records

    assert pd.isna(records.iloc[0]["municipality_key"])
    assert records.iloc[0]["department_key"] == "ANTIOQUIA"
    assert records.iloc[1]["municipality_key"] == "MEDELLIN"
    assert records["source_row"].tolist() == [1, 2]


def test_ml_does_not_import_django():
    for module in (ROOT / "ml").glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name.split(".")[0] == "django" for name in names), module


def test_text_module_does_not_load_pandas():
    code = "import sys, ml.text; assert 'pandas' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_real_dataset_figures():
    result = clean_ungrd(DATA / "ungrd_emergencies_v2.csv")
    assert len(result.records) == 6505
    assert sum(result.discarded.values()) == 1
    assert result.records["is_high_impact"].sum() == 1046
    assert result.records["event_type"].nunique() == 28
    assert result.records["municipality_key"].isna().sum() == 24
    wildfire = result.records[result.records.event_type == "Wildfire"]
    assert wildfire[wildfire.hectares > 0].hectares.quantile(0.9) == 30.0
