ADMINISTRATOR = "administrator"
RISK_MANAGER = "risk_manager"
OPERATOR = "operator"
ACTION_OWNER = "action_owner"

ALL_ROLES: tuple[str, ...] = (ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER)
MANAGE_ROLES: tuple[str, ...] = (ADMINISTRATOR, RISK_MANAGER)
EDIT_ROLES: tuple[str, ...] = (ADMINISTRATOR, RISK_MANAGER, OPERATOR)
ADMIN_ROLES: tuple[str, ...] = (ADMINISTRATOR,)

CAPABILITIES: dict[str, tuple[str, ...]] = {
    "view_emergencies": ALL_ROLES,
    "edit_emergencies": EDIT_ROLES,
    "close_emergencies": MANAGE_ROLES,
    "start_plans": EDIT_ROLES,
    "approve_plans": MANAGE_ROLES,
    "update_actions": ALL_ROLES,
    "manage_resources": MANAGE_ROLES,
    "manage_catalogs": MANAGE_ROLES,
    "register_municipalities": EDIT_ROLES,
    "validate_municipalities": MANAGE_ROLES,
    "view_dashboard": ALL_ROLES,
    "view_risk_ranking": EDIT_ROLES,
    "browse_history": EDIT_ROLES,
    "manage_models": ADMIN_ROLES,
    "manage_users": ADMIN_ROLES,
}

ROLE_LABELS: dict[str, str] = {
    ADMINISTRATOR: "Administrator",
    RISK_MANAGER: "Risk manager",
    OPERATOR: "Operator",
    ACTION_OWNER: "Action owner",
}


def get_role(user) -> str | None:
    if not user.is_authenticated:
        return None
    group = user.groups.filter(name__in=ALL_ROLES).first()
    return group.name if group else None
