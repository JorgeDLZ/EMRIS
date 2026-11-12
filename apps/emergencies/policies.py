from django.db.models import QuerySet

from apps.accounts.permissions import has_role
from apps.accounts.roles import ACTION_OWNER, EDIT_ROLES, MANAGE_ROLES, OPERATOR

from .models import CLOSED, Emergency
from .workflow import TRANSITIONS


def visible_emergencies(user) -> QuerySet[Emergency]:
    if has_role(user, *EDIT_ROLES):
        return Emergency.objects.all()
    if has_role(user, ACTION_OWNER):
        return Emergency.objects.filter(action_plan__actions__owner=user).distinct()
    return Emergency.objects.none()


def can_edit_emergency(user, emergency) -> bool:
    return not emergency.is_closed and has_role(user, *EDIT_ROLES)


def allowed_statuses(user, emergency) -> list[str]:
    if not can_edit_emergency(user, emergency):
        return []
    can_close = has_role(user, *MANAGE_ROLES)
    return [
        status
        for status in TRANSITIONS[emergency.status]
        if status != CLOSED or can_close
    ]


def can_set_status(user, emergency, status) -> bool:
    if status not in TRANSITIONS or not has_role(user, *EDIT_ROLES):
        return False
    return status != CLOSED or emergency.is_closed or has_role(user, *MANAGE_ROLES)


def can_start_plan(user, emergency) -> bool:
    return can_edit_emergency(user, emergency)


def can_edit_plan(user, plan) -> bool:
    if plan.emergency.is_closed:
        return False
    if has_role(user, *MANAGE_ROLES):
        return True
    return not plan.is_approved and has_role(user, OPERATOR)


def can_approve_plan(user, plan) -> bool:
    return not plan.emergency.is_closed and has_role(user, *MANAGE_ROLES)


def can_update_action(user, action) -> bool:
    if action.plan.emergency.is_closed:
        return False
    if has_role(user, *EDIT_ROLES):
        return True
    return has_role(user, ACTION_OWNER) and action.owner_id == user.pk


def can_manage_resources(user) -> bool:
    return has_role(user, *MANAGE_ROLES)
