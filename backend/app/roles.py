ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

VALID_ROLES = {ROLE_OWNER, ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER}


def normalize_role(role: str | None) -> str:
    value = (role or ROLE_VIEWER).strip().lower()
    if value == "user":
        return ROLE_VIEWER
    return value if value in VALID_ROLES else ROLE_VIEWER
