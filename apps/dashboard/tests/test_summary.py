from datetime import timedelta

import pytest
from django.utils import timezone

from apps.dashboard.summary import PROFILE_PENDING, TOP_MUNICIPALITIES, emergency_summary
from apps.emergencies.models import CLOSED, IN_RESPONSE, REPORTED, Emergency, EmergencyType
from apps.intelligence.models import PROFILES, ModelVersion, Prediction
from apps.places.models import Department, Municipality


@pytest.fixture
def department(db):
    return Department.objects.create(code="05", name="ANTIOQUIA")


@pytest.fixture
def municipality(department):
    return Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")


@pytest.fixture
def flood(db):
    return EmergencyType.objects.create(name="Flood")


@pytest.fixture
def make_emergency(municipality, flood):
    def build(status=REPORTED, **extra):
        values = {
            "emergency_type": flood,
            "municipality": municipality,
            "occurred_at": timezone.now() - timedelta(hours=1),
            "status": status,
        }
        values.update(extra)
        return Emergency.objects.create(**values)

    return build


@pytest.fixture
def profile_version(db):
    return ModelVersion.objects.create(
        component=PROFILES, version=1, artifact=b"", primary_metric="silhouette",
        score=0.5, metrics={}, trained_on={}, library_versions={},
    )


def predict_profile(emergency, version, profile):
    return Prediction.objects.create(
        emergency=emergency, model_version=version, component=PROFILES, output={"profile": profile}
    )


def test_summary_counts_active_and_closed(make_emergency):
    for _ in range(3):
        make_emergency(REPORTED)
    make_emergency(IN_RESPONSE)
    for _ in range(2):
        make_emergency(CLOSED)
    summary = emergency_summary(Emergency.objects.all())
    assert summary["active"] == 4
    assert summary["closed"] == 2
    assert summary["by_status"] == [("Reported", 3), ("In response", 1), ("Controlled", 0)]


def test_summary_groups_by_type_and_municipality(make_emergency, flood, department):
    fire = EmergencyType.objects.create(name="Fire")
    make_emergency()
    make_emergency(emergency_type=fire)
    make_emergency(emergency_type=fire)
    make_emergency(status=CLOSED)
    for index in range(TOP_MUNICIPALITIES + 2):
        town = Municipality.objects.create(department=department, code=f"05{index + 100}", name=f"Town {index:02d}")
        for _ in range(index + 1):
            make_emergency(municipality=town)
    summary = emergency_summary(Emergency.objects.all())
    assert summary["by_type"][0] == ("Flood", 1 + sum(range(1, TOP_MUNICIPALITIES + 3)))
    assert summary["by_type"][1] == ("Fire", 2)
    assert len(summary["by_municipality"]) == TOP_MUNICIPALITIES
    counts = [row[2] for row in summary["by_municipality"]]
    assert counts == sorted(counts, reverse=True)
    assert summary["by_municipality"][0] == ("Town 11", "ANTIOQUIA", 12)


def test_ties_break_by_name(make_emergency, department):
    zebra = EmergencyType.objects.create(name="Zebra")
    apple = EmergencyType.objects.create(name="Apple")
    make_emergency(emergency_type=zebra)
    make_emergency(emergency_type=apple)
    summary = emergency_summary(Emergency.objects.filter(emergency_type__in=[zebra, apple]))
    assert [row[0] for row in summary["by_type"]] == ["Apple", "Zebra"]


def test_profile_counts_use_latest_prediction(make_emergency, profile_version):
    predicted = make_emergency()
    make_emergency()
    predict_profile(predicted, profile_version, "Old profile")
    predict_profile(predicted, profile_version, "New profile")
    summary = emergency_summary(Emergency.objects.all())
    assert summary["by_profile"] == [("New profile", 1), (PROFILE_PENDING, 1)]


def test_profile_ignores_closed_emergencies(make_emergency, profile_version):
    closed = make_emergency(CLOSED)
    predict_profile(closed, profile_version, "Closed profile")
    assert emergency_summary(Emergency.objects.all())["by_profile"] == []


def test_empty_summary(db):
    summary = emergency_summary(Emergency.objects.all())
    assert summary["active"] == 0
    assert summary["closed"] == 0
    assert summary["by_status"] == [("Reported", 0), ("In response", 0), ("Controlled", 0)]
    assert summary["by_type"] == []
    assert summary["by_municipality"] == []
    assert summary["by_profile"] == []
