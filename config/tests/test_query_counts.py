from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ADMINISTRATOR
from apps.emergencies.models import Emergency, EmergencyType
from apps.places.models import Department, Municipality

MAX_ROLE_QUERIES = 1


@pytest.fixture
def admin_client(client, db):
    user = User.objects.create_user("ana", password="pass-12345")
    user.groups.add(Group.objects.get(name=ADMINISTRATOR))
    client.force_login(user)
    return client


@pytest.fixture
def emergency(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    return Emergency.objects.create(
        emergency_type=EmergencyType.objects.create(name="Flood"),
        municipality=municipality,
        occurred_at=timezone.now() - timedelta(hours=1),
    )


def role_queries(client, url):
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url).status_code == 200
    return [q for q in queries.captured_queries if "auth_group" in q["sql"]]


def test_dashboard_looks_the_role_up_once(admin_client):
    assert len(role_queries(admin_client, reverse("dashboard:index"))) <= MAX_ROLE_QUERIES


def test_emergency_detail_looks_the_role_up_once(admin_client, emergency):
    url = reverse("emergencies:emergency_detail", args=[emergency.pk])
    assert len(role_queries(admin_client, url)) <= MAX_ROLE_QUERIES


def test_dashboard_query_budget(admin_client, django_assert_max_num_queries):
    with django_assert_max_num_queries(10):
        assert admin_client.get(reverse("dashboard:index")).status_code == 200


def test_emergency_detail_query_budget(admin_client, emergency, django_assert_max_num_queries):
    url = reverse("emergencies:emergency_detail", args=[emergency.pk])
    with django_assert_max_num_queries(13):
        assert admin_client.get(url).status_code == 200
