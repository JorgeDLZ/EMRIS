import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.emergencies.models import Emergency, EmergencyType
from apps.intelligence.models import ModelVersion, Prediction
from apps.places.models import Department, Municipality


def make_version(component="impact", version=1, is_active=False):
    return ModelVersion.objects.create(
        component=component,
        version=version,
        artifact=b"artifact",
        primary_metric="mae",
        score=1.0,
        metrics={},
        trained_on={},
        library_versions={},
        is_active=is_active,
    )


def test_only_one_active_version_per_component(db):
    make_version("impact", 1, is_active=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version("impact", 2, is_active=True)
    make_version("profiles", 1, is_active=True)
    assert ModelVersion.objects.filter(is_active=True).count() == 2


def test_version_numbers_are_unique_per_component(db):
    make_version("impact", 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_version("impact", 1)


def test_prediction_keeps_its_version(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    emergency = Emergency.objects.create(
        emergency_type=EmergencyType.objects.create(name="Flood"),
        municipality=municipality,
        occurred_at=timezone.now(),
    )
    version = make_version()
    Prediction.objects.create(
        emergency=emergency, model_version=version, component="impact", output={}
    )
    with pytest.raises(ProtectedError):
        version.delete()


def test_str_uses_component_label(db):
    assert str(make_version("impact", 2)) == "Impact estimator v2"
