from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.roles import ALL_ROLES, OPERATOR, get_role
from apps.accounts.permissions import has_role


def test_roles_exist_after_migrate(db):
    assert set(Group.objects.values_list("name", flat=True)) == set(ALL_ROLES)


def test_get_role_none_for_new_user(db):
    user = User.objects.create_user("ana", password="pass-12345")
    assert get_role(user) is None


def test_get_role_returns_assigned_role(db):
    user = User.objects.create_user("ana", password="pass-12345")
    user.groups.add(Group.objects.get(name=OPERATOR))
    assert get_role(user) == OPERATOR


def test_has_role_superuser_always_true(db):
    admin = User.objects.create_superuser("root", password="pass-12345")
    assert has_role(admin, OPERATOR)


def test_has_role_false_without_role(db):
    user = User.objects.create_user("ana", password="pass-12345")
    assert not has_role(user, OPERATOR)
