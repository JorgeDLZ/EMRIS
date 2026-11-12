from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.roles import ALL_ROLES
from apps.emergencies.models import CLOSED, Emergency
from apps.emergencies.workflow import WorkflowError, ensure_open

from .models import (
    APPROVED,
    DONE,
    DRAFT,
    IN_PROGRESS,
    PENDING,
    Action,
    ActionPlan,
    Resource,
    ResourceAssignment,
)

ACTION_TRANSITIONS = {PENDING: IN_PROGRESS, IN_PROGRESS: DONE}


class PlanError(WorkflowError):
    pass


def _lock_open(emergency: Emergency) -> Emergency:
    locked = Emergency.objects.select_for_update().get(pk=emergency.pk)
    ensure_open(locked)
    return locked


@transaction.atomic
def start_plan(emergency: Emergency, actor) -> ActionPlan:
    locked = _lock_open(emergency)
    plan, _ = ActionPlan.objects.get_or_create(emergency=locked, defaults={"proposed_by": actor})
    return plan


@transaction.atomic
def add_action(plan: ActionPlan, *, description, code="", owner=None, due_date=None) -> Action:
    _lock_open(plan.emergency)
    return Action.objects.create(
        plan=plan, description=description, code=code, owner=owner, due_date=due_date
    )


@transaction.atomic
def update_action(action: Action, *, description, code, owner, due_date) -> None:
    _lock_open(action.plan.emergency)
    action.description = description
    action.code = code
    action.owner = owner
    action.due_date = due_date
    action.save(update_fields=["description", "code", "owner", "due_date", "updated_at"])


@transaction.atomic
def advance_action(action: Action) -> None:
    _lock_open(action.plan.emergency)
    action.refresh_from_db(fields=["status"])
    if action.status not in ACTION_TRANSITIONS:
        raise PlanError("This action is already done.")
    action.status = ACTION_TRANSITIONS[action.status]
    action.save(update_fields=["status", "updated_at"])


@transaction.atomic
def approve_plan(plan: ActionPlan, actor) -> None:
    _lock_open(plan.emergency)
    plan.refresh_from_db(fields=["status"])
    if plan.status != DRAFT:
        raise PlanError("This plan is already approved.")
    if not plan.actions.exists():
        raise PlanError("Add at least one action before approving.")
    plan.status = APPROVED
    plan.approved_by = actor
    plan.approved_at = timezone.now()
    plan.save(update_fields=["status", "approved_by", "approved_at"])


def remaining_quantity(resource: Resource, exclude_plan: ActionPlan | None = None) -> int:
    assignments = ResourceAssignment.objects.filter(resource=resource).exclude(
        plan__emergency__status=CLOSED
    )
    if exclude_plan is not None:
        assignments = assignments.exclude(plan=exclude_plan)
    assigned = assignments.aggregate(total=Sum("quantity"))["total"] or 0
    return max(resource.quantity_available - assigned, 0)


@transaction.atomic
def assign_resource(plan: ActionPlan, resource: Resource, quantity: int) -> ResourceAssignment:
    _lock_open(plan.emergency)
    locked = Resource.objects.select_for_update().get(pk=resource.pk)
    remaining = remaining_quantity(locked, exclude_plan=plan)
    if quantity > remaining:
        raise PlanError(f"Only {remaining} {locked.name} remain.")
    assignment, _ = ResourceAssignment.objects.update_or_create(
        plan=plan, resource=locked, defaults={"quantity": quantity}
    )
    return assignment


@transaction.atomic
def remove_assignment(assignment: ResourceAssignment) -> None:
    _lock_open(assignment.plan.emergency)
    assignment.delete()


def assignable_owners():
    return (
        get_user_model()
        .objects.filter(is_active=True, groups__name__in=ALL_ROLES)
        .distinct()
        .order_by("username")
    )
