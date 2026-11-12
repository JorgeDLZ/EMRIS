import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import OPERATOR
from apps.emergencies.models import CLOSED, Emergency, EmergencyType
from apps.emergencies.workflow import WorkflowError, create_emergency
from apps.places.models import Department, Municipality
from apps.plans.models import (
    ACTION_CODE_CHOICES,
    APPROVED,
    DONE,
    DRAFT,
    IN_PROGRESS,
    PENDING,
    Action,
    Resource,
    ResourceAssignment,
)
from apps.plans.services import (
    PlanError,
    add_action,
    advance_action,
    approve_plan,
    assign_resource,
    assignable_owners,
    remaining_quantity,
    remove_assignment,
    start_plan,
    update_action,
)
from ml.actions import ACTION_VOCABULARY


@pytest.fixture
def actor(db):
    return User.objects.create_user("operator", password="pass-12345")


@pytest.fixture
def make_emergency(actor):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood = EmergencyType.objects.create(name="Flood")

    def make():
        return create_emergency(
            actor, emergency_type=flood, municipality=municipality, occurred_at=timezone.now()
        )

    return make


@pytest.fixture
def emergency(make_emergency):
    return make_emergency()


@pytest.fixture
def food_kits(db):
    return Resource.objects.create(name="Food kits", kind="kit", quantity_available=10)


def close(emergency):
    Emergency.objects.filter(pk=emergency.pk).update(status=CLOSED)


def test_start_plan_is_idempotent(emergency, actor):
    first = start_plan(emergency, actor)
    second = start_plan(emergency, actor)
    assert first.pk == second.pk
    assert second.status == DRAFT
    assert second.proposed_by == actor


def test_approve_needs_an_action(emergency, actor):
    plan = start_plan(emergency, actor)
    with pytest.raises(PlanError, match="Add at least one action before approving."):
        approve_plan(plan, actor)
    add_action(plan, description="Evacuate the riverside")
    approve_plan(plan, actor)
    plan.refresh_from_db()
    assert plan.status == APPROVED
    assert plan.approved_by == actor
    assert plan.approved_at is not None
    with pytest.raises(PlanError, match="This plan is already approved."):
        approve_plan(plan, actor)


def test_action_moves_only_forward(emergency, actor):
    plan = start_plan(emergency, actor)
    action = add_action(plan, description="Open a shelter")
    assert action.status == PENDING
    advance_action(action)
    assert action.status == IN_PROGRESS
    advance_action(action)
    assert action.status == DONE
    with pytest.raises(PlanError, match="This action is already done."):
        advance_action(action)


def test_update_action_changes_fields(emergency, actor):
    plan = start_plan(emergency, actor)
    action = add_action(plan, description="Open a shelter")
    update_action(
        action,
        description="Open two shelters",
        code="deploy_civil_defense",
        owner=actor,
        due_date=None,
    )
    action.refresh_from_db()
    assert action.description == "Open two shelters"
    assert action.code == "deploy_civil_defense"
    assert action.owner == actor


def test_remaining_counts_other_open_emergencies(make_emergency, actor, food_kits):
    plan_a = start_plan(make_emergency(), actor)
    plan_b = start_plan(make_emergency(), actor)
    assign_resource(plan_a, food_kits, 6)
    assert remaining_quantity(food_kits) == 4
    assert remaining_quantity(food_kits, exclude_plan=plan_a) == 10
    with pytest.raises(PlanError, match="Only 4 Food kits remain."):
        assign_resource(plan_b, food_kits, 5)
    assign_resource(plan_b, food_kits, 4)
    assert remaining_quantity(food_kits) == 0


def test_closing_frees_resources(make_emergency, actor, food_kits):
    emergency_a = make_emergency()
    plan_a = start_plan(emergency_a, actor)
    assign_resource(plan_a, food_kits, 6)
    close(emergency_a)
    assert remaining_quantity(food_kits) == 10


def test_reassigning_replaces_quantity(emergency, actor, food_kits):
    plan = start_plan(emergency, actor)
    assign_resource(plan, food_kits, 3)
    assign_resource(plan, food_kits, 5)
    assignment = ResourceAssignment.objects.get(plan=plan, resource=food_kits)
    assert assignment.quantity == 5
    assert remaining_quantity(food_kits) == 5
    assert remaining_quantity(food_kits, exclude_plan=plan) == 10


def test_remove_assignment_frees_stock(emergency, actor, food_kits):
    plan = start_plan(emergency, actor)
    assignment = assign_resource(plan, food_kits, 3)
    remove_assignment(assignment)
    assert remaining_quantity(food_kits) == 10


def test_closed_emergency_locks_plan(emergency, actor, food_kits):
    plan = start_plan(emergency, actor)
    action = add_action(plan, description="Open a shelter")
    assignment = assign_resource(plan, food_kits, 3)
    close(emergency)
    calls = [
        lambda: start_plan(emergency, actor),
        lambda: add_action(plan, description="Another"),
        lambda: update_action(action, description="x", code="", owner=None, due_date=None),
        lambda: advance_action(action),
        lambda: approve_plan(plan, actor),
        lambda: assign_resource(plan, food_kits, 1),
        lambda: remove_assignment(assignment),
    ]
    for call in calls:
        with pytest.raises(WorkflowError, match="This emergency is closed."):
            call()
    assert Action.objects.filter(plan=plan).count() == 1


def test_assignable_owners_need_a_role(db):
    group = Group.objects.get(name=OPERATOR)
    for username in ("beta", "alpha"):
        User.objects.create_user(username, password="pass-12345").groups.add(group)
    User.objects.create_user("norole", password="pass-12345")
    inactive = User.objects.create_user("inactive", password="pass-12345", is_active=False)
    inactive.groups.add(group)
    assert [user.username for user in assignable_owners()] == ["alpha", "beta"]


def test_action_code_choices_follow_vocabulary():
    field = Action._meta.get_field("code")
    assert len(ACTION_CODE_CHOICES) == 16
    assert field.blank
    assert [code for code, _ in field.choices] == list(ACTION_VOCABULARY)
    assert dict(field.choices) == {code: rule.label for code, rule in ACTION_VOCABULARY.items()}


def test_remaining_never_negative_when_stock_is_lowered(make_emergency, actor, food_kits):
    plan_a = start_plan(make_emergency(), actor)
    plan_b = start_plan(make_emergency(), actor)
    assign_resource(plan_a, food_kits, 6)
    food_kits.quantity_available = 4
    food_kits.save()
    assert remaining_quantity(food_kits) == 0
    with pytest.raises(PlanError, match="Only 0 Food kits remain."):
        assign_resource(plan_b, food_kits, 1)
