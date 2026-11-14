from django.db.models import QuerySet

from apps.accounts.permissions import has_role
from apps.accounts.roles import ACTION_OWNER, CAPABILITIES

from .models import CLOSED, Emergency
from .workflow import TRANSITIONS


def _can(user, capability: str) -> bool:
    return has_role(user, *CAPABILITIES[capability])


def visible_emergencies(user) -> QuerySet[Emergency]:
    if _can(user, "edit_emergencies"):
        return Emergency.objects.all()
    if has_role(user, ACTION_OWNER):
        return Emergency.objects.filter(action_plan__actions__owner=user).distinct()
    return Emergency.objects.none()


def can_edit_emergency(user, emergency) -> bool:
    return not emergency.is_closed and _can(user, "edit_emergencies")


def allowed_statuses(user, emergency) -> list[str]:
    if not can_edit_emergency(user, emergency):
        return []
    can_close = _can(user, "close_emergencies")
    return [
        status
        for status in TRANSITIONS[emergency.status]
        if status != CLOSED or can_close
    ]


def can_set_status(user, emergency, status) -> bool:
    if status not in TRANSITIONS or not _can(user, "edit_emergencies"):
        return False
    return status != CLOSED or emergency.is_closed or _can(user, "close_emergencies")


def can_start_plan(user, emergency) -> bool:
    return can_edit_emergency(user, emergency) and _can(user, "start_plans")


def can_edit_plan(user, plan) -> bool:
    if plan.emergency.is_closed:
        return False
    if _can(user, "approve_plans"):
        return True
    return not plan.is_approved and _can(user, "start_plans")


def can_approve_plan(user, plan) -> bool:
    return not plan.emergency.is_closed and _can(user, "approve_plans")


def can_update_action(user, action) -> bool:
    if action.plan.emergency.is_closed or not _can(user, "update_actions"):
        return False
    if _can(user, "approve_plans") or action.owner_id == user.pk:
        return True
    return action.owner_id is None and _can(user, "start_plans")


def can_manage_resources(user) -> bool:
    return _can(user, "manage_resources")
