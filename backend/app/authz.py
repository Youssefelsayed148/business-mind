from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.routes_auth import get_current_user
from app.models.user import User
from app.roles import ROLE_ADMIN, ROLE_OPERATOR, ROLE_OWNER, ROLE_VIEWER, normalize_role

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_OWNER: {
        "manage_users",
        "manage_campaigns",
        "delete_campaigns",
        "manage_accounts",
        "disconnect_accounts",
        "view_audit_logs",
        "retry_messages",
    },
    ROLE_ADMIN: {
        "manage_campaigns",
        "delete_campaigns",
        "manage_accounts",
        "disconnect_accounts",
        "view_audit_logs",
        "retry_messages",
    },
    ROLE_OPERATOR: {
        "manage_campaigns",
        "view_audit_logs",
    },
    ROLE_VIEWER: {
        "view_audit_logs",
    },
}


def has_permission(user: User, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(normalize_role(user.role), set())


def require_permission(permission: str) -> Callable:
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency


def require_role(*roles: str) -> Callable:
    allowed = {normalize_role(role) for role in roles}

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if normalize_role(current_user.role) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return dependency
