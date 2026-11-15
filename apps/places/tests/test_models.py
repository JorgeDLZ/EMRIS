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


def test_as_options_shape(db):
    department = make_department()
    medellin = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    assert Municipality.objects.all().as_options() == [[medellin.pk, "MEDELLÍN", department.pk, "05"]]


def test_as_options_ordered_by_name(db):
    department = make_department()
    Municipality.objects.create(department=department, name="ZARAGOZA")
    Municipality.objects.create(department=department, name="ABEJORRAL")
    assert [row[1] for row in Municipality.objects.all().as_options()] == ["ABEJORRAL", "ZARAGOZA"]


def test_names_saved_in_capitals(db):
    department = make_department(name="valle  del cauca")
    municipality = Municipality.objects.create(department=department, name=" cajicá   norte")
    assert department.name == "VALLE DEL CAUCA"
    assert municipality.name == "CAJICÁ NORTE"


def test_resaving_capitalized_name_changes_nothing(db):
    municipality = Municipality.objects.create(department=make_department(), name="MEDELLÍN")
    municipality.save()
    municipality.refresh_from_db()
    assert municipality.name == "MEDELLÍN"
    assert municipality.name_key == "MEDELLIN"
