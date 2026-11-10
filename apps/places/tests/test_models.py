import pytest
from django.db import IntegrityError, transaction

from apps.places.models import Department, Municipality


def make_department(code="05", name="ANTIOQUIA"):
    return Department.objects.create(code=code, name=name)


def test_department_save_sets_name_key(db):
    department = make_department(name="CÓRDOBA")
    assert department.name_key == "CORDOBA"


def test_municipality_save_sets_name_key(db):
    municipality = Municipality.objects.create(department=make_department(), name="Medellín")
    assert municipality.name_key == "MEDELLIN"


def test_municipality_name_key_unique_per_department(db):
    department = make_department()
    Municipality.objects.create(department=department, name="MEDELLÍN")
    with pytest.raises(IntegrityError), transaction.atomic():
        Municipality.objects.create(department=department, name="medellin")


def test_approved_queryset_excludes_pending(db):
    department = make_department()
    Municipality.objects.create(department=department, name="A", validation=Municipality.APPROVED)
    Municipality.objects.create(department=department, name="B", validation=Municipality.PENDING)
    assert list(Municipality.objects.approved().values_list("name", flat=True)) == ["A"]
