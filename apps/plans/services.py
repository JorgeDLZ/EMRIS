from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.roles import ALL_ROLES
from apps.emergencies.models import CLOSED, Emergency
from apps.emergencies.workflow import WorkflowError, lock_open

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


@transaction.atomic
def start_plan(emergency: Emergency, actor) -> ActionPlan:
    locked = lock_open(emergency)
    plan, _ = ActionPlan.objects.get_or_create(emergency=locked, defaults={"proposed_by": actor})
    return plan


@transaction.atomic
def add_action(plan: ActionPlan, *, description, code="", owner=None, due_date=None) -> Action:
    lock_open(plan.emergency)
    return Action.objects.create(
        plan=plan, description=description, code=code, owner=owner, due_date=due_date
    )


@transaction.atomic
def update_action(action: Action, *, description, code, owner, due_date) -> None:
    lock_open(action.plan.emergency)
    action.description = description
    action.code = code
    action.owner = owner
    action.due_date = due_date
    action.save(update_fields=["description", "code", "owner", "due_date", "updated_at"])


@transaction.atomic
def advance_action(action: Action, expected_status: str | None = None) -> None:
    lock_open(action.plan.emergency)
    locked = Action.objects.select_for_update().get(pk=action.pk)
    if expected_status is not None and locked.status != expected_status:
        raise PlanError("This action was already updated.")
    if locked.status not in ACTION_TRANSITIONS:
        raise PlanError("This action is already done.")
    locked.status = ACTION_TRANSITIONS[locked.status]
    locked.save(update_fields=["status", "updated_at"])
    action.status = locked.status
    action.updated_at = locked.updated_at


@transaction.atomic
def approve_plan(plan: ActionPlan, actor) -> None:
    lock_open(plan.emergency)
    plan.refresh_from_db(fields=["status"])
    if plan.status != DRAFT:
        raise PlanError("This plan is already approved.")
    if not plan.actions.exists():
        raise PlanError("Add at least one action before approving.")
    plan.status = APPROVED
    plan.approved_by = actor
    plan.approved_at = timezone.now()
    plan.save(update_fields=["status", "approved_by", "approved_at"])


def assigned_quantity(resource: Resource, exclude_plan: ActionPlan | None = None) -> int:
    assignments = ResourceAssignment.objects.filter(resource=resource).exclude(
        plan__emergency__status=CLOSED
    )
    if exclude_plan is not None:
        assignments = assignments.exclude(plan=exclude_plan)
    return assignments.aggregate(total=Sum("quantity"))["total"] or 0


def remaining_quantity(resource: Resource, exclude_plan: ActionPlan | None = None) -> int:
    return max(resource.quantity_available - assigned_quantity(resource, exclude_plan), 0)


@transaction.atomic
def assign_resource(plan: ActionPlan, resource: Resource, quantity: int) -> ResourceAssignment:
    lock_open(plan.emergency)
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
    lock_open(assignment.plan.emergency)
    assignment.delete()


def assignable_owners():
    return (
        get_user_model()
        .objects.filter(is_active=True, groups__name__in=ALL_ROLES)
        .distinct()
        .order_by("username")
    )
