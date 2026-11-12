import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies.models import EmergencyType
from apps.emergencies.services import seed_emergency_types


def make_user(username, role):
    user = User.objects.create_user(username, password="pass-12345")
    user.groups.add(Group.objects.get(name=role))
    return user


def test_seed_is_idempotent(db):
    assert seed_emergency_types(["Flood", "Fire"]) == 2
    assert seed_emergency_types(["Flood", "Fire"]) == 0
    assert EmergencyType.objects.count() == 2


def test_seed_does_not_reactivate(db):
    EmergencyType.objects.create(name="Flood", is_active=False)
    assert seed_emergency_types(["Flood"]) == 0
    assert EmergencyType.objects.get(name="Flood").is_active is False


@pytest.mark.parametrize(
    "role, expected",
    [(ADMINISTRATOR, 200), (RISK_MANAGER, 200), (OPERATOR, 403), (ACTION_OWNER, 403)],
)
def test_access_by_role(client, db, role, expected):
    emergency_type = EmergencyType.objects.create(name="Flood")
    client.force_login(make_user("ana", role))
    for url in (
        reverse("emergencies:type_list"),
        reverse("emergencies:type_create"),
        reverse("emergencies:type_edit", args=[emergency_type.pk]),
    ):
        assert client.get(url).status_code == expected


def test_create_rejects_case_insensitive_duplicate(client, db):
    EmergencyType.objects.create(name="Flood")
    client.force_login(make_user("ana", ADMINISTRATOR))
    response = client.post(reverse("emergencies:type_create"), {"name": "flood", "is_active": "on"})
    assert response.status_code == 200
    assert "name" in response.context["form"].errors
    assert EmergencyType.objects.count() == 1


def test_create_adds_type(client, db):
    client.force_login(make_user("ana", RISK_MANAGER))
    response = client.post(reverse("emergencies:type_create"), {"name": "Landslide", "is_active": "on"})
    assert response.status_code == 302
    assert EmergencyType.objects.get(name="Landslide").is_active is True


def test_deactivate(client, db):
    emergency_type = EmergencyType.objects.create(name="Flood")
    client.force_login(make_user("ana", ADMINISTRATOR))
    response = client.post(reverse("emergencies:type_edit", args=[emergency_type.pk]), {"name": "Flood"})
    assert response.status_code == 302
    emergency_type.refresh_from_db()
    assert emergency_type.is_active is False
    listing = client.get(reverse("emergencies:type_list"))
    assert emergency_type in listing.context["types"]
    assert "Inactive" in listing.content.decode()


def test_seed_matches_case_insensitive_name(db):
    EmergencyType.objects.create(name="flood")
    assert seed_emergency_types(["Flood"]) == 0
    assert EmergencyType.objects.count() == 1
    assert EmergencyType.objects.get(name="flood").seed_key == "Flood"


def test_renamed_seeded_type_is_not_forked(db):
    assert seed_emergency_types(["Flood"]) == 1
    EmergencyType.objects.filter(seed_key="Flood").update(name="Floods")
    assert seed_emergency_types(["Flood"]) == 0
    assert EmergencyType.objects.count() == 1
    assert EmergencyType.objects.get().name == "Floods"


def test_operator_post_is_refused(client, db):
    emergency_type = EmergencyType.objects.create(name="Flood")
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(reverse("emergencies:type_create"), {"name": "Landslide", "is_active": "on"})
    assert response.status_code == 403
    response = client.post(
        reverse("emergencies:type_edit", args=[emergency_type.pk]), {"name": "Changed", "is_active": "on"}
    )
    assert response.status_code == 403
    assert list(EmergencyType.objects.values_list("name", flat=True)) == ["Flood"]


def test_edit_saves_name(client, db):
    emergency_type = EmergencyType.objects.create(name="Flood")
    client.force_login(make_user("rita", RISK_MANAGER))
    response = client.post(
        reverse("emergencies:type_edit", args=[emergency_type.pk]), {"name": "Floods", "is_active": "on"}
    )
    assert response.status_code == 302
    emergency_type.refresh_from_db()
    assert emergency_type.name == "Floods"
