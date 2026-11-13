import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from apps.emergencies.models import CLOSED, REPORTED, Emergency, EmergencyType, Impact
from apps.history.services import load_baseline
from apps.intelligence.frames import (
    build_training_frame,
    emergency_frame,
    municipality_id,
    seismic_inputs,
)
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan
from apps.seismic.models import SeismicEvent
from ml.features import FRAME_COLUMNS
from ml.seismic import SeismicFeatures

DATA = Path(__file__).resolve().parents[3] / "data"
UNGRD = DATA / "ungrd_emergencies_v2.csv"
DIVIPOLA = DATA / "divipola_dane.csv"


def make_emergency(status=CLOSED, code="05001", occurred_at=None, **municipality_fields):
    department, _ = Department.objects.get_or_create(code="05", defaults={"name": "ANTIOQUIA"})
    municipality = Municipality.objects.create(
        department=department,
        code=code,
        name=municipality_fields.pop("name", "Medellin"),
        **municipality_fields,
    )
    emergency_type, _ = EmergencyType.objects.get_or_create(name="Flood")
    return Emergency.objects.create(
        emergency_type=emergency_type,
        municipality=municipality,
        occurred_at=occurred_at or datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
        status=status,
    )


def test_frame_from_loaded_baseline_matches_files(db):
    load_baseline(UNGRD, DIVIPOLA)
    frame = build_training_frame()
    assert len(frame) == 6505
    assert list(frame.columns) == list(FRAME_COLUMNS)
    assert int(frame["is_high_impact"].sum()) == 1046
    assert int((frame["municipality"] == "").sum()) == 24
    assert frame["reference"].is_unique


def test_closed_emergency_with_impact_is_included(db):
    emergency = make_emergency()
    Impact.objects.create(emergency=emergency, people_affected=40, hectares=1.5)
    plan = ActionPlan.objects.create(emergency=emergency)
    for code in ["clear_roads", "deploy_fire_brigade", ""]:
        Action.objects.create(plan=plan, description="step", code=code)
    frame = build_training_frame()
    assert list(frame["reference"]) == [f"emergency:{emergency.pk}"]
    row = frame.iloc[0]
    assert row["action_codes"] == ["deploy_fire_brigade", "clear_roads"]
    assert row["municipality"] == "05001" and row["department"] == "05"
    assert row["event_type"] == "Flood" and row["has_impact"]
    assert row["people_affected"] == 40 and row["hectares"] == 1.5
    assert row["is_high_impact"]


def test_occurred_on_uses_the_local_date(db):
    emergency = make_emergency(occurred_at=datetime(2026, 3, 2, 3, 0, tzinfo=timezone.utc))
    Impact.objects.create(emergency=emergency)
    frame = build_training_frame()
    assert str(frame.iloc[0]["occurred_on"]) == "2026-03-01"


def test_open_or_impactless_emergencies_are_excluded(db):
    open_emergency = make_emergency(status=REPORTED, code="05001")
    Impact.objects.create(emergency=open_emergency, people_affected=5)
    make_emergency(status=CLOSED, code="05002", name="Bello")
    frame = build_training_frame()
    assert frame.empty
    assert list(frame.columns) == list(FRAME_COLUMNS)


def test_user_municipality_id(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    official = Municipality.objects.create(department=department, code="05001", name="Medellin")
    local = Municipality.objects.create(
        department=department, name="Vereda Nueva", source=Municipality.USER
    )
    assert municipality_id(official) == "05001"
    assert municipality_id(local) == f"user-{local.pk}"
    assert municipality_id(None) == ""


def test_emergency_frame_without_impact(db):
    emergency = make_emergency(status=REPORTED)
    frame = emergency_frame(emergency)
    assert len(frame) == 1 and list(frame.columns) == list(FRAME_COLUMNS)
    row = frame.iloc[0]
    assert not row["has_impact"] and not row["is_high_impact"]
    assert row["people_affected"] == 0 and row["hectares"] == 0
    assert row["action_codes"] == []


def test_seismic_inputs_cover_every_municipality(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    Municipality.objects.create(
        department=department, code="05001", name="Medellin", latitude=6.25, longitude=-75.56
    )
    Municipality.objects.create(department=department, code="05002", name="Abejorral")
    SeismicEvent.objects.create(
        sgc_id="a", event_time=datetime(2026, 1, 1, tzinfo=timezone.utc), magnitude=4.5,
        depth_km=10.0, latitude=6.25, longitude=-75.56, place="x",
    )
    features = seismic_inputs()
    assert set(features) == {"05001", "05002"}
    assert features["05001"] == SeismicFeatures(1, 4.5)
    assert features["05002"] == SeismicFeatures(0, 0.0)


def test_importing_frames_does_not_load_pandas_or_sklearn():
    script = (
        "import os, sys, django\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
        "django.setup()\n"
        "import apps.intelligence.frames\n"
        "loaded = [name for name in ('pandas', 'sklearn') if name in sys.modules]\n"
        "sys.exit(','.join(loaded) or 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
