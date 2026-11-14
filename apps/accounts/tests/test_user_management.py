import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ADMINISTRATOR, OPERATOR, RISK_MANAGER, get_role
from apps.accounts.services import RoleChangeError, set_role


def make_user(username, role=None, **extra):
    user = User.objects.create_user(username, password="pass-12345", **extra)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def group_names(user):
    return set(user.groups.values_list("name", flat=True))


def test_only_administrator_can_list_users(client, db):
    make_user("olga", OPERATOR)
    client.force_login(User.objects.get(username="olga"))
    assert client.get(reverse("accounts:user_list")).status_code == 403

    make_user("adam", ADMINISTRATOR)
    client.force_login(User.objects.get(username="adam"))
    response = client.get(reverse("accounts:user_list"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "olga" in content
    assert "Operator" in content
    assert "Administrator" in content


def test_administrator_assigns_role(client, db):
    admin = make_user("adam", ADMINISTRATOR)
    target = make_user("ana")
    client.force_login(admin)
    response = client.post(
        reverse("accounts:user_role", args=[target.pk]), {"role": OPERATOR}
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:user_list")
    assert group_names(target) == {OPERATOR}


def test_assigning_replaces_previous_role(db):
    admin = make_user("adam", ADMINISTRATOR)
    target = make_user("ana", OPERATOR)
    set_role(admin, target, RISK_MANAGER)
    assert group_names(target) == {RISK_MANAGER}


def test_administrator_cannot_change_own_role(db):
    admin = make_user("adam", ADMINISTRATOR)
    make_user("eve", ADMINISTRATOR)
    with pytest.raises(RoleChangeError, match="own role"):
        set_role(admin, admin, OPERATOR)
    assert group_names(admin) == {ADMINISTRATOR}


def test_cannot_remove_last_administrator(db):
    root = User.objects.create_superuser("root", password="pass-12345")
    only_admin = make_user("adam", ADMINISTRATOR)
    with pytest.raises(RoleChangeError, match="last administrator"):
        set_role(root, only_admin, OPERATOR)
    with pytest.raises(RoleChangeError, match="last administrator"):
        set_role(root, only_admin, None)
    assert group_names(only_admin) == {ADMINISTRATOR}

    second = make_user("eve", ADMINISTRATOR)
    set_role(root, only_admin, OPERATOR)
    assert group_names(only_admin) == {OPERATOR}
    assert group_names(second) == {ADMINISTRATOR}


def test_role_none_removes_access(client, db):
    admin = make_user("adam", ADMINISTRATOR)
    target = make_user("ana", OPERATOR)
    set_role(admin, target, None)
    assert get_role(target) is None
    client.force_login(target)
    response = client.get(reverse("dashboard:index"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:pending")


def test_invalid_role_raises(db):
    admin = make_user("adam", ADMINISTRATOR)
    target = make_user("ana", OPERATOR)
    with pytest.raises(RoleChangeError, match="Unknown role"):
        set_role(admin, target, "janitor")
    assert group_names(target) == {OPERATOR}


def test_view_shows_message_when_change_rejected(client, db):
    admin = make_user("adam", ADMINISTRATOR)
    client.force_login(admin)
    response = client.post(
        reverse("accounts:user_role", args=[admin.pk]), {"role": OPERATOR}
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:user_list")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("own role" in m for m in messages)
    assert group_names(admin) == {ADMINISTRATOR}


def test_role_view_rejects_non_administrator(client, db):
    operator = make_user("olga", OPERATOR)
    target = make_user("ana")
    client.force_login(operator)
    response = client.post(
        reverse("accounts:user_role", args=[target.pk]), {"role": OPERATOR}
    )
    assert response.status_code == 403
    assert group_names(target) == set()


def test_user_list_link_only_for_administrators(client, db):
    link = f'href="{reverse("accounts:user_list")}"'

    client.force_login(make_user("adam", ADMINISTRATOR))
    assert link in client.get(reverse("dashboard:index")).content.decode()

    client.force_login(make_user("olga", OPERATOR))
    assert link not in client.get(reverse("dashboard:index")).content.decode()
