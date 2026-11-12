import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.emergencies.models import (
    CLOSED,
    CONTROLLED,
    IN_RESPONSE,
    REPORTED,
    Emergency,
    EmergencyType,
    Impact,
)
from apps.emergencies.workflow import (
    WorkflowError,
    add_note,
    change_status,
    create_emergency,
    save_impact,
)
from apps.places.models import Department, Municipality
from apps.seismic.models import SeismicEvent


@pytest.fixture
def actor(db):
    return User.objects.create_user("operator", password="pass-12345")


@pytest.fixture
def emergency(actor):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood = EmergencyType.objects.create(name="Flood")
    return create_emergency(
        actor, emergency_type=flood, municipality=municipality, occurred_at=timezone.now()
    )


def test_create_logs_reported(emergency):
    assert emergency.status == REPORTED
    entry = emergency.status_log.get()
    assert entry.status == REPORTED
    assert entry.previous_status == ""
    assert entry.note == "Emergency reported"
    assert not entry.is_status_change


def test_forward_flow_and_back_to_response(emergency, actor):
    for target in (IN_RESPONSE, CONTROLLED, IN_RESPONSE, CONTROLLED):
        change_status(emergency, target, actor)
        emergency.refresh_from_db()
        assert emergency.status == target
    assert emergency.status_log.count() == 5
    assert emergency.status_log.last().is_status_change


def test_jumps_are_refused(emergency, actor):
    with pytest.raises(WorkflowError, match="Cannot move from Reported to Closed."):
        change_status(emergency, CLOSED, actor)
    with pytest.raises(WorkflowError, match="Cannot move from Reported to Controlled."):
        change_status(emergency, CONTROLLED, actor)
    emergency.refresh_from_db()
    assert emergency.status == REPORTED


def test_close_requires_impact(emergency, actor):
    change_status(emergency, IN_RESPONSE, actor)
    change_status(emergency, CONTROLLED, actor)
    with pytest.raises(WorkflowError, match="Record the impact before closing."):
        change_status(emergency, CLOSED, actor)
    emergency.refresh_from_db()
    assert emergency.status == CONTROLLED


def test_close_sets_closed_at_and_locks(emergency, actor):
    change_status(emergency, IN_RESPONSE, actor)
    change_status(emergency, CONTROLLED, actor)
    save_impact(emergency, actor, {"deceased": 2, "hectares": 1.5})
    change_status(emergency, CLOSED, actor)
    emergency.refresh_from_db()
    assert emergency.is_closed
    assert emergency.closed_at is not None
    assert emergency.impact.deceased == 2
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        change_status(emergency, IN_RESPONSE, actor)
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        add_note(emergency, actor, "late note")
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        save_impact(emergency, actor, {"deceased": 3})


def test_non_closing_transition_leaves_closed_at_empty(emergency, actor):
    emergency.closed_at = timezone.now()
    change_status(emergency, IN_RESPONSE, actor)
    emergency.refresh_from_db()
    assert emergency.closed_at is None


def test_add_note_and_blank_note(emergency, actor):
    entry = add_note(emergency, actor, "Road reopened")
    assert entry.status == REPORTED
    assert entry.previous_status == ""
    assert entry.note == "Road reopened"
    with pytest.raises(WorkflowError, match="Write a note."):
        add_note(emergency, actor, "   ")


def test_save_impact_creates_then_updates(emergency, actor):
    first = save_impact(emergency, actor, {"injured": 4})
    second = save_impact(emergency, actor, {"injured": 7})
    assert first.pk == second.pk
    assert Impact.objects.get().injured == 7
    assert second.recorded_by == actor


def test_magnitude_prefers_linked_event(emergency):
    emergency.reported_magnitude = 4.0
    emergency.reported_depth_km = 10.0
    assert emergency.magnitude == 4.0
    assert emergency.depth_km == 10.0
    emergency.seismic_event = SeismicEvent(
        sgc_id="x", event_time=timezone.now(), magnitude=5.3, depth_km=22.0,
        latitude=1.0, longitude=1.0, place="p",
    )
    assert emergency.magnitude == 5.3
    assert emergency.depth_km == 22.0


def test_is_earthquake(emergency):
    assert not emergency.is_earthquake
    quake = EmergencyType.objects.create(name="Earthquake", seed_key="Earthquake")
    assert Emergency(emergency_type=quake).is_earthquake


def stale_pair(emergency, actor):
    change_status(emergency, IN_RESPONSE, actor)
    change_status(emergency, CONTROLLED, actor)
    save_impact(emergency, actor, {"deceased": 1})
    return Emergency.objects.get(pk=emergency.pk), Emergency.objects.get(pk=emergency.pk)


def test_stale_copy_cannot_reopen_closed(emergency, actor):
    first, second = stale_pair(emergency, actor)
    change_status(first, CLOSED, actor)
    closed_at = Emergency.objects.get(pk=first.pk).closed_at
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        change_status(second, IN_RESPONSE, actor)
    row = Emergency.objects.get(pk=first.pk)
    assert row.status == CLOSED
    assert row.closed_at == closed_at


def test_stale_copy_cannot_edit_closed(emergency, actor):
    first, second = stale_pair(emergency, actor)
    change_status(first, CLOSED, actor)
    logs = emergency.status_log.count()
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        save_impact(second, actor, {"deceased": 9})
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        add_note(second, actor, "x")
    assert Impact.objects.get().deceased == 1
    assert emergency.status_log.count() == logs


def test_stale_second_close_logs_once(emergency, actor):
    first, second = stale_pair(emergency, actor)
    change_status(first, CLOSED, actor)
    with pytest.raises(WorkflowError, match="This emergency is closed."):
        change_status(second, CLOSED, actor)
    assert emergency.status_log.filter(status=CLOSED).count() == 1


def test_caller_object_sees_new_state(emergency, actor):
    change_status(emergency, IN_RESPONSE, actor)
    assert emergency.status == IN_RESPONSE
    change_status(emergency, CONTROLLED, actor)
    save_impact(emergency, actor, {"deceased": 1})
    change_status(emergency, CLOSED, actor)
    assert emergency.is_closed
    assert emergency.closed_at is not None
