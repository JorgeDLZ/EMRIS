from django.contrib.auth.models import Group
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.roles import ADMINISTRATOR, ALL_ROLES, clear_role_cache, get_role


class RoleChangeError(Exception):
    """Raised when a role change is refused; the message is meant for the user."""


def set_role(actor: User, target: User, role: str | None) -> None:
    if role is not None and role not in ALL_ROLES:
        raise RoleChangeError(f"Unknown role: {role}.")
    if actor.pk == target.pk:
        raise RoleChangeError("You cannot change your own role.")
    with transaction.atomic():
        if get_role(target) == ADMINISTRATOR and role != ADMINISTRATOR:
            administrators = User.objects.filter(groups__name=ADMINISTRATOR)
            if administrators.count() <= 1:
                raise RoleChangeError("The last administrator cannot be removed.")
        target.groups.remove(*target.groups.filter(name__in=ALL_ROLES))
        if role is not None:
            target.groups.add(Group.objects.get(name=role))
    clear_role_cache(target)
