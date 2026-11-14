from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ALL_ROLES
from apps.emergencies.models import REPORTED, Emergency, EmergencyType, Impact, StatusLog
from apps.history.models import UngrdRecord
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan, ResourceAssignment
from apps.seismic.models import SeismicEvent


@pytest.fixture
def emergency(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    return Emergency.objects.create(
        emergency_type=EmergencyType.objects.create(name="Flood"),
        municipality=municipality,
        occurred_at=timezone.now(),
        description="Original",
        status=REPORTED,
    )


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser("root", password="pass-12345")


def refused(response):
    return response.status_code == 403 or (
        response.status_code == 302 and response.url.startswith(reverse("admin:login"))
    )


def test_admin_requires_superuser(client, db):
    staff = User.objects.create_user("staff", password="pass-12345", is_staff=True)
    accounts = [staff]
    for role in ALL_ROLES:
        user = User.objects.create_user(role, password="pass-12345", is_staff=True)
        user.groups.add(Group.objects.get(name=role))
        accounts.append(user)
    for account in accounts:
        client.force_login(account)
        assert refused(client.get(reverse("admin:index")))
        assert refused(client.get(reverse("admin:emergencies_emergencytype_changelist")))
    client.force_login(User.objects.create_superuser("root", password="pass-12345"))
    assert client.get(reverse("admin:index")).status_code == 200


def test_inactive_superuser_has_no_access(client, db):
    root = User.objects.create_superuser("root", password="pass-12345", is_active=False)
    client.force_login(root)
    assert refused(client.get(reverse("admin:index")))


def test_audit_models_read_only_in_admin(client, emergency, superuser):
    impact = Impact.objects.create(emergency=emergency, deceased=1)
    log = StatusLog.objects.create(emergency=emergency, status=REPORTED, note="Reported")
    client.force_login(superuser)
    for obj, field, value in (
        (emergency, "description", "Changed"),
        (impact, "deceased", 9),
        (log, "note", "Changed"),
    ):
        opts = obj._meta
        change_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
        response = client.get(change_url)
        assert response.status_code == 200
        assert 'name="_save"' not in response.content.decode()
        assert client.post(change_url, {field: value}).status_code == 403
        add_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
        assert client.get(add_url).status_code == 403
        delete_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_delete", args=[obj.pk])
        assert client.post(delete_url, {"post": "yes"}).status_code == 403
        obj.refresh_from_db()
        assert getattr(obj, field) != value


@pytest.mark.parametrize(
    "model",
    [Emergency, Impact, StatusLog, ActionPlan, Action, ResourceAssignment, UngrdRecord, SeismicEvent],
)
def test_workflow_and_audit_models_refuse_add(client, superuser, model):
    opts = model._meta
    client.force_login(superuser)
    assert client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_add")).status_code == 403


@pytest.mark.parametrize(
    "model_name",
    [
        "emergencies_emergencytype",
        "places_department",
        "places_municipality",
        "plans_resource",
        "accounts_user",
    ],
)
def test_catalogs_stay_editable_for_superusers(client, superuser, model_name):
    client.force_login(superuser)
    assert client.get(reverse(f"admin:{model_name}_add")).status_code == 200


def test_ungrd_record_change_view_is_read_only(client, emergency, superuser):
    record = UngrdRecord.objects.create(
        source_row=1,
        occurred_on=date(2020, 1, 10),
        department=emergency.municipality.department,
        emergency_type=emergency.emergency_type,
    )
    client.force_login(superuser)
    response = client.get(reverse("admin:history_ungrdrecord_change", args=[record.pk]))
    assert response.status_code == 200
    assert 'name="_save"' not in response.content.decode()
