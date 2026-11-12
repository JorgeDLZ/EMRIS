from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, OPERATOR
from apps.emergencies.models import CLOSED, Emergency, EmergencyType
from apps.emergencies.workflow import WorkflowError
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan
from apps.seismic.models import SeismicEvent
from apps.seismic.services import clear_link, confirm_link, suggest_link

PASSWORD = "pass-12345"
NO_MATCH = "No SGC event matches; enter magnitude and depth in the form."


def make_user(username, role):
    user = User.objects.create_user(username, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def bogota(db):
    department = Department.objects.create(code="11", name="BOGOTÁ")
    return Municipality.objects.create(
        department=department, code="11001", name="BOGOTÁ", latitude=4.6, longitude=-74.1
    )


@pytest.fixture
def no_coordinates(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    return Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")


@pytest.fixture
def earthquake(db):
    return EmergencyType.objects.create(name="Earthquake", seed_key="Earthquake")


@pytest.fixture
def flood(db):
    return EmergencyType.objects.create(name="Flood")


def make_emergency(emergency_type, municipality, **extra):
    return Emergency.objects.create(
        emergency_type=emergency_type,
        municipality=municipality,
        occurred_at=timezone.now() - timedelta(hours=1),
        **extra,
    )


def make_event(sgc_id, magnitude, event_time=None, latitude=4.6, longitude=-74.1):
    return SeismicEvent.objects.create(
        sgc_id=sgc_id,
        event_time=event_time or timezone.now() - timedelta(hours=2),
        magnitude=magnitude,
        depth_km=12.0,
        latitude=latitude,
        longitude=longitude,
        place="Bogotá - Bogotá, Colombia",
    )


def detail_url(emergency):
    return reverse("emergencies:emergency_detail", args=[emergency.pk])


def test_suggests_largest_event_in_window(db, bogota, earthquake):
    emergency = make_emergency(earthquake, bogota)
    make_event("near", 4.1, latitude=4.61)
    big = make_event("far", 5.3, latitude=4.8)
    make_event("later", 6.5, event_time=timezone.now() + timedelta(days=3))
    suggestion = suggest_link(emergency)
    assert suggestion.event == big
    assert suggestion.distance_km > 0


def test_no_suggestion_without_coordinates(client, db, no_coordinates, earthquake):
    emergency = make_emergency(earthquake, no_coordinates)
    make_event("any", 5.0)
    assert suggest_link(emergency) is None
    client.force_login(make_user("olga", OPERATOR))
    assert NO_MATCH in client.get(detail_url(emergency)).content.decode()


def test_no_suggestion_for_other_types(client, db, bogota, flood):
    emergency = make_emergency(flood, bogota)
    make_event("any", 5.0)
    assert suggest_link(emergency) is None
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(detail_url(emergency)).content.decode()
    assert NO_MATCH not in content
    assert "SGC" not in content


def test_confirm_stores_link_and_magnitude_shows(client, db, bogota, earthquake):
    emergency = make_emergency(earthquake, bogota)
    event = make_event("ev1", 5.3)
    client.force_login(make_user("olga", OPERATOR))
    assert "Confirm" in client.get(detail_url(emergency)).content.decode()
    response = client.post(reverse("emergencies:seismic_confirm", args=[emergency.pk]))
    assert response.status_code == 302
    emergency.refresh_from_db()
    assert emergency.seismic_event == event
    assert emergency.seismic_link_distance_km is not None
    content = client.get(detail_url(emergency)).content.decode()
    assert "Magnitude: 5.3" in content
    assert "ev1" in content


def test_confirm_without_match_reports_error(client, db, bogota, earthquake):
    emergency = make_emergency(earthquake, bogota)
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(reverse("emergencies:seismic_confirm", args=[emergency.pk]), follow=True)
    emergency.refresh_from_db()
    assert emergency.seismic_event is None
    assert NO_MATCH in response.content.decode()


def test_closed_emergency_refuses_link_changes(client, db, bogota, earthquake):
    emergency = make_emergency(earthquake, bogota, status=CLOSED)
    make_event("ev1", 5.3)
    client.force_login(make_user("olga", OPERATOR))
    assert client.post(reverse("emergencies:seismic_confirm", args=[emergency.pk])).status_code == 403
    assert client.post(reverse("emergencies:seismic_clear", args=[emergency.pk])).status_code == 403
    for change in (confirm_link, clear_link):
        with pytest.raises(WorkflowError, match="This emergency is closed."):
            change(Emergency.objects.get(pk=emergency.pk))
    emergency.refresh_from_db()
    assert emergency.seismic_event is None


def test_close_during_request_shows_message(client, db, bogota, earthquake, monkeypatch):
    emergency = make_emergency(earthquake, bogota)
    make_event("ev1", 5.3)

    def refuse(_emergency):
        raise WorkflowError("This emergency is closed.")

    monkeypatch.setattr("apps.emergencies.views.confirm_link", refuse)
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(reverse("emergencies:seismic_confirm", args=[emergency.pk]), follow=True)
    assert "This emergency is closed." in response.content.decode()


def test_clear_removes_link(client, db, bogota, earthquake):
    event = make_event("ev1", 5.3)
    emergency = make_emergency(
        earthquake, bogota, seismic_event=event, seismic_link_distance_km=3.0
    )
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(reverse("emergencies:seismic_clear", args=[emergency.pk]))
    assert response.status_code == 302
    emergency.refresh_from_db()
    assert emergency.seismic_event is None
    assert emergency.seismic_link_distance_km is None


def test_seismic_actions_require_post(client, db, bogota, earthquake):
    emergency = make_emergency(earthquake, bogota)
    client.force_login(make_user("olga", OPERATOR))
    assert client.get(reverse("emergencies:seismic_confirm", args=[emergency.pk])).status_code == 405
    assert client.get(reverse("emergencies:seismic_clear", args=[emergency.pk])).status_code == 405


def test_manual_magnitude_saves_without_event(client, db, bogota, earthquake):
    emergency = make_emergency(earthquake, bogota)
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(
        reverse("emergencies:emergency_edit", args=[emergency.pk]),
        {
            "emergency_type": earthquake.pk,
            "municipality": bogota.pk,
            "site": "",
            "occurred_at": timezone.localtime(emergency.occurred_at).strftime("%Y-%m-%dT%H:%M"),
            "description": "",
            "reported_magnitude": "4.2",
            "reported_depth_km": "10",
        },
    )
    assert response.status_code == 302
    emergency.refresh_from_db()
    assert emergency.seismic_event is None
    assert (emergency.magnitude, emergency.depth_km) == (4.2, 10.0)


def test_action_owner_cannot_confirm(client, db, bogota, earthquake):
    make_event("ev1", 5.3)
    owner = make_user("omar", ACTION_OWNER)
    own = make_emergency(earthquake, bogota)
    plan = ActionPlan.objects.create(emergency=own)
    Action.objects.create(plan=plan, description="Deliver kits", owner=owner)
    other = make_emergency(earthquake, bogota)
    client.force_login(owner)
    for name in ("seismic_confirm", "seismic_clear"):
        assert client.post(reverse(f"emergencies:{name}", args=[own.pk])).status_code == 403
        assert client.post(reverse(f"emergencies:{name}", args=[other.pk])).status_code == 403
    own.refresh_from_db()
    assert own.seismic_event is None


def test_window_uses_bogota_date(db, bogota, earthquake):
    emergency = Emergency.objects.create(
        emergency_type=earthquake,
        municipality=bogota,
        occurred_at=datetime(2026, 3, 11, 2, 0, tzinfo=dt_timezone.utc),
    )
    inside = make_event(
        "day-before", 5.0, event_time=datetime(2026, 3, 10, 12, 0, tzinfo=dt_timezone.utc)
    )
    make_event(
        "utc-day-only", 6.0, event_time=datetime(2026, 3, 11, 15, 0, tzinfo=dt_timezone.utc)
    )
    assert suggest_link(emergency).event == inside


def edit_payload(emergency, **extra):
    data = {
        "emergency_type": emergency.emergency_type_id,
        "municipality": emergency.municipality_id,
        "site": "",
        "occurred_at": timezone.localtime(emergency.occurred_at).strftime("%Y-%m-%dT%H:%M"),
        "description": "",
    }
    data.update(extra)
    return data


@pytest.fixture
def linked(db, bogota, earthquake):
    event = make_event("ev1", 5.3)
    return make_emergency(earthquake, bogota, seismic_event=event, seismic_link_distance_km=3.0)


def edit(client, emergency, **extra):
    client.force_login(make_user("olga", OPERATOR))
    response = client.post(
        reverse("emergencies:emergency_edit", args=[emergency.pk]), edit_payload(emergency, **extra)
    )
    assert response.status_code == 302
    emergency.refresh_from_db()


def test_edit_to_other_type_clears_link(client, linked, flood):
    edit(client, linked, emergency_type=flood.pk)
    assert linked.seismic_event is None
    assert linked.seismic_link_distance_km is None


def test_edit_municipality_clears_link(client, linked, no_coordinates):
    edit(client, linked, municipality=no_coordinates.pk)
    assert linked.seismic_event is None
    assert linked.seismic_link_distance_km is None


def test_edit_date_clears_link_and_keeps_manual_values(client, linked):
    Emergency.objects.filter(pk=linked.pk).update(reported_magnitude=4.2, reported_depth_km=10)
    earlier = timezone.localtime(linked.occurred_at - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    edit(client, linked, occurred_at=earlier, reported_magnitude="4.2", reported_depth_km="10")
    assert linked.seismic_event is None
    assert (linked.reported_magnitude, linked.reported_depth_km) == (4.2, 10.0)


def test_edit_site_and_description_keep_link(client, linked):
    event = linked.seismic_event
    edit(client, linked, site="Downtown", description="Felt widely")
    assert linked.seismic_event == event
    assert linked.seismic_link_distance_km == 3.0


def test_closed_emergency_shows_no_suggestion(client, db, bogota, earthquake, monkeypatch):
    emergency = make_emergency(earthquake, bogota, status=CLOSED)
    make_event("ev1", 5.3)

    def refuse(_emergency):
        raise AssertionError("suggest_link must not run for a closed emergency")

    monkeypatch.setattr("apps.emergencies.views.suggest_link", refuse)
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(detail_url(emergency)).content.decode()
    assert "Suggested:" not in content
    assert NO_MATCH not in content


def test_read_only_viewer_sees_link_without_suggestion(client, db, bogota, earthquake):
    owner = make_user("omar", ACTION_OWNER)
    event = make_event("ev1", 5.3)
    unlinked = make_emergency(earthquake, bogota)
    linked = make_emergency(earthquake, bogota, seismic_event=event, seismic_link_distance_km=3.0)
    no_match = Emergency.objects.create(
        emergency_type=earthquake,
        municipality=bogota,
        occurred_at=timezone.now() - timedelta(days=30),
    )
    for emergency in (unlinked, linked, no_match):
        plan = ActionPlan.objects.create(emergency=emergency)
        Action.objects.create(plan=plan, description="Deliver kits", owner=owner)
    client.force_login(owner)

    content = client.get(detail_url(unlinked)).content.decode()
    assert "Suggested:" not in content
    assert reverse("emergencies:seismic_confirm", args=[unlinked.pk]) not in content
    assert NO_MATCH not in client.get(detail_url(no_match)).content.decode()

    content = client.get(detail_url(linked)).content.decode()
    assert "SGC id ev1" in content
    assert reverse("emergencies:seismic_clear", args=[linked.pk]) not in content


def test_closed_linked_emergency_shows_event(client, db, bogota, earthquake):
    event = make_event("ev1", 5.3)
    emergency = make_emergency(
        earthquake, bogota, status=CLOSED, seismic_event=event, seismic_link_distance_km=3.0
    )
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(detail_url(emergency)).content.decode()
    assert "SGC id ev1" in content
    assert reverse("emergencies:seismic_clear", args=[emergency.pk]) not in content
