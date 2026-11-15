from datetime import timedelta

from django.utils import timezone

from apps.emergencies.models import Emergency, EmergencyType
from apps.places.models import Department, Municipality


def make_emergency(**extra):
    department = Department.objects.create(code="25", name="CUNDINAMARCA")
    municipality = Municipality.objects.create(department=department, code="25126", name="CAJICÁ")
    return Emergency.objects.create(
        emergency_type=EmergencyType.objects.create(name="Flood"),
        municipality=municipality,
        occurred_at=timezone.now() - timedelta(hours=1),
        **extra,
    )


def test_site_saved_in_capitals(db):
    assert make_emergency(site="  vereda  la balsa ").site == "VEREDA LA BALSA"


def test_description_keeps_its_casing(db):
    assert make_emergency(description="Water rising near the school").description == (
        "Water rising near the school"
    )
