from pathlib import Path

import pandas as pd
from django.core.management import call_command

from apps.emergencies.models import EmergencyType
from apps.history.models import UngrdRecord
from apps.history.services import load_baseline
from apps.places.models import Department, Municipality

DATA = Path(__file__).resolve().parents[3] / "data"
UNGRD = DATA / "ungrd_emergencies_v2.csv"
DIVIPOLA = DATA / "divipola_dane.csv"

COLUMNS = [
    "FECHA", "DEPARTAMENTO", "MUNICIPIO", "EVENTO", "FALLECIDOS", "HERIDOS",
    "DESAPARECIDOS", "PERSONAS", "FAMILIAS", "VIVIENDAS DESTRUIDAS",
    "VIVIVIENDAS AVERIADAS", "VIAS", "PPUENTES VEHICULARES",
    "PPUENTES PEATONALES", "HECTAREAS", "COMENTARIOS", "CODIGO EMERGENCIA",
]


def write_ungrd(path, rows):
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False, quoting=1)
    return path


def ungrd_row(**overrides):
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


def test_real_files_load_and_reload(db):
    first = load_baseline(UNGRD, DIVIPOLA)
    assert first.records == 6505 and sum(first.discarded.values()) == 1
    assert first.types_created == 28
    second = load_baseline(UNGRD, DIVIPOLA)
    assert second.types_created == 0
    assert UngrdRecord.objects.count() == 6505
    assert UngrdRecord.objects.filter(is_high_impact=True).count() == 1046
    assert UngrdRecord.objects.filter(municipality__isnull=True).count() == 24
    assert UngrdRecord.objects.filter(municipality__code="11001").count() == 22


def test_unresolved_municipality_is_discarded_with_reason(db, tmp_path):
    path = write_ungrd(
        tmp_path / "small.csv",
        [ungrd_row(), ungrd_row(MUNICIPIO="NOWHERE VILLE")],
    )
    report = load_baseline(path, DIVIPOLA)
    assert report.records == 1
    assert report.discarded["unknown municipality: ANTIOQUIA/NOWHERE VILLE"] == 1
    assert UngrdRecord.objects.count() == 1


def test_unresolved_department_level_row_is_discarded_with_reason(db, tmp_path):
    path = write_ungrd(
        tmp_path / "small.csv",
        [ungrd_row(), ungrd_row(DEPARTAMENTO="NOWHERE", MUNICIPIO="DEPARTAMENTO")],
    )
    report = load_baseline(path, DIVIPOLA)
    assert report.records == 1
    assert report.discarded["unknown department: NOWHERE"] == 1
    assert UngrdRecord.objects.count() == 1


def test_record_fields_are_stored_as_plain_values(db, tmp_path):
    path = write_ungrd(
        tmp_path / "small.csv",
        [
            ungrd_row(FALLECIDOS="2", HECTAREAS="12.5", PERSONAS="1,200"),
            ungrd_row(MUNICIPIO="DEPARTAMENTO"),
        ],
    )
    load_baseline(path, DIVIPOLA)
    municipal, departmental = UngrdRecord.objects.order_by("source_row")
    assert municipal.municipality.code == "05001"
    assert municipal.department.code == "05"
    assert municipal.emergency_type.name == "Flood"
    assert municipal.deceased == 2 and municipal.people_affected == 1200
    assert municipal.hectares == 12.5
    assert municipal.is_high_impact is True
    assert municipal.action_codes == []
    assert departmental.municipality is None
    assert departmental.department.code == "05"


def test_reload_keeps_deactivated_type_and_user_municipality(db):
    load_baseline(UNGRD, DIVIPOLA)
    EmergencyType.objects.filter(name="Flood").update(is_active=False)
    department = Department.objects.get(code="05")
    user_municipality = Municipality.objects.create(
        department=department, name="Villa Nueva Test", source=Municipality.USER
    )
    load_baseline(UNGRD, DIVIPOLA)
    assert EmergencyType.objects.get(name="Flood").is_active is False
    assert Municipality.objects.filter(pk=user_municipality.pk).exists()


def test_command_prints_summary(db, tmp_path, capsys):
    path = write_ungrd(
        tmp_path / "small.csv",
        [ungrd_row(), ungrd_row(MUNICIPIO="NOWHERE VILLE")],
    )
    call_command("load_baseline", ungrd=str(path), divipola=str(DIVIPOLA))
    output = capsys.readouterr().out
    assert "Records loaded: 1" in output
    assert "Emergency types created: 28" in output
    assert "unknown municipality: ANTIOQUIA/NOWHERE VILLE: 1" in output
