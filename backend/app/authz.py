from collections.abc import Callable
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.roles import ROLE_ADMIN, ROLE_OPERATOR, ROLE_OWNER, ROLE_VIEWER, normalize_role

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_OWNER: {
        "manage_users",
        "manage_campaigns",
        "delete_campaigns",
        "manage_accounts",
        "disconnect_accounts",
        "delete_accounts",
        "view_audit_logs",
        "retry_messages",
        "manage_contacts",
        "manage_templates",
        "run_campaigns",
    },
    ROLE_ADMIN: {
        "manage_campaigns",
        "delete_campaigns",
        "manage_accounts",
        "disconnect_accounts",
        "view_audit_logs",
        "retry_messages",
        "manage_contacts",
        "manage_templates",
        "run_campaigns",
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


# --- Workspace-scoped authz (WhatsApp + Facebook routes only this phase) ----
#
# These dependencies resolve the caller's per-workspace membership from the
# X-Workspace-Id header instead of the global users.role column. Instagram
# and every other still-global route keep using require_permission /
# require_role above, unchanged.


@dataclass(frozen=True)
class WorkspaceContext:
    """Returned by the workspace-scoped dependencies so route handlers can
    filter queries by workspace_id without a second lookup."""

    user: User
    workspace_id: uuid.UUID


def _resolve_workspace_context(
    x_workspace_id: str | None,
    current_user: User,
    db: Session,
    allowed: set[str] | None = None,
    permission: str | None = None,
) -> WorkspaceContext:
    if not x_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Workspace-Id header is required",
        )
    try:
        workspace_id = uuid.UUID(x_workspace_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Workspace-Id must be a valid UUID",
        )

    membership = (
        db.query(UserWorkspaceMembership)
        .filter(
            UserWorkspaceMembership.user_id == current_user.id,
            UserWorkspaceMembership.workspace_id == workspace_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this workspace",
        )

    membership_role = normalize_role(membership.role)
    if allowed is not None and membership_role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )
    if permission is not None and permission not in ROLE_PERMISSIONS.get(membership_role, set()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )

    return WorkspaceContext(user=current_user, workspace_id=workspace_id)


def require_workspace_role(*roles: str) -> Callable:
    """Require the caller to hold a membership (with one of the given roles)
    in the workspace named by the X-Workspace-Id header. Called with no
    roles, any recognized membership role passes — the workspace-scoped
    equivalent of a plain get_current_user."""

    # No roles = no role restriction: any recognized membership role passes
    # (empty set would otherwise block everyone).
    allowed = {normalize_role(role) for role in roles} or None

    async def dependency(
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceContext:
        return _resolve_workspace_context(x_workspace_id, current_user, db, allowed=allowed)

    return dependency


def require_workspace_permission(permission: str) -> Callable:
    """Workspace-scoped mirror of require_permission: checks the permission
    against the membership's role (via the same ROLE_PERMISSIONS map) instead
    of the user's global role."""

    async def dependency(
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceContext:
        return _resolve_workspace_context(
            x_workspace_id, current_user, db, permission=permission
        )

    return dependency


def require_workspace_any_permission(*permissions: str) -> Callable:
    """Require at least one workspace-scoped permission."""

    async def dependency(
        x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceContext:
        ctx = _resolve_workspace_context(x_workspace_id, current_user, db)
        membership = (
            db.query(UserWorkspaceMembership)
            .filter(
                UserWorkspaceMembership.user_id == current_user.id,
                UserWorkspaceMembership.workspace_id == ctx.workspace_id,
            )
            .one()
        )
        role_permissions = ROLE_PERMISSIONS.get(normalize_role(membership.role), set())
        if not any(permission in role_permissions for permission in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return ctx

    return dependency
