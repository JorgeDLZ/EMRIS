import re
from datetime import timedelta
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.emergencies.models import Emergency, EmergencyType
from apps.places.models import Department, Municipality


def forward(module_path, function_name):
    getattr(import_module(module_path), function_name)(apps, None)


def test_migration_capitalizes_place_names(db):
    department = Department.objects.create(code="25", name="CUNDINAMARCA")
    municipality = Municipality.objects.create(department=department, name="CAJICÁ NORTE")
    Department.objects.filter(pk=department.pk).update(name="cundinamarca")
    Municipality.objects.filter(pk=municipality.pk).update(name="cajicá  norte")
    forward("apps.places.migrations.0002_capitalize_names", "capitalize_names")
    assert Department.objects.get(pk=department.pk).name == "CUNDINAMARCA"
    assert Municipality.objects.get(pk=municipality.pk).name == "CAJICÁ NORTE"


def test_migration_capitalizes_sites(db):
    department = Department.objects.create(code="25", name="CUNDINAMARCA")
    emergency = Emergency.objects.create(
        emergency_type=EmergencyType.objects.create(name="Flood"),
        municipality=Municipality.objects.create(department=department, name="CAJICÁ"),
        occurred_at=timezone.now() - timedelta(hours=1),
        description="Keep me",
    )
    Emergency.objects.filter(pk=emergency.pk).update(site="vereda  la balsa")
    forward("apps.emergencies.migrations.0005_capitalize_sites", "capitalize_sites")
    emergency.refresh_from_db()
    assert emergency.site == "VEREDA LA BALSA"
    assert emergency.description == "Keep me"


def test_migration_capitalizes_organizations(db):
    user = User.objects.create_user("ana", password="pass-12345")
    User.objects.filter(pk=user.pk).update(organization="cruz  roja")
    forward("apps.accounts.migrations.0004_capitalize_organizations", "capitalize_organizations")
    assert User.objects.get(pk=user.pk).organization == "CRUZ ROJA"


def test_proper_name_inputs_show_capitals(client, db):
    register = client.get(reverse("accounts:register")).content.decode()
    assert re.search(r'<input[^>]*class="input-caps"[^>]*name="organization"|<input[^>]*name="organization"[^>]*class="input-caps"', register)
    operator = User.objects.create_user("olga", password="pass-12345")
    operator.groups.add(Group.objects.get(name="operator"))
    client.force_login(operator)
    report = client.get(reverse("emergencies:emergency_create")).content.decode()
    assert re.search(r'<input[^>]*class="input-caps"[^>]*name="site"|<input[^>]*name="site"[^>]*class="input-caps"', report)
