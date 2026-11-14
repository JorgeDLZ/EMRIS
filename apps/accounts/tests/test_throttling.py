from datetime import timedelta

from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LoginAttempt, User
from apps.accounts.roles import OPERATOR
from apps.accounts.throttling import LOCKED_MESSAGE, client_ip

PASSWORD = "pass-12345"
IP_1 = "10.0.0.1"
IP_2 = "10.0.0.2"


def make_user(username):
    user = User.objects.create_user(username, password=PASSWORD)
    user.groups.add(Group.objects.get(name=OPERATOR))
    return user


def attempt(client, username, password, ip=IP_1):
    return client.post(
        reverse("accounts:login"),
        {"username": username, "password": password},
        REMOTE_ADDR=ip,
    )


def fail(client, username, times, ip=IP_1):
    for _ in range(times):
        response = attempt(client, username, "wrong-password", ip)
        assert LOCKED_MESSAGE not in response.content.decode()


def signed_in(client):
    return "_auth_user_id" in client.session


def test_sixth_attempt_refused_even_with_right_password(client, db):
    make_user("ana")
    fail(client, "ana", 5)
    response = attempt(client, "ana", PASSWORD)
    assert response.status_code == 200
    assert LOCKED_MESSAGE in response.content.decode()
    assert not signed_in(client)
    assert LoginAttempt.objects.count() == 5


def test_lock_clears_after_window(client, db):
    make_user("ana")
    fail(client, "ana", 5)
    LoginAttempt.objects.update(attempted_at=timezone.now() - timedelta(minutes=16))
    response = attempt(client, "ana", PASSWORD)
    assert response.status_code == 302
    assert signed_in(client)


def test_lock_is_per_username_and_ip(client, db):
    make_user("ana")
    make_user("beto")
    fail(client, "ana", 5)
    assert attempt(client, "ana", PASSWORD, IP_2).status_code == 302
    client.logout()
    assert attempt(client, "beto", PASSWORD, IP_1).status_code == 302


def test_ip_locked_after_twenty_failures(client, db):
    make_user("ana")
    for index in range(5):
        fail(client, f"user-{index}", 4)
    response = attempt(client, "ana", PASSWORD)
    assert LOCKED_MESSAGE in response.content.decode()
    assert not signed_in(client)
    assert attempt(client, "ana", PASSWORD, IP_2).status_code == 302


def test_success_clears_failures(client, db):
    make_user("ana")
    fail(client, "ana", 4)
    assert attempt(client, "ana", PASSWORD).status_code == 302
    client.logout()
    fail(client, "ana", 4)
    assert attempt(client, "ana", PASSWORD).status_code == 302


def test_username_case_insensitive(client, db):
    make_user("ana")
    fail(client, "Ana", 3)
    fail(client, "ana", 2)
    response = attempt(client, "ana", PASSWORD)
    assert LOCKED_MESSAGE in response.content.decode()


def test_old_failures_are_purged(client, db):
    fail(client, "ana", 1)
    LoginAttempt.objects.update(attempted_at=timezone.now() - timedelta(minutes=16))
    fail(client, "beto", 1)
    assert list(LoginAttempt.objects.values_list("username", flat=True)) == ["beto"]


def test_client_ip_uses_rightmost_forwarded_entry():
    factory = RequestFactory()
    forwarded = factory.get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2 ", REMOTE_ADDR="3.3.3.3")
    assert client_ip(forwarded) == "2.2.2.2"
    assert client_ip(factory.get("/", REMOTE_ADDR="3.3.3.3")) == "3.3.3.3"


def test_client_ip_ignores_invalid_forwarded_entry():
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="not-an-ip", REMOTE_ADDR="3.3.3.3")
    assert client_ip(request) == "3.3.3.3"


def test_locked_message_does_not_reveal_username(client, db):
    make_user("ana")
    fail(client, "ghost", 5)
    fail(client, "ana", 5)
    unknown = attempt(client, "ghost", "whatever").content.decode()
    known = attempt(client, "ana", PASSWORD).content.decode()
    assert LOCKED_MESSAGE in unknown
    assert LOCKED_MESSAGE in known


def test_admin_login_is_throttled(client, db):
    User.objects.create_superuser("root", password=PASSWORD)
    url = reverse("admin:login")
    for _ in range(5):
        client.post(url, {"username": "root", "password": "wrong-password"}, REMOTE_ADDR=IP_1)
    response = client.post(url, {"username": "root", "password": PASSWORD}, REMOTE_ADDR=IP_1)
    assert LOCKED_MESSAGE in response.content.decode()
    assert not signed_in(client)
