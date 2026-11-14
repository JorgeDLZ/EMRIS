import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.db import OperationalError
from django.urls import resolve, reverse

from apps.accounts import roles
from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from config.navigation import MENU, navigation

EVERYTHING = {
    "Home",
    "Dashboard",
    "Emergencies",
    "Resources",
    "Risk ranking",
    "Models",
    "UNGRD history",
    "Municipalities",
    "Pending municipalities",
    "Emergency types",
    "Users",
}
MATRIX = {
    ADMINISTRATOR: EVERYTHING,
    RISK_MANAGER: EVERYTHING - {"Models", "Users"},
    OPERATOR: {
        "Home",
        "Dashboard",
        "Emergencies",
        "Risk ranking",
        "UNGRD history",
        "Municipalities",
    },
    ACTION_OWNER: {"Home", "Dashboard", "Emergencies"},
}
ITEM_URLS = {entry.label: entry.url_name for _, entries in MENU for entry in entries}


def make_user(role=None, **extra):
    user = User.objects.create_user(role or "plain", password="pass-12345", **extra)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def labels(groups):
    return {item.label for group in groups for item in group.items}


def request_for(rf, user, path="/"):
    request = rf.get(path)
    request.user = user
    request.resolver_match = resolve(path)
    return request


@pytest.mark.parametrize("role", list(MATRIX))
def test_menu_matches_role_matrix(rf, db, role):
    groups = navigation(request_for(rf, make_user(role)))["nav_groups"]
    assert labels(groups) == MATRIX[role]


def test_superuser_sees_every_item(rf, db):
    superuser = User.objects.create_superuser("root", password="pass-12345")
    assert labels(navigation(request_for(rf, superuser))["nav_groups"]) == EVERYTHING


@pytest.mark.parametrize("role", list(MATRIX))
def test_visible_items_open_and_hidden_items_are_forbidden(client, db, role):
    make_user(role)
    client.login(username=role, password="pass-12345")
    for label, url_name in ITEM_URLS.items():
        expected = 200 if label in MATRIX[role] else 403
        assert client.get(reverse(url_name)).status_code == expected, label


def test_menu_items_share_the_view_role_tuples():
    named = [value for value in vars(roles).values() if isinstance(value, tuple)]
    for _, entries in MENU:
        for entry in entries:
            assert any(entry.roles is tuple_ for tuple_ in named), entry.label
            callback = resolve(reverse(entry.url_name)).func
            if entry.url_name == "home":
                assert not hasattr(callback, "view_class")
                assert not hasattr(callback, "required_roles")
                continue
            view_roles = getattr(callback, "required_roles", None) or callback.view_class.allowed_roles
            assert entry.roles == view_roles, entry.label


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/emergencies/", "Emergencies"),
        ("/emergencies/7/", "Emergencies"),
        ("/plans/7/", "Emergencies"),
        ("/plans/actions/3/edit/", "Emergencies"),
        ("/plans/resources/", "Resources"),
        ("/plans/resources/4/", "Resources"),
        ("/emergencies/types/5/", "Emergency types"),
        ("/history/", "UNGRD history"),
        ("/places/pending/", "Pending municipalities"),
        ("/dashboard/risk/", "Risk ranking"),
        ("/", "Home"),
    ],
)
def test_active_item_follows_url(rf, db, path, active):
    groups = navigation(request_for(rf, make_user(ADMINISTRATOR), path))["nav_groups"]
    current = [item.label for group in groups for item in group.items if item.active]
    assert current == [active]


def test_anonymous_and_roleless_have_no_groups(rf, db):
    assert navigation(request_for(rf, AnonymousUser()))["nav_groups"] == []
    assert navigation(request_for(rf, make_user()))["nav_groups"] == []


def test_sidebar_links_present_without_js(client, db):
    make_user(OPERATOR)
    client.login(username=OPERATOR, password="pass-12345")
    html = client.get("/dashboard/").content.decode()
    assert '<nav class="sidebar"' in html
    assert f'href="{reverse("emergencies:emergency_list")}"' in html
    assert 'aria-current="page"' in html
    assert 'aria-expanded="false"' in html
    assert "Log out" in html


def test_report_button_only_for_editors(client, db):
    for role, shown in ((OPERATOR, True), (ACTION_OWNER, False)):
        make_user(role)
        client.login(username=role, password="pass-12345")
        html = client.get("/dashboard/").content.decode()
        assert (f'href="{reverse("emergencies:emergency_create")}"' in html) is shown


def test_login_redirects_to_dashboard(client, db):
    make_user(OPERATOR)
    response = client.post("/accounts/login/", {"username": OPERATOR, "password": "pass-12345"})
    assert response.status_code == 302
    assert response.url == "/dashboard/"


def test_login_without_role_lands_on_pending_page(client, db):
    make_user()
    response = client.post(
        "/accounts/login/", {"username": "plain", "password": "pass-12345"}, follow=True
    )
    assert response.redirect_chain[-1][0] == reverse("accounts:pending")


def test_error_page_renders_when_role_lookup_fails(client, db, settings, monkeypatch):
    def failing_role(user):
        raise OperationalError("database is unavailable")

    make_user(OPERATOR)
    client.login(username=OPERATOR, password="pass-12345")
    settings.ROOT_URLCONF = "config.tests.test_health"
    monkeypatch.setattr("config.navigation.get_role", failing_role)
    response = client.get("/boom/")
    assert response.status_code == 503
    assert "EMRIS is temporarily unavailable." in response.content.decode()
