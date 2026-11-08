import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse
from django.views import View

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin
from apps.accounts.roles import ADMINISTRATOR, OPERATOR


def make_user(username="ana", role=None):
    user = User.objects.create_user(username, password="pass-12345")
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


class AdminOnlyView(RoleRequiredMixin, View):
    allowed_roles = (ADMINISTRATOR,)

    def get(self, request):
        return HttpResponse("ok")


def test_anonymous_home_redirects_to_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_user_without_role_sees_pending_on_home(client, db):
    client.force_login(make_user())
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:pending")


def test_user_without_role_direct_url_sees_pending(client, db):
    client.force_login(make_user())
    response = client.get("/accounts/users/")
    assert response.status_code == 302
    assert response.url == reverse("accounts:pending")


def test_decorator_role_not_allowed_returns_403_page(client, db):
    client.force_login(make_user(role=OPERATOR))
    response = client.get("/accounts/users/")
    assert response.status_code == 403
    assert "Access denied" in response.content.decode()


def test_decorator_anonymous_redirects_to_login(client, db):
    response = client.get("/accounts/users/")
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


@pytest.mark.urls("apps.accounts.tests.urls")
def test_decorator_allowed_role_passes(client, db):
    client.force_login(make_user(role=OPERATOR))
    assert client.get("/operator-only/").status_code == 200


def test_mixin_user_without_role_redirects_to_pending(db):
    request = RequestFactory().get("/x/")
    request.user = make_user()
    response = AdminOnlyView.as_view()(request)
    assert response.status_code == 302
    assert response.url == reverse("accounts:pending")


def test_mixin_role_not_allowed_returns_403(db):
    request = RequestFactory().get("/x/")
    request.user = make_user(role=OPERATOR)
    with pytest.raises(PermissionDenied):
        AdminOnlyView.as_view()(request)


def test_mixin_anonymous_redirects_to_login(db):
    request = RequestFactory().get("/x/")
    request.user = AnonymousUser()
    response = AdminOnlyView.as_view()(request)
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_operator_sees_home(client, db):
    client.force_login(make_user(role=OPERATOR))
    response = client.get(reverse("home"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "EMRIS" in content
    assert "Emergency Management &amp; Resource Information System" in content
