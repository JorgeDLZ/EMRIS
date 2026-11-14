from dataclasses import dataclass
from fnmatch import fnmatchcase

from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from apps.accounts.permissions import has_role
from apps.accounts.roles import ALL_ROLES, CAPABILITIES, get_role


@dataclass(frozen=True)
class NavItem:
    label: str
    url: str
    active: bool


@dataclass(frozen=True)
class NavGroup:
    label: str
    items: list[NavItem]


@dataclass(frozen=True)
class MenuEntry:
    label: str
    url_name: str
    roles: tuple[str, ...]
    active_names: tuple[str, ...]
    excluded_names: tuple[str, ...] = ()


MENU: tuple[tuple[str, tuple[MenuEntry, ...]], ...] = (
    (
        "Overview",
        (
            MenuEntry("Home", "home", ALL_ROLES, ("home",)),
            MenuEntry(
                "Dashboard", "dashboard:index", CAPABILITIES["view_dashboard"], ("dashboard:index",)
            ),
        ),
    ),
    (
        "Operations",
        (
            MenuEntry(
                "Emergencies",
                "emergencies:emergency_list",
                CAPABILITIES["view_emergencies"],
                (
                    "emergencies:*",
                    "plans:plan_*",
                    "plans:action_*",
                    "plans:assignment_*",
                    "plans:suggested_action_add",
                ),
                ("emergencies:type_*",),
            ),
            MenuEntry(
                "Resources",
                "plans:resource_list",
                CAPABILITIES["manage_resources"],
                ("plans:resource_*",),
            ),
        ),
    ),
    (
        "Intelligence",
        (
            MenuEntry(
                "Risk ranking",
                "dashboard:ranking",
                CAPABILITIES["view_risk_ranking"],
                ("dashboard:ranking",),
            ),
            MenuEntry(
                "Models", "intelligence:model_list", CAPABILITIES["manage_models"], ("intelligence:*",)
            ),
        ),
    ),
    (
        "Reference data",
        (
            MenuEntry(
                "UNGRD history", "history:record_list", CAPABILITIES["browse_history"], ("history:*",)
            ),
            MenuEntry(
                "Municipalities",
                "places:municipality_list",
                CAPABILITIES["register_municipalities"],
                ("places:municipality_list", "places:municipality_create"),
            ),
            MenuEntry(
                "Pending municipalities",
                "places:municipality_pending",
                CAPABILITIES["validate_municipalities"],
                ("places:municipality_pending",),
            ),
            MenuEntry(
                "Emergency types",
                "emergencies:type_list",
                CAPABILITIES["manage_catalogs"],
                ("emergencies:type_*",),
            ),
        ),
    ),
    (
        "Administration",
        (MenuEntry("Users", "accounts:user_list", CAPABILITIES["manage_users"], ("accounts:user_*",)),),
    ),
)


def _is_active(entry: MenuEntry, view_name: str) -> bool:
    if not view_name:
        return False
    if any(fnmatchcase(view_name, pattern) for pattern in entry.excluded_names):
        return False
    return any(fnmatchcase(view_name, pattern) for pattern in entry.active_names)


def _build_groups(request) -> list[NavGroup]:
    user = request.user
    if not user.is_authenticated or not (user.is_superuser or get_role(user)):
        return []
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else ""
    groups = []
    for label, entries in MENU:
        items = [
            NavItem(entry.label, reverse(entry.url_name), _is_active(entry, view_name))
            for entry in entries
            if has_role(user, *entry.roles)
        ]
        if items:
            groups.append(NavGroup(label, items))
    return groups


def navigation(request) -> dict:
    return {"nav_groups": SimpleLazyObject(lambda: _build_groups(request))}
