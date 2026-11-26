"""Reusable tenant-scoping dependency (ADR-010).

Resolves the tenant from the path, verifies active membership, and hands
services a ``TenantContext``. Hidden resources return 404 — never 403 —
so a guessed tenant id reveals nothing.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session as OrmSession

from app.auth.cookies import get_current_user
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.permissions import TENANT_ROUTE_PERMISSIONS
from app.db.models import Membership, Tenant, User
from app.db.session import get_session
from app.identity.access import resolve_access
from app.identity.roles import ROLE_PERMISSIONS, STAFF_PERMISSIONS, org_role_of

ROLE_LEVELS: dict[str, int] = {"viewer": 1, "editor": 2, "admin": 3}
ROLES = tuple(ROLE_LEVELS)


def role_at_least(role: str, minimum: str) -> bool:
    if role not in ROLE_LEVELS or minimum not in ROLE_LEVELS:
        raise ApiError(500, "INTERNAL_ERROR", "Unknown role referenced.")
    return ROLE_LEVELS[role] >= ROLE_LEVELS[minimum]


@dataclass
class TenantContext:
    """Validated caller context for one tenant-scoped request."""

    db: OrmSession
    user: User
    tenant: Tenant
    membership: Membership | None
    # Identity v2 (set only while IDENTITY_V2_ENABLED is on; see get_tenant_context).
    org_role: str | None = None
    permissions: frozenset[str] | None = None
    location_ids: frozenset[UUID] | None = None  # None = unrestricted
    via_agency: UUID | None = None
    via_agency_name: str | None = None

    @property
    def role(self) -> str:
        return self.membership.role if self.membership else "platform_staff"

    @property
    def effective_org_role(self) -> str | None:
        if self.org_role is not None:
            return self.org_role
        if self.membership is not None:
            return org_role_of(self.membership.role, self.membership.org_role)
        return None

    def has_permission(self, permission: str) -> bool:
        if self.permissions is not None:
            return permission in self.permissions
        if self.user.is_platform_staff:
            return permission in STAFF_PERMISSIONS
        role = self.effective_org_role
        return role is not None and permission in ROLE_PERMISSIONS[role]

    def require_permission(self, permission: str) -> None:
        if not self.has_permission(permission):
            raise ApiError(403, "FORBIDDEN", "You do not have permission for this action.")

    def require_role(self, minimum: str) -> None:
        """Raise 403 unless the caller holds at least `minimum` (docs/06 matrix)."""
        if not self.user.is_platform_staff and not role_at_least(self.role, minimum):
            raise ApiError(
                403,
                "FORBIDDEN",
                f"This action requires the {minimum} role or higher.",
            )

    def require_operator(self) -> None:
        if not self.user.is_platform_staff:
            raise ApiError(403, "FORBIDDEN", "Only platform staff can control the bot.")

    # Convenience for services that need ids as primitives.
    @property
    def tenant_id(self) -> UUID:
        return self.tenant.id


def get_tenant_context(
    tenant_id: UUID,
    request: Request,
    db: Annotated[OrmSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantContext:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    membership = (
        db.query(Membership)
        .filter(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
            Membership.status == "active",
        )
        .one_or_none()
    )
    if settings.identity_v2_enabled:
        return _identity_v2_context(request, db, user, tenant, membership)
    if membership is None and not user.is_platform_staff:
        # Do not reveal the tenant exists: a hidden resource looks like a 404.
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    context = TenantContext(db=db, user=user, tenant=tenant, membership=membership)
    minimum = request.scope["route"].openapi_extra["x-minimum-role"]
    route = request.scope["route"]
    inbox_action = request.method != "GET" and (
        "/inbox/" in route.path
        or route.path.startswith("/api/v1/tenants/{tenant_id}/conversations/")
    )
    if minimum == "editor" and membership is None and inbox_action:
        raise ApiError(403, "FORBIDDEN", "Inbox actions require an active tenant membership.")
    if minimum == "platform_staff_only":
        context.require_operator()
    else:
        context.require_role(minimum)
    return context


def _identity_v2_context(
    request: Request,
    db: OrmSession,
    user: User,
    tenant: Tenant,
    membership: Membership | None,
) -> TenantContext:
    """Permission-table authorization (design section 5); only reached with the flag on."""
    access = resolve_access(db, user=user, tenant=tenant, membership=membership)
    if access is None:
        raise ApiError(404, "NOT_FOUND", "Resource not found.")
    context = TenantContext(
        db=db,
        user=user,
        tenant=tenant,
        membership=membership,
        org_role=access.org_role,
        permissions=access.permissions,
        location_ids=access.location_ids,
        via_agency=access.via_agency,
        via_agency_name=access.via_agency_name,
    )
    route = request.scope["route"]
    permission = TENANT_ROUTE_PERMISSIONS.get((request.method, route.path))
    if permission is None or permission == "authenticated":
        # No reviewed declaration for this route and method: fail closed.
        raise ApiError(403, "FORBIDDEN", "You do not have permission for this action.")
    context.require_permission(permission)
    inbox_action = request.method != "GET" and (
        "/inbox/" in route.path
        or route.path.startswith("/api/v1/tenants/{tenant_id}/conversations/")
    )
    if permission == "inbox.reply" and membership is None and inbox_action:
        raise ApiError(403, "FORBIDDEN", "Inbox actions require an active tenant membership.")
    if access.location_ids is not None:
        # Fail closed: location-limited callers get no tenant routes until the
        # query sites apply identity.locations.location_filter (a later change).
        raise ApiError(
            403, "LOCATION_SCOPE_UNSUPPORTED", "Location-limited access is not available yet."
        )
    return context


TenantContextDep = Annotated[TenantContext, Depends(get_tenant_context)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
