from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from apps.accounts.roles import ALL_ROLES, get_role


def has_role(user, *roles: str) -> bool:
    if user.is_superuser:
        return True
    return get_role(user) in roles


def check_access(request, roles):
    """Return a redirect when access is refused, raise 403 for a disallowed role, else None."""
    user = request.user
    if not user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if user.is_superuser:
        return None
    role = get_role(user)
    if role is None:
        return redirect("accounts:pending")
    if role not in roles:
        raise PermissionDenied
    return None


class RoleRequiredMixin:
    allowed_roles: tuple[str, ...] = ALL_ROLES

    def dispatch(self, request, *args, **kwargs):
        refusal = check_access(request, self.allowed_roles)
        if refusal is not None:
            return refusal
        return super().dispatch(request, *args, **kwargs)


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            refusal = check_access(request, roles)
            if refusal is not None:
                return refusal
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
