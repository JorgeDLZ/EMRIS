import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.places.models import Department, Municipality


def make_user(username, role=None):
    user = User.objects.create_user(username, password="pass-12345")
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def antioquia(db):
    return Department.objects.create(code="05", name="ANTIOQUIA")


@pytest.fixture
def medellin(antioquia):
    return Municipality.objects.create(department=antioquia, code="05001", name="MEDELLÍN")


@pytest.mark.parametrize(
    "role, url_name, expected",
    [
        (ADMINISTRATOR, "places:municipality_list", 200),
        (ADMINISTRATOR, "places:municipality_create", 200),
        (ADMINISTRATOR, "places:municipality_pending", 200),
        (RISK_MANAGER, "places:municipality_list", 200),
        (RISK_MANAGER, "places:municipality_create", 200),
        (RISK_MANAGER, "places:municipality_pending", 200),
        (OPERATOR, "places:municipality_list", 200),
        (OPERATOR, "places:municipality_create", 200),
        (OPERATOR, "places:municipality_pending", 403),
        (ACTION_OWNER, "places:municipality_list", 403),
        (ACTION_OWNER, "places:municipality_create", 403),
        (ACTION_OWNER, "places:municipality_pending", 403),
    ],
)
def test_access_matrix(client, db, role, url_name, expected):
    client.force_login(make_user("ana", role))
    assert client.get(reverse(url_name)).status_code == expected


def test_operator_creates_pending(client, antioquia):
    operator = make_user("olga", OPERATOR)
    client.force_login(operator)
    response = client.post(
        reverse("places:municipality_create"), {"department": antioquia.pk, "name": "Nueva Villa"}
    )
    assert response.status_code == 302
    created = Municipality.objects.get(name="Nueva Villa")
    assert created.validation == Municipality.PENDING
    assert created.created_by == operator

    client.force_login(make_user("rita", RISK_MANAGER))
    assert "Nueva Villa" in client.get(reverse("places:municipality_pending")).content.decode()


def test_similar_name_requires_confirmation(client, medellin):
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("places:municipality_create")
    data = {"department": medellin.department.pk, "name": "Medelin"}

    response = client.post(url, data)
    assert response.status_code == 200
    assert Municipality.objects.count() == 1
    assert "MEDELLÍN" in response.content.decode()

    response = client.post(url, {**data, "confirm_new": "on"})
    assert response.status_code == 302
    assert Municipality.objects.filter(name="Medelin").exists()


def test_exact_duplicate_shows_form_error(client, medellin):
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(
        reverse("places:municipality_create"),
        {"department": medellin.department.pk, "name": "medellin", "confirm_new": "on"},
    )
    assert response.status_code == 200
    assert "already exists" in response.content.decode()
    assert Municipality.objects.count() == 1


def test_blank_name_is_rejected(client, antioquia):
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(
        reverse("places:municipality_create"), {"department": antioquia.pk, "name": "   "}
    )
    assert response.status_code == 200
    assert Municipality.objects.count() == 0


@pytest.mark.parametrize("url_name", ["places:municipality_approve", "places:municipality_reject"])
def test_approve_and_reject_are_post_only(client, antioquia, url_name):
    pending = Municipality.objects.create(
        department=antioquia, name="Nueva Villa", validation=Municipality.PENDING
    )
    client.force_login(make_user("rita", RISK_MANAGER))
    assert client.get(reverse(url_name, args=[pending.pk])).status_code == 405


def test_risk_manager_approves_and_rejects(client, antioquia):
    first = Municipality.objects.create(department=antioquia, name="Uno", validation=Municipality.PENDING)
    second = Municipality.objects.create(department=antioquia, name="Dos", validation=Municipality.PENDING)
    client.force_login(make_user("rita", RISK_MANAGER))

    response = client.post(reverse("places:municipality_approve", args=[first.pk]))
    assert response.status_code == 302
    first.refresh_from_db()
    assert first.validation == Municipality.APPROVED

    client.post(reverse("places:municipality_reject", args=[second.pk]))
    assert not Municipality.objects.filter(pk=second.pk).exists()


def test_rejecting_an_approved_municipality_is_harmless(client, medellin):
    client.force_login(make_user("rita", RISK_MANAGER))
    response = client.post(reverse("places:municipality_reject", args=[medellin.pk]))
    assert response.status_code == 302
    assert Municipality.objects.filter(pk=medellin.pk).exists()


def test_operator_cannot_approve(client, antioquia):
    pending = Municipality.objects.create(
        department=antioquia, name="Nueva Villa", validation=Municipality.PENDING
    )
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(reverse("places:municipality_approve", args=[pending.pk]))
    assert response.status_code == 403
    pending.refresh_from_db()
    assert pending.validation == Municipality.PENDING


def test_operator_sees_only_own_pending(client, antioquia):
    olga = make_user("olga", OPERATOR)
    other = make_user("omar", OPERATOR)
    Municipality.objects.create(department=antioquia, name="Mine", validation=Municipality.PENDING, created_by=olga)
    Municipality.objects.create(department=antioquia, name="Theirs", validation=Municipality.PENDING, created_by=other)
    client.force_login(olga)
    content = client.get(reverse("places:municipality_list")).content.decode()
    assert "Mine" in content
    assert "Theirs" not in content


def test_search_ignores_accents(client, medellin):
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("places:municipality_list")
    assert "MEDELLÍN" in client.get(url, {"q": "medellín"}).content.decode()
    assert "MEDELLÍN" in client.get(url, {"q": "MEDELLIN"}).content.decode()
    assert "MEDELLÍN" not in client.get(url, {"q": "bogota"}).content.decode()


def test_department_filter(client, medellin):
    other = Department.objects.create(code="08", name="ATLÁNTICO")
    Municipality.objects.create(department=other, code="08001", name="BARRANQUILLA")
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(reverse("places:municipality_list"), {"department": other.pk}).content.decode()
    assert "BARRANQUILLA" in content
    assert "MEDELLÍN" not in content


def test_bad_page_number_is_harmless(client, medellin):
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("places:municipality_list")
    assert client.get(url, {"page": "abc"}).status_code == 200
    assert client.get(url, {"department": "abc"}).status_code == 200


def test_nav_links_follow_role(client, db):
    link = f'href="{reverse("places:municipality_list")}"'

    client.force_login(make_user("olga", OPERATOR))
    assert link in client.get(reverse("home")).content.decode()

    client.force_login(make_user("alan", ACTION_OWNER))
    assert link not in client.get(reverse("home")).content.decode()


def test_operator_similar_warning_hides_other_operators_pending(client, antioquia):
    Municipality.objects.create(
        department=antioquia,
        name="Nueva Villa",
        source=Municipality.USER,
        validation=Municipality.PENDING,
        created_by=make_user("olga", OPERATOR),
    )
    client.force_login(make_user("omar", OPERATOR))
    response = client.post(
        reverse("places:municipality_create"), {"department": antioquia.pk, "name": "Nueva Vila"}
    )
    assert response.status_code == 302
    assert Municipality.objects.filter(name="Nueva Vila").exists()
