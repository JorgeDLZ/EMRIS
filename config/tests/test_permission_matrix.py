from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, CAPABILITIES, OPERATOR, RISK_MANAGER
from apps.emergencies.models import CLOSED, CONTROLLED, IN_RESPONSE, Emergency, EmergencyType
from apps.history.models import UngrdRecord
from apps.places.models import Department, Municipality
from apps.plans.models import APPROVED, DRAFT, IN_PROGRESS, PENDING, Action, ActionPlan

PUBLIC_VIEWS = {
    "home",
    "health",
    "accounts:login",
    "accounts:logout",
    "accounts:register",
    "accounts:pending",
}


def named_patterns(patterns, namespace=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            if pattern.namespace == "admin":
                continue
            prefix = f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            yield from named_patterns(pattern.url_patterns, prefix)
        elif isinstance(pattern, URLPattern):
            yield f"{namespace}{pattern.name}", pattern.callback


def test_capabilities_cover_every_view():
    allowed = set(CAPABILITIES.values())
    uncovered = [
        name
        for name, callback in named_patterns(get_resolver().url_patterns)
        if name not in PUBLIC_VIEWS and getattr(callback, "required_roles", None) not in allowed
    ]
    assert uncovered == []


@pytest.fixture
def world(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood = EmergencyType.objects.create(name="Flood")
    users = {}
    for role in (ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER):
        users[role] = User.objects.create_user(role, password="pass-12345")
        users[role].groups.add(Group.objects.get(name=role))
    other_owner = User.objects.create_user("other-owner", password="pass-12345")
    other_owner.groups.add(Group.objects.get(name=ACTION_OWNER))
    owner = users[ACTION_OWNER]

    def emergency(status, plan_status, action_owner):
        created = Emergency.objects.create(
            emergency_type=flood,
            municipality=municipality,
            occurred_at=timezone.now() - timedelta(hours=1),
            status=status,
        )
        plan = ActionPlan.objects.create(emergency=created, status=plan_status)
        action = Action.objects.create(plan=plan, description="Evacuate", owner=action_owner)
        return created, action

    open_emergency, own_action = emergency(CONTROLLED, DRAFT, owner)
    other_action = Action.objects.create(
        plan=open_emergency.action_plan, description="Shelter", owner=other_owner
    )
    approved_emergency, approved_action = emergency(IN_RESPONSE, APPROVED, owner)
    closed_emergency, _ = emergency(CLOSED, DRAFT, owner)
    foreign_emergency, _ = emergency(IN_RESPONSE, DRAFT, other_owner)
    UngrdRecord.objects.create(
        source_row=1,
        occurred_on=date(2020, 1, 10),
        department=department,
        municipality=municipality,
        emergency_type=flood,
    )
    return {
        "users": users,
        "open": open_emergency,
        "approved": approved_emergency,
        "closed": closed_emergency,
        "foreign": foreign_emergency,
        "own_action": own_action,
        "other_action": other_action,
        "approved_action": approved_action,
    }


ADMIN, MANAGER, OPER, OWNER = ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER

CASES = [
    ("emergencies:emergency_list", None, "get", {}, ADMIN, 200),
    ("emergencies:emergency_list", None, "get", {}, OWNER, 200),
    ("emergencies:emergency_create", None, "get", {}, OPER, 200),
    ("emergencies:emergency_create", None, "get", {}, OWNER, 403),
    ("emergencies:emergency_detail", "open", "get", {}, OWNER, 200),
    ("emergencies:emergency_detail", "foreign", "get", {}, OWNER, 404),
    ("emergencies:emergency_detail", "foreign", "get", {}, OPER, 200),
    ("emergencies:emergency_edit", "open", "get", {}, OPER, 200),
    ("emergencies:emergency_edit", "open", "get", {}, OWNER, 403),
    ("emergencies:emergency_edit", "closed", "get", {}, ADMIN, 403),
    ("emergencies:emergency_edit", "closed", "get", {}, MANAGER, 403),
    ("emergencies:emergency_edit", "closed", "get", {}, OPER, 403),
    ("emergencies:impact_edit", "closed", "get", {}, MANAGER, 403),
    ("emergencies:status_change", "open", "post", {"status": IN_RESPONSE}, OPER, 302),
    ("emergencies:status_change", "open", "post", {"status": CLOSED}, OPER, 403),
    ("emergencies:status_change", "open", "post", {"status": CLOSED}, MANAGER, 302),
    ("emergencies:status_change", "open", "post", {"status": IN_RESPONSE}, OWNER, 403),
    ("emergencies:type_list", None, "get", {}, MANAGER, 200),
    ("emergencies:type_list", None, "get", {}, OPER, 403),
    ("plans:plan_detail", "open", "get", {}, OWNER, 200),
    ("plans:plan_detail", "foreign", "get", {}, OWNER, 404),
    ("plans:plan_approve", "open", "post", {}, OPER, 403),
    ("plans:plan_approve", "open", "post", {}, OWNER, 403),
    ("plans:plan_approve", "open", "post", {}, MANAGER, 302),
    ("plans:action_create", "open", "get", {}, OPER, 200),
    ("plans:action_create", "approved", "get", {}, OPER, 403),
    ("plans:action_create", "approved", "get", {}, MANAGER, 200),
    ("plans:action_edit", "approved_action", "get", {}, OPER, 403),
    ("plans:action_edit", "approved_action", "get", {}, MANAGER, 200),
    ("plans:action_edit", "own_action", "get", {}, OWNER, 403),
    ("plans:action_advance", "own_action", "post", {}, OWNER, 302),
    ("plans:action_advance", "other_action", "post", {}, OWNER, 403),
    ("plans:action_advance", "own_action", "post", {}, OPER, 403),
    ("plans:action_advance", "own_action", "post", {}, MANAGER, 302),
    ("plans:plan_suggest", "approved", "post", {}, OPER, 403),
    ("plans:plan_suggest", "approved", "post", {}, OWNER, 403),
    ("plans:plan_suggest", "approved", "post", {}, MANAGER, 302),
    ("plans:plan_suggest", "open", "post", {}, OPER, 302),
    ("plans:resource_list", None, "get", {}, MANAGER, 200),
    ("plans:resource_list", None, "get", {}, OPER, 403),
    ("places:municipality_list", None, "get", {}, OPER, 200),
    ("places:municipality_list", None, "get", {}, OWNER, 403),
    ("places:municipality_pending", None, "get", {}, MANAGER, 200),
    ("places:municipality_pending", None, "get", {}, OPER, 403),
    ("dashboard:index", None, "get", {}, OWNER, 200),
    ("dashboard:ranking", None, "get", {}, OPER, 200),
    ("dashboard:ranking", None, "get", {}, OWNER, 403),
    ("history:record_list", None, "get", {}, OPER, 200),
    ("history:record_list", None, "get", {}, OWNER, 403),
    ("intelligence:model_list", None, "get", {}, ADMIN, 200),
    ("intelligence:model_list", None, "get", {}, MANAGER, 403),
    ("accounts:user_list", None, "get", {}, ADMIN, 200),
    ("accounts:user_list", None, "get", {}, MANAGER, 403),
]


def case_id(case):
    name, state, method, data, role, expected = case
    return f"{name}-{state}-{method}-{data.get('status', '')}-{role}-{expected}"


@pytest.mark.parametrize("case", CASES, ids=[case_id(case) for case in CASES])
def test_permission_matrix(client, world, case):
    name, state, method, data, role, expected = case
    args = [world[state].pk] if state else []
    client.force_login(world["users"][role])
    response = getattr(client, method)(reverse(name, args=args), data)
    assert response.status_code == expected


def test_suggest_refused_on_approved_plan_for_operator(client, world):
    url = reverse("plans:plan_suggest", args=[world["approved"].pk])
    client.force_login(world["users"][OPERATOR])
    assert client.post(url).status_code == 403
    html = client.get(reverse("plans:plan_detail", args=[world["approved"].pk])).content.decode()
    assert url not in html
    client.force_login(world["users"][RISK_MANAGER])
    assert client.post(url).status_code == 302


def test_history_forbidden_for_action_owner(client, world):
    urls = [
        reverse("history:record_list"),
        reverse("history:record_detail", args=[1]),
        reverse("history:export"),
    ]
    client.force_login(world["users"][ACTION_OWNER])
    for url in urls:
        assert client.get(url).status_code == 403
    html = client.get(reverse("dashboard:index")).content.decode()
    assert reverse("history:record_list") not in html
    client.force_login(world["users"][OPERATOR])
    for url in urls:
        assert client.get(url).status_code == 200
    html = client.get(reverse("dashboard:index")).content.decode()
    assert reverse("history:record_list") in html


def test_operator_advances_own_or_unassigned_action(client, world):
    operator = world["users"][OPERATOR]
    plan = world["open"].action_plan
    own = Action.objects.create(plan=plan, description="Own", owner=operator)
    unassigned = Action.objects.create(plan=plan, description="Unassigned")
    client.force_login(operator)
    for action in (own, unassigned):
        response = client.post(reverse("plans:action_advance", args=[action.pk]))
        assert response.status_code == 302
        action.refresh_from_db()
        assert action.status == IN_PROGRESS


def test_operator_cannot_advance_action_of_another_user(client, world):
    action = world["own_action"]
    url = reverse("plans:action_advance", args=[action.pk])
    client.force_login(world["users"][OPERATOR])
    assert client.post(url).status_code == 403
    action.refresh_from_db()
    assert action.status == PENDING
    for page in (
        reverse("plans:plan_detail", args=[world["open"].pk]),
        reverse("emergencies:emergency_detail", args=[world["open"].pk]),
    ):
        assert url not in client.get(page).content.decode()
    client.force_login(world["users"][RISK_MANAGER])
    assert client.post(url).status_code == 302
    action.refresh_from_db()
    assert action.status == IN_PROGRESS
