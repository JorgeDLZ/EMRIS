import subprocess
import sys
from datetime import timedelta
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
