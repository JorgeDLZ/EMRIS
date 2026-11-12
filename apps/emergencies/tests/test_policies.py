import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies import policies
from apps.emergencies.models import (
    CLOSED,
    CONTROLLED,
    IN_RESPONSE,
    REPORTED,
    Emergency,
    EmergencyType,
)
from apps.places.models import Department, Municipality
from apps.plans.models import APPROVED, DRAFT, Action, ActionPlan

ROLES = [ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER, None, "superuser", "anonymous"]
EDITORS = {ADMINISTRATOR, RISK_MANAGER, OPERATOR, "superuser"}
MANAGERS = {ADMINISTRATOR, RISK_MANAGER, "superuser"}


def make_user(role):
    if role == "anonymous":
        return AnonymousUser()
    user = User.objects.create_user(f"user-{role}", password="pass-12345")
    if role == "superuser":
        user.is_superuser = True
        user.save()
    elif role is not None:
        user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def municipality(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    return Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")


@pytest.fixture
def make_emergency(municipality):
    flood = EmergencyType.objects.create(name="Flood")

    def build(status=REPORTED):
        return Emergency.objects.create(
            emergency_type=flood,
            municipality=municipality,
            occurred_at=timezone.now(),
            status=status,
        )

    return build


def make_plan(emergency, status=DRAFT):
    return ActionPlan.objects.create(emergency=emergency, status=status)


@pytest.mark.parametrize("role", ROLES)
def test_visible_emergencies_by_role(make_emergency, role):
    first = make_emergency()
    second = make_emergency()
    user = make_user(role)
    if role == ACTION_OWNER:
        Action.objects.create(plan=make_plan(first), description="Evacuate", owner=user)
    Action.objects.create(plan=make_plan(second), description="Shelter")
    visible = set(policies.visible_emergencies(user))
    if role in EDITORS:
        assert visible == {first, second}
    elif role == ACTION_OWNER:
        assert visible == {first}
    else:
        assert visible == set()


def test_action_owner_with_two_actions_sees_emergency_once(make_emergency):
    emergency = make_emergency()
    user = make_user(ACTION_OWNER)
    plan = make_plan(emergency)
    Action.objects.create(plan=plan, description="Evacuate", owner=user)
    Action.objects.create(plan=plan, description="Shelter", owner=user)
    assert list(policies.visible_emergencies(user)) == [emergency]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (REPORTED, [IN_RESPONSE]),
        (IN_RESPONSE, [CONTROLLED]),
        (CONTROLLED, [CLOSED, IN_RESPONSE]),
        (CLOSED, []),
    ],
)
def test_status_choices_by_role(make_emergency, role, status, expected):
    emergency = make_emergency(status)
    allowed = policies.allowed_statuses(make_user(role), emergency)
    if role not in EDITORS:
        assert allowed == []
    elif role in MANAGERS:
        assert allowed == expected
    else:
        assert allowed == [target for target in expected if target != CLOSED]


@pytest.mark.parametrize("role", ROLES)
def test_edit_rights_and_resources(make_emergency, role):
    user = make_user(role)
    emergency = make_emergency()
    assert policies.can_edit_emergency(user, emergency) is (role in EDITORS)
    assert policies.can_start_plan(user, emergency) is (role in EDITORS)
    assert policies.can_manage_resources(user) is (role in MANAGERS)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("plan_status", [DRAFT, APPROVED])
def test_plan_rights(make_emergency, role, plan_status):
    user = make_user(role)
    plan = make_plan(make_emergency(IN_RESPONSE), plan_status)
    can_edit = role in MANAGERS or (role == OPERATOR and plan_status == DRAFT)
    assert policies.can_edit_plan(user, plan) is can_edit
    assert policies.can_approve_plan(user, plan) is (role in MANAGERS)


@pytest.mark.parametrize("role", ROLES)
def test_action_owner_updates_only_own_action(make_emergency, role):
    user = make_user(role)
    other = User.objects.create_user("someone-else", password="pass-12345")
    plan = make_plan(make_emergency(IN_RESPONSE), APPROVED)
    owner = user if role not in (None, "anonymous") else None
    own = Action.objects.create(plan=plan, description="Evacuate", owner=owner)
    foreign = Action.objects.create(plan=plan, description="Shelter", owner=other)
    assert policies.can_update_action(user, foreign) is (role in EDITORS)
    assert policies.can_update_action(user, own) is (role in EDITORS or role == ACTION_OWNER)


@pytest.mark.parametrize("role", ROLES)
def test_closed_emergency_refuses_everything(make_emergency, role):
    user = make_user(role)
    emergency = make_emergency(CLOSED)
    plan = make_plan(emergency)
    owner = user if role != "anonymous" else None
    action = Action.objects.create(plan=plan, description="Evacuate", owner=owner)
    assert not policies.can_edit_emergency(user, emergency)
    assert not policies.can_start_plan(user, emergency)
    assert not policies.can_edit_plan(user, plan)
    assert not policies.can_approve_plan(user, plan)
    assert not policies.can_update_action(user, action)
    assert policies.allowed_statuses(user, emergency) == []


def test_user_navigation_properties(db):
    for role in ROLES[:-1]:
        user = make_user(role)
        assert user.can_edit_emergencies is (role in EDITORS)
        assert user.can_manage_resources is (role in MANAGERS)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("current", [REPORTED, IN_RESPONSE, CONTROLLED, CLOSED])
def test_can_set_status_is_role_only(make_emergency, role, current):
    user = make_user(role)
    emergency = make_emergency(current)
    for target in (REPORTED, IN_RESPONSE, CONTROLLED):
        assert policies.can_set_status(user, emergency, target) is (role in EDITORS)
    closers = EDITORS if current == CLOSED else MANAGERS
    assert policies.can_set_status(user, emergency, CLOSED) is (role in closers)
    assert policies.can_set_status(user, emergency, "flying") is False
