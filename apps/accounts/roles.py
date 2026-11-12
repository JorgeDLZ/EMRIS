ADMINISTRATOR = "administrator"
RISK_MANAGER = "risk_manager"
OPERATOR = "operator"
ACTION_OWNER = "action_owner"

ALL_ROLES: tuple[str, ...] = (ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER)
MANAGE_ROLES: tuple[str, ...] = (ADMINISTRATOR, RISK_MANAGER)
EDIT_ROLES: tuple[str, ...] = (ADMINISTRATOR, RISK_MANAGER, OPERATOR)

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
