from pathlib import Path

import pytest
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.roles import OPERATOR, RISK_MANAGER
from apps.places.models import Department, Municipality
from apps.places.services import (
    DuplicateMunicipality,
    approve_municipality,
    find_similar,
    load_divipola,
    register_municipality,
    reject_municipality,
)

DIVIPOLA_PATH = Path(__file__).resolve().parents[3] / "data" / "divipola_dane.csv"


def make_user(username, role):
    user = User.objects.create_user(username, password="pass-12345")
    user.groups.add(Group.objects.get(name=role))
    return user


def make_medellin():
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    return department, municipality


def test_load_divipola_real_file_is_idempotent(db):
    assert load_divipola(DIVIPOLA_PATH) == 1122
    assert load_divipola(DIVIPOLA_PATH) == 1122
    assert Department.objects.count() == 33
    assert Municipality.objects.count() == 1122
    medellin = Municipality.objects.get(code="05001")
    assert medellin.name == "MEDELLÍN"
    assert medellin.department.code == "05"
    assert medellin.latitude is not None and medellin.longitude is not None
    assert medellin.source == Municipality.OFFICIAL
    assert medellin.validation == Municipality.APPROVED


def test_load_keeps_user_municipalities(db):
    load_divipola(DIVIPOLA_PATH)
    department = Department.objects.get(code="05")
    user_municipality = register_municipality(department, "Villa Nueva Test", make_user("op", OPERATOR))
    load_divipola(DIVIPOLA_PATH)
    reloaded = Municipality.objects.get(pk=user_municipality.pk)
    assert reloaded.name == "Villa Nueva Test"
    assert reloaded.source == Municipality.USER
    assert reloaded.validation == Municipality.PENDING
    assert reloaded.code is None


def test_operator_registration_is_pending(db):
    department, _ = make_medellin()
    operator = make_user("op", OPERATOR)
    municipality = register_municipality(department, "Nuevo Lugar", operator)
    assert municipality.source == Municipality.USER
    assert municipality.validation == Municipality.PENDING
    assert municipality.created_by == operator
    assert municipality.code is None


def test_risk_manager_registration_is_approved(db):
    department, _ = make_medellin()
    municipality = register_municipality(department, "Nuevo Lugar", make_user("rm", RISK_MANAGER))
    assert municipality.validation == Municipality.APPROVED
    assert municipality.source == Municipality.USER


def test_accent_and_case_duplicate_rejected(db):
    department, _ = make_medellin()
    with pytest.raises(DuplicateMunicipality):
        register_municipality(department, "medellin", make_user("op", OPERATOR))


def test_same_name_in_other_department_allowed(db):
    make_medellin()
    other = Department.objects.create(code="08", name="ATLÁNTICO")
    municipality = register_municipality(other, "Medellín", make_user("op", OPERATOR))
    assert municipality.department == other


def test_find_similar_catches_typo(db):
    department, medellin = make_medellin()
    other = Department.objects.create(code="08", name="ATLÁNTICO")
    Municipality.objects.create(department=other, code="08001", name="MEDELLÍN")
    assert find_similar(department, "Medelin") == [medellin]


def test_approve_municipality(db):
    department, _ = make_medellin()
    municipality = register_municipality(department, "Nuevo Lugar", make_user("op", OPERATOR))
    approve_municipality(municipality)
    municipality.refresh_from_db()
    assert municipality.validation == Municipality.APPROVED


def test_reject_deletes_pending(db):
    department, _ = make_medellin()
    municipality = register_municipality(department, "Nuevo Lugar", make_user("op", OPERATOR))
    reject_municipality(municipality)
    assert not Municipality.objects.filter(pk=municipality.pk).exists()


def test_reject_refuses_approved(db):
    _, medellin = make_medellin()
    with pytest.raises(ValueError):
        reject_municipality(medellin)
    assert Municipality.objects.filter(pk=medellin.pk).exists()
