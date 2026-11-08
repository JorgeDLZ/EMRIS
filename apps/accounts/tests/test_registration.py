from django.urls import reverse

from apps.accounts.models import User

VALID_DATA = {
    "username": "Ana",
    "organization": "Municipal council",
    "password1": "a-Strong-pass-123",
    "password2": "a-Strong-pass-123",
}


def test_register_creates_user_without_role(client, db):
    response = client.post(reverse("accounts:register"), VALID_DATA)
    user = User.objects.get(username="Ana")
    assert user.groups.count() == 0
    assert user.organization == "Municipal council"
    assert response.status_code == 302
    assert response.url == reverse("accounts:pending")


def test_register_rejects_case_insensitive_duplicate(client, db):
    User.objects.create_user("ana", password="pass-12345")
    response = client.post(reverse("accounts:register"), VALID_DATA)
    assert response.status_code == 200
    assert "username" in response.context["form"].errors
    assert User.objects.count() == 1


def test_logout_requires_post(client, db):
    assert client.get(reverse("accounts:logout")).status_code == 405
