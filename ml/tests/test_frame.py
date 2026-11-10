from pathlib import Path

import pandas as pd

from ml.data import load_frame, municipality_centroids, read_divipola
from ml.features import FRAME_COLUMNS
from ml.tests.test_data import row, write_csv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

DIVIPOLA_COLUMNS = [
    "department_code", "department_name", "municipality_code", "municipality_name",
    "type", "longitude", "latitude",
]


def write_divipola(path, rows):
    pd.DataFrame(rows, columns=DIVIPOLA_COLUMNS).to_csv(path, index=False)
    return path


def place(department_code, department, code, name):
    return [department_code, department, code, name, "Municipio", "-75.0", "6.0"]


def test_real_frame_figures():
    frame = load_frame(DATA / "ungrd_emergencies_v2.csv", DATA / "divipola_dane.csv")
    assert list(frame.columns) == list(FRAME_COLUMNS)
    assert len(frame) == 6505 and frame["reference"].is_unique
    assert (frame["municipality"] == "").sum() == 24
    assert (frame["municipality"] == "11001").sum() == 22
    assert frame["is_high_impact"].sum() == 1046
    assert frame["has_impact"].all()


def test_same_name_in_three_departments_stays_apart(tmp_path):
    divipola = write_divipola(
        tmp_path / "divipola.csv",
        [
            place("19", "CAUCA", "19100", "BOLÍVAR"),
            place("68", "SANTANDER", "68101", "BOLÍVAR"),
            place("76", "VALLE DEL CAUCA", "76100", "BOLÍVAR"),
        ],
    )
    ungrd = write_csv(
        tmp_path / "ungrd.csv",
        [
            row(DEPARTAMENTO="CAUCA", MUNICIPIO="BOLIVAR"),
            row(DEPARTAMENTO="SANTANDER", MUNICIPIO="BOLIVAR"),
            row(DEPARTAMENTO="VALLE DEL CAUCA", MUNICIPIO="BOLIVAR"),
        ],
    )
    frame = load_frame(ungrd, divipola)
    assert list(frame["municipality"]) == ["19100", "68101", "76100"]
    assert list(frame["department"]) == ["19", "68", "76"]
    assert list(frame["reference"]) == ["ungrd:1", "ungrd:2", "ungrd:3"]


def test_department_level_row(tmp_path):
    divipola = write_divipola(tmp_path / "divipola.csv", [place("27", "CHOCÓ", "27001", "QUIBDÓ")])
    ungrd = write_csv(tmp_path / "ungrd.csv", [row(DEPARTAMENTO="CHOCO", MUNICIPIO="DEPARTAMENTO")])
    frame = load_frame(ungrd, divipola)
    assert list(frame["department"]) == ["27"]
    assert list(frame["municipality"]) == [""]


def test_unresolved_row_is_dropped(tmp_path):
    divipola = write_divipola(tmp_path / "divipola.csv", [place("05", "ANTIOQUIA", "05001", "MEDELLÍN")])
    ungrd = write_csv(
        tmp_path / "ungrd.csv",
        [row(MUNICIPIO="NOWHERE"), row(MUNICIPIO="MEDELLIN")],
    )
    frame = load_frame(ungrd, divipola)
    assert list(frame["municipality"]) == ["05001"]
    assert list(frame["reference"]) == ["ungrd:2"]


def test_centroids():
    centroids = municipality_centroids(read_divipola(DATA / "divipola_dane.csv"))
    assert len(centroids) == 1122
    assert centroids["05001"] == (6.246631, -75.581775)
