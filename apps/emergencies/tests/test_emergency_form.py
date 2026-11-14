from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import OPERATOR, RISK_MANAGER
from apps.emergencies.forms import EmergencyForm
from apps.emergencies.models import Emergency, EmergencyType
from apps.emergencies.tests.test_emergency_views import make_user
from apps.places.models import Department, Municipality

WRONG_DEPARTMENT = "Choose a municipality in the selected department."


@pytest.fixture
def places(db):
    antioquia = Department.objects.create(code="05", name="ANTIOQUIA")
    cundinamarca = Department.objects.create(code="25", name="CUNDINAMARCA")
    return {
        "antioquia": antioquia,
        "cundinamarca": cundinamarca,
        "medellin": Municipality.objects.create(department=antioquia, code="05001", name="MEDELLÍN"),
        "cajica": Municipality.objects.create(department=cundinamarca, code="25126", name="CAJICÁ"),
    }


@pytest.fixture
def flood(db):
    return EmergencyType.objects.create(name="Flood")


def data(department, municipality, flood):
    return {
        "emergency_type": flood.pk,
        "department": department.pk,
        "municipality": municipality.pk,
        "site": "",
        "occurred_at": timezone.localtime(timezone.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        "description": "",
    }


def test_form_has_department_before_municipality(places):
    fields = list(EmergencyForm(user=make_user("rita", RISK_MANAGER)).fields)
    assert fields.index("department") == fields.index("municipality") - 1


def test_municipality_outside_department_is_refused(places, flood):
    form = EmergencyForm(
        data(places["antioquia"], places["cajica"], flood), user=make_user("rita", RISK_MANAGER)
    )
    assert not form.is_valid()
    assert form.errors["municipality"] == [WRONG_DEPARTMENT]


def test_municipality_inside_department_is_accepted(places, flood):
    form = EmergencyForm(
        data(places["cundinamarca"], places["cajica"], flood), user=make_user("rita", RISK_MANAGER)
    )
    assert form.is_valid(), form.errors


def test_edit_preselects_department(places, flood):
    emergency = Emergency.objects.create(
        emergency_type=flood,
        municipality=places["cajica"],
        occurred_at=timezone.now() - timedelta(hours=1),
    )
    form = EmergencyForm(instance=emergency, user=make_user("rita", RISK_MANAGER))
    assert form["department"].value() == places["cundinamarca"].pk


def test_operator_options_hide_other_pending(places):
    olga = make_user("olga", OPERATOR)
    other = make_user("otto", OPERATOR)
    mine = Municipality.objects.create(
        department=places["antioquia"], name="VEREDA NUEVA", validation=Municipality.PENDING, created_by=olga
    )
    theirs = Municipality.objects.create(
        department=places["antioquia"], name="OTRA VEREDA", validation=Municipality.PENDING, created_by=other
    )
    ids = [row[0] for row in Municipality.objects.visible_to(olga).as_options()]
    assert mine.pk in ids
    assert theirs.pk not in ids


def test_report_page_embeds_options(client, places, flood):
    client.force_login(make_user("olga", OPERATOR))
    html = client.get(reverse("emergencies:emergency_create")).content.decode()
    assert '<script id="municipality-options" type="application/json">' in html
    assert 'data-combobox="municipality"' in html
    assert 'data-department-field="id_department"' in html
