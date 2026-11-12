from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies.forms import EmergencyForm
from apps.emergencies.models import (
    CLOSED,
    CONTROLLED,
    IN_RESPONSE,
    REPORTED,
    Emergency,
    EmergencyType,
    Impact,
    StatusLog,
)
from apps.emergencies.workflow import change_status
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan

PASSWORD = "pass-12345"


def make_user(username, role=None):
    user = User.objects.create_user(username, password=PASSWORD)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def antioquia(db):
    return Department.objects.create(code="05", name="ANTIOQUIA")


@pytest.fixture
def medellin(antioquia):
    return Municipality.objects.create(department=antioquia, code="05001", name="MEDELLÍN")


@pytest.fixture
def flood(db):
    return EmergencyType.objects.create(name="Flood")


@pytest.fixture
def earthquake(db):
    return EmergencyType.objects.create(name="Earthquake", seed_key="Earthquake")


@pytest.fixture
def make_emergency(medellin, flood):
    def build(status=REPORTED, **extra):
        values = {
            "emergency_type": flood,
            "municipality": medellin,
            "occurred_at": timezone.now() - timedelta(hours=1),
            "status": status,
        }
        values.update(extra)
        return Emergency.objects.create(**values)

    return build


def form_data(medellin, flood, **extra):
    data = {
        "emergency_type": flood.pk,
        "municipality": medellin.pk,
        "site": "Riverside",
        "occurred_at": timezone.localtime(timezone.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        "description": "Water rising",
    }
    data.update(extra)
    return data


def give_action(emergency, owner):
    plan = ActionPlan.objects.create(emergency=emergency)
    Action.objects.create(plan=plan, description="Deliver kits", owner=owner)


EDIT_ROLES = [ADMINISTRATOR, RISK_MANAGER, OPERATOR]
EDIT_URLS = ["emergency_list", "emergency_create", "emergency_detail", "emergency_edit", "impact_edit"]


def url_for(name, emergency):
    if name in ("emergency_list", "emergency_create"):
        return reverse(f"emergencies:{name}")
    return reverse(f"emergencies:{name}", args=[emergency.pk])


@pytest.mark.parametrize("role", EDIT_ROLES)
@pytest.mark.parametrize("url_name", EDIT_URLS)
def test_access_matrix_edit_roles(client, make_emergency, role, url_name):
    emergency = make_emergency()
    client.force_login(make_user("ana", role))
    assert client.get(url_for(url_name, emergency)).status_code == 200


@pytest.mark.parametrize(
    "url_name, expected",
    [
        ("emergency_list", 200),
        ("emergency_create", 403),
        ("emergency_detail", 200),
        ("emergency_edit", 403),
        ("impact_edit", 403),
    ],
)
def test_access_matrix_action_owner(client, make_emergency, url_name, expected):
    emergency = make_emergency()
    owner = make_user("omar", ACTION_OWNER)
    give_action(emergency, owner)
    client.force_login(owner)
    assert client.get(url_for(url_name, emergency)).status_code == expected


def test_action_owner_cannot_see_other_emergency(client, make_emergency):
    emergency = make_emergency()
    client.force_login(make_user("omar", ACTION_OWNER))
    assert client.get(url_for("emergency_detail", emergency)).status_code == 404


def test_anonymous_and_roleless_are_redirected(client, make_emergency):
    emergency = make_emergency()
    url = url_for("emergency_list", emergency)
    assert client.get(url).status_code == 302
    assert "/login" in client.get(url)["Location"]
    client.force_login(make_user("nora"))
    assert client.get(url).status_code == 302
    assert client.get(url)["Location"] == reverse("accounts:pending")


def test_operator_reports_emergency(client, medellin, flood):
    operator = make_user("olga", OPERATOR)
    client.force_login(operator)
    response = client.post(reverse("emergencies:emergency_create"), form_data(medellin, flood))
    emergency = Emergency.objects.get()
    assert response.status_code == 302
    assert response["Location"] == reverse("emergencies:emergency_detail", args=[emergency.pk])
    assert emergency.reported_by == operator
    assert emergency.status == REPORTED
    assert StatusLog.objects.filter(emergency=emergency, status=REPORTED).count() == 1


def test_future_date_is_refused(client, medellin, flood):
    client.force_login(make_user("olga", OPERATOR))
    future = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    response = client.post(
        reverse("emergencies:emergency_create"), form_data(medellin, flood, occurred_at=future)
    )
    assert response.status_code == 200
    assert "The date cannot be in the future." in response.content.decode()
    assert not Emergency.objects.exists()


def test_magnitude_only_for_earthquakes(client, medellin, flood, earthquake):
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("emergencies:emergency_create")
    response = client.post(url, form_data(medellin, flood, reported_magnitude="5.5"))
    assert response.status_code == 200
    assert "Magnitude and depth apply only to earthquakes." in response.content.decode()
    assert not Emergency.objects.exists()

    response = client.post(
        url,
        form_data(medellin, earthquake, reported_magnitude="5.5", reported_depth_km="10"),
    )
    assert response.status_code == 302
    created = Emergency.objects.get()
    assert created.reported_magnitude == 5.5
    assert created.reported_depth_km == 10


def test_magnitude_and_depth_ranges(client, medellin, earthquake):
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("emergencies:emergency_create")
    assert client.post(url, form_data(medellin, earthquake, reported_magnitude="11")).status_code == 200
    assert client.post(url, form_data(medellin, earthquake, reported_depth_km="-1")).status_code == 200
    assert not Emergency.objects.exists()


def test_operator_can_use_own_pending_municipality(client, antioquia, flood):
    operator = make_user("olga", OPERATOR)
    other = make_user("otto", OPERATOR)
    own = Municipality.objects.create(
        department=antioquia, name="Nueva Villa", validation=Municipality.PENDING, created_by=operator
    )
    foreign = Municipality.objects.create(
        department=antioquia, name="Otra Villa", validation=Municipality.PENDING, created_by=other
    )
    client.force_login(operator)
    url = reverse("emergencies:emergency_create")

    response = client.post(url, form_data(own, flood))
    assert response.status_code == 302

    response = client.post(url, form_data(foreign, flood))
    assert response.status_code == 200
    assert Emergency.objects.count() == 1


def test_inactive_type_is_not_offered_but_kept_on_edit(client, make_emergency, medellin):
    retired = EmergencyType.objects.create(name="Retired", is_active=False)
    emergency = make_emergency(emergency_type=retired)
    client.force_login(make_user("olga", OPERATOR))

    assert client.post(
        reverse("emergencies:emergency_create"), form_data(medellin, retired)
    ).status_code == 200

    response = client.post(
        reverse("emergencies:emergency_edit", args=[emergency.pk]),
        form_data(medellin, retired, site="Updated site"),
    )
    assert response.status_code == 302
    emergency.refresh_from_db()
    assert emergency.site == "Updated site"


def test_edit_updates_emergency(client, make_emergency, medellin, flood):
    emergency = make_emergency()
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(
        reverse("emergencies:emergency_edit", args=[emergency.pk]),
        form_data(medellin, flood, site="New site"),
    )
    assert response.status_code == 302
    emergency.refresh_from_db()
    assert emergency.site == "New site"


def test_list_filters_and_bad_page(client, antioquia, medellin, make_emergency, flood, earthquake):
    bogota = Municipality.objects.create(department=antioquia, code="05002", name="BOGOTÁ")
    make_emergency(municipality=medellin, status=REPORTED)
    make_emergency(municipality=bogota, status=IN_RESPONSE, emergency_type=earthquake)
    client.force_login(make_user("rita", RISK_MANAGER))
    url = reverse("emergencies:emergency_list")

    def listed(**params):
        response = client.get(url, params)
        assert response.status_code == 200
        return list(response.context["page"].object_list)

    assert len(listed()) == 2
    assert [e.municipality for e in listed(status=IN_RESPONSE)] == [bogota]
    assert [e.municipality for e in listed(type=flood.pk)] == [medellin]
    assert [e.municipality for e in listed(q="medellin")] == [medellin]
    assert [e.municipality for e in listed(q="bogota")] == [bogota]
    assert len(listed(status="nonsense", type="abc")) == 2
    assert client.get(url, {"page": "abc"}).status_code == 200


def test_list_paginates_by_25(client, make_emergency):
    for _ in range(26):
        make_emergency()
    client.force_login(make_user("rita", RISK_MANAGER))
    response = client.get(reverse("emergencies:emergency_list"))
    assert len(response.context["page"].object_list) == 25
    assert response.context["page"].paginator.num_pages == 2


def test_action_owner_list_shows_only_own(client, make_emergency):
    mine = make_emergency()
    make_emergency()
    owner = make_user("omar", ACTION_OWNER)
    give_action(mine, owner)
    client.force_login(owner)
    page = client.get(reverse("emergencies:emergency_list")).context["page"]
    assert list(page.object_list) == [mine]


def test_status_change_via_post(client, make_emergency):
    emergency = make_emergency()
    operator = make_user("olga", OPERATOR)
    client.force_login(operator)
    url = reverse("emergencies:status_change", args=[emergency.pk])

    assert client.get(url).status_code == 405

    response = client.post(url, {"status": IN_RESPONSE, "note": "Teams deployed"})
    assert response.status_code == 302
    assert response["Location"] == reverse("emergencies:emergency_detail", args=[emergency.pk])
    emergency.refresh_from_db()
    assert emergency.status == IN_RESPONSE
    entry = StatusLog.objects.filter(emergency=emergency).last()
    assert (entry.status, entry.previous_status, entry.note, entry.author) == (
        IN_RESPONSE,
        REPORTED,
        "Teams deployed",
        operator,
    )


def test_operator_cannot_close(client, make_emergency):
    emergency = make_emergency(status=CONTROLLED)
    Impact.objects.create(emergency=emergency)
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(reverse("emergencies:status_change", args=[emergency.pk]), {"status": CLOSED})
    assert response.status_code == 403
    emergency.refresh_from_db()
    assert emergency.status == CONTROLLED


def test_close_without_impact_shows_message(client, make_emergency):
    emergency = make_emergency(status=CONTROLLED)
    client.force_login(make_user("rita", RISK_MANAGER))
    response = client.post(
        reverse("emergencies:status_change", args=[emergency.pk]), {"status": CLOSED}, follow=True
    )
    assert response.redirect_chain[-1][0] == reverse("emergencies:emergency_detail", args=[emergency.pk])
    assert "Record the impact before closing." in response.content.decode()
    emergency.refresh_from_db()
    assert emergency.status == CONTROLLED


def test_risk_manager_closes_with_impact(client, make_emergency):
    emergency = make_emergency(status=CONTROLLED)
    Impact.objects.create(emergency=emergency)
    client.force_login(make_user("rita", RISK_MANAGER))
    client.post(reverse("emergencies:status_change", args=[emergency.pk]), {"status": CLOSED})
    emergency.refresh_from_db()
    assert emergency.status == CLOSED
    assert emergency.closed_at is not None


def test_impact_is_saved_and_validated(client, make_emergency):
    emergency = make_emergency()
    operator = make_user("olga", OPERATOR)
    client.force_login(operator)
    url = reverse("emergencies:impact_edit", args=[emergency.pk])
    values = {
        "deceased": 1,
        "injured": 2,
        "missing": 3,
        "people_affected": 100,
        "families_affected": 30,
        "homes_destroyed": 4,
        "homes_damaged": 5,
        "roads_damaged": 6,
        "bridges_damaged": 7,
        "hectares": "12.5",
    }

    response = client.post(url, values)
    assert response.status_code == 302
    assert response["Location"] == reverse("emergencies:emergency_detail", args=[emergency.pk])
    impact = Impact.objects.get(emergency=emergency)
    assert (impact.people_affected, impact.hectares, impact.recorded_by) == (100, 12.5, operator)

    for field in values:
        bad = client.post(url, {**values, field: "-1"})
        assert bad.status_code == 200, field
    impact.refresh_from_db()
    assert impact.hectares == 12.5


def test_note_add(client, make_emergency):
    emergency = make_emergency()
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("emergencies:note_add", args=[emergency.pk])

    assert client.get(url).status_code == 405

    response = client.post(url, {"note": "Road reopened"})
    assert response.status_code == 302
    assert StatusLog.objects.filter(emergency=emergency, note="Road reopened").exists()

    response = client.post(url, {"note": "   "}, follow=True)
    assert "Write a note." in response.content.decode()


def test_closed_emergency_refuses_posts(client, make_emergency, medellin, flood):
    emergency = make_emergency(status=CLOSED)
    client.force_login(make_user("rita", RISK_MANAGER))
    pk = [emergency.pk]
    assert client.get(reverse("emergencies:emergency_edit", args=pk)).status_code == 403
    assert client.post(
        reverse("emergencies:emergency_edit", args=pk), form_data(medellin, flood)
    ).status_code == 403
    assert client.get(reverse("emergencies:impact_edit", args=pk)).status_code == 403
    assert client.post(reverse("emergencies:impact_edit", args=pk), {}).status_code == 403
    assert client.post(reverse("emergencies:note_add", args=pk), {"note": "x"}).status_code == 403
    response = client.post(reverse("emergencies:status_change", args=pk), {"status": IN_RESPONSE})
    assert response.status_code == 302
    emergency.refresh_from_db()
    assert emergency.status == CLOSED
    assert client.get(reverse("emergencies:emergency_detail", args=pk)).status_code == 200


def test_detail_buttons_follow_policy(client, make_emergency):
    emergency = make_emergency(status=CONTROLLED)
    url = reverse("emergencies:emergency_detail", args=[emergency.pk])
    status_url = reverse("emergencies:status_change", args=[emergency.pk])

    client.force_login(make_user("olga", OPERATOR))
    html = client.get(url).content.decode()
    assert reverse("emergencies:emergency_edit", args=[emergency.pk]) in html
    assert 'value="closed"' not in html
    assert 'value="in_response"' in html
    assert status_url in html

    client.force_login(make_user("rita", RISK_MANAGER))
    assert 'value="closed"' in client.get(url).content.decode()

    owner = make_user("omar", ACTION_OWNER)
    give_action(emergency, owner)
    client.force_login(owner)
    html = client.get(url).content.decode()
    assert reverse("emergencies:emergency_edit", args=[emergency.pk]) not in html
    assert status_url not in html


@pytest.mark.parametrize("role", [ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER])
def test_nav_shows_emergencies_link(client, db, role):
    client.force_login(make_user("ana", role))
    html = client.get(reverse("home")).content.decode()
    assert reverse("emergencies:emergency_list") in html


def test_nav_hides_link_without_role(client, db):
    client.force_login(make_user("nora"))
    response = client.get(reverse("accounts:pending"))
    assert response.status_code == 200
    assert reverse("emergencies:emergency_list") not in response.content.decode()


def test_edit_cannot_reopen_concurrently_closed_emergency(
    client, make_emergency, medellin, flood, monkeypatch
):
    emergency = make_emergency(status=CONTROLLED)
    Impact.objects.create(emergency=emergency)
    client.force_login(make_user("olga", OPERATOR))
    original_is_valid = EmergencyForm.is_valid

    def close_then_validate(form):
        change_status(Emergency.objects.get(pk=emergency.pk), CLOSED, make_user("rita", RISK_MANAGER))
        return original_is_valid(form)

    monkeypatch.setattr(EmergencyForm, "is_valid", close_then_validate)
    response = client.post(
        reverse("emergencies:emergency_edit", args=[emergency.pk]),
        form_data(medellin, flood, site="Late edit"),
    )
    closed_at = Emergency.objects.get(pk=emergency.pk).closed_at
    assert response.status_code == 403
    stored = Emergency.objects.get(pk=emergency.pk)
    assert stored.status == CLOSED
    assert stored.closed_at == closed_at is not None
    assert stored.site != "Late edit"


def test_edit_refuses_another_operators_pending_municipality(
    client, make_emergency, antioquia, medellin, flood
):
    other = make_user("otto", OPERATOR)
    foreign = Municipality.objects.create(
        department=antioquia, name="Otra Villa", validation=Municipality.PENDING, created_by=other
    )
    emergency = make_emergency()
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(
        reverse("emergencies:emergency_edit", args=[emergency.pk]), form_data(foreign, flood)
    )
    assert response.status_code == 200
    assert response.context["form"].errors["municipality"]
    emergency.refresh_from_db()
    assert emergency.municipality == medellin


def test_list_is_newest_first(client, make_emergency):
    now = timezone.now()
    old = make_emergency(occurred_at=now - timedelta(days=5))
    new = make_emergency(occurred_at=now - timedelta(days=1))
    middle = make_emergency(occurred_at=now - timedelta(days=3))
    client.force_login(make_user("rita", RISK_MANAGER))
    page = client.get(reverse("emergencies:emergency_list")).context["page"]
    assert list(page.object_list) == [new, middle, old]


def test_repeated_status_change_shows_message(client, make_emergency):
    emergency = make_emergency()
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("emergencies:status_change", args=[emergency.pk])
    detail = reverse("emergencies:emergency_detail", args=[emergency.pk])

    assert client.post(url, {"status": IN_RESPONSE}).status_code == 302
    response = client.post(url, {"status": IN_RESPONSE}, follow=True)
    assert response.redirect_chain[-1][0] == detail
    assert "Cannot move from In response to In response." in response.content.decode()
    emergency.refresh_from_db()
    assert emergency.status == IN_RESPONSE
    assert StatusLog.objects.filter(emergency=emergency, status=IN_RESPONSE).count() == 1


def test_stale_status_change_shows_message(client, make_emergency):
    emergency = make_emergency()
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("emergencies:status_change", args=[emergency.pk])
    response = client.post(url, {"status": CONTROLLED}, follow=True)
    assert "Cannot move from Reported to Controlled." in response.content.decode()
    emergency.refresh_from_db()
    assert emergency.status == REPORTED


def test_status_change_role_refusals(client, make_emergency):
    emergency = make_emergency()
    url = reverse("emergencies:status_change", args=[emergency.pk])
    client.force_login(make_user("olga", OPERATOR))
    assert client.post(url, {"status": "flying"}).status_code == 403
    assert client.post(url, {"status": CLOSED}).status_code == 403
    emergency.refresh_from_db()
    assert emergency.status == REPORTED


def test_repeated_close_shows_message(client, make_emergency):
    emergency = make_emergency(status=CONTROLLED)
    Impact.objects.create(emergency=emergency)
    client.force_login(make_user("rita", RISK_MANAGER))
    url = reverse("emergencies:status_change", args=[emergency.pk])
    detail = reverse("emergencies:emergency_detail", args=[emergency.pk])

    assert client.post(url, {"status": CLOSED}).status_code == 302
    emergency.refresh_from_db()
    assert emergency.status == CLOSED
    response = client.post(url, {"status": CLOSED}, follow=True)
    assert response.redirect_chain == [(detail, 302)]
    assert "This emergency is closed." in response.content.decode()
    assert StatusLog.objects.filter(emergency=emergency, status=CLOSED).count() == 1


def test_status_post_on_closed_emergency(client, make_emergency):
    emergency = make_emergency(status=CLOSED)
    url = reverse("emergencies:status_change", args=[emergency.pk])
    detail = reverse("emergencies:emergency_detail", args=[emergency.pk])

    client.force_login(make_user("olga", OPERATOR))
    for status in (CLOSED, IN_RESPONSE):
        response = client.post(url, {"status": status}, follow=True)
        assert response.redirect_chain == [(detail, 302)]
        assert "This emergency is closed." in response.content.decode()
    assert client.post(url, {"status": "flying"}).status_code == 403

    owner = make_user("omar", ACTION_OWNER)
    give_action(emergency, owner)
    client.force_login(owner)
    assert client.post(url, {"status": CLOSED}).status_code == 403
    emergency.refresh_from_db()
    assert emergency.status == CLOSED
    assert not StatusLog.objects.filter(emergency=emergency).exists()
