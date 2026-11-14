from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.roles import ALL_ROLES, OPERATOR, get_role
from apps.accounts.permissions import has_role
from apps.accounts.services import set_role


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


def test_get_role_is_cached_per_user_object(db, django_assert_num_queries):
    user = User.objects.create_user("ana", password="pass-12345")
    user.groups.add(Group.objects.get(name=OPERATOR))
    assert get_role(user) == OPERATOR
    with django_assert_num_queries(0):
        assert get_role(user) == OPERATOR


def test_set_role_refreshes_the_cached_role(db):
    actor = User.objects.create_user("boss", password="pass-12345")
    target = User.objects.create_user("ana", password="pass-12345")
    target.groups.add(Group.objects.get(name=OPERATOR))
    assert get_role(target) == OPERATOR
    set_role(actor, target, None)
    assert get_role(target) is None
