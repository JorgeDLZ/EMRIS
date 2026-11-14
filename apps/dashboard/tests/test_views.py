import subprocess
import sys
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies.models import Emergency, EmergencyType
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan
from apps.seismic.models import SeismicEvent

PASSWORD = "pass-12345"


def make_user(username, role=None):
    user = User.objects.create_user(username, password=PASSWORD)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def make_emergency(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood = EmergencyType.objects.create(name="Flood")

    def build(**extra):
        return Emergency.objects.create(
            emergency_type=flood,
            municipality=municipality,
            occurred_at=timezone.now() - timedelta(hours=1),
            **extra,
        )

    return build


@pytest.mark.parametrize("role", [ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER])
def test_dashboard_for_every_role(client, db, role):
    client.force_login(make_user("ana", role))
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 200
    assert "No active emergencies." in response.content.decode()


def test_user_without_role_goes_to_pending(client, db):
    client.force_login(make_user("ana"))
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:pending")


def test_anonymous_user_goes_to_login(client, db):
    assert client.get(reverse("dashboard:index")).status_code == 302


def test_action_owner_counts_only_own(client, make_emergency):
    owner = make_user("owen", ACTION_OWNER)
    own = make_emergency()
    make_emergency()
    make_emergency()
    plan = ActionPlan.objects.create(emergency=own)
    Action.objects.create(plan=plan, description="Deliver kits", owner=owner)
    Action.objects.create(plan=plan, description="Open shelter", owner=owner)
    client.force_login(owner)
    response = client.get(reverse("dashboard:index"))
    assert response.context["summary"]["active"] == 1
    assert "1 active emergencies" in response.content.decode()


def test_dashboard_does_not_import_pandas():
    script = (
        "import os, sys, django\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
        "django.setup()\n"
        "import apps.dashboard.views\n"
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


def test_dashboard_shows_seismic_panel_to_every_role(client, db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLIN")
    SeismicEvent.objects.create(
        sgc_id="x", event_time=timezone.now() - timedelta(days=400), magnitude=5.26,
        depth_km=12.34, latitude=4.0, longitude=-74.0, place="Near Medellin",
        municipality=municipality,
    )
    for role in (ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER):
        client.force_login(make_user(f"user-{role}", role))
        html = client.get(reverse("dashboard:index")).content.decode()
        assert "Seismic activity" in html
        assert "Catalog up to" in html
        assert "1 event in the last 30 days of the catalog." in html
        assert "<td>5.3</td>" in html
        assert "<td>12.3</td>" in html
        assert "MEDELLIN (ANTIOQUIA)" in html


def test_dashboard_seismic_panel_empty_texts(client, db):
    client.force_login(make_user("viewer", OPERATOR))
    assert "No seismic events loaded." in client.get(reverse("dashboard:index")).content.decode()
    SeismicEvent.objects.create(
        sgc_id="w", event_time=timezone.now(), magnitude=3.0, depth_km=1.0,
        latitude=4.0, longitude=-74.0, place="Weak",
    )
    html = client.get(reverse("dashboard:index")).content.decode()
    assert "No events of magnitude 4.0 or more in this period." in html


def test_dashboard_shows_seismic_dates_in_local_time(client, db):
    SeismicEvent.objects.create(
        sgc_id="tz", event_time=datetime(2026, 3, 2, 2, 0, tzinfo=dt_timezone.utc), magnitude=4.5,
        depth_km=10.0, latitude=4.0, longitude=-74.0, place="Local time check",
    )
    client.force_login(make_user("viewer", OPERATOR))
    html = client.get(reverse("dashboard:index")).content.decode()
    assert "Catalog up to 2026-03-01." in html
    assert "<td>2026-03-01 21:00</td>" in html
