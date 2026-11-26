"""Resolve what a caller may do inside one organization (identity flag on).

Order of authority: platform staff, then a direct membership, then an agency
grant. A direct membership wins over a grant, which can only make the caller
narrower, never broader.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session as OrmSession

from app.db.models import Membership, Tenant, User
from app.identity.agency import active_grant_for
from app.identity.locations import member_location_ids
from app.identity.roles import (
    ROLE_PERMISSIONS,
    STAFF_PERMISSIONS,
    agency_permissions,
    org_role_of,
)


@dataclass(frozen=True)
class Access:
    org_role: str
    permissions: frozenset[str]
    location_ids: frozenset[UUID] | None  # None = unrestricted
    via_agency: UUID | None = None
    via_agency_name: str | None = None


def resolve_access(
    db: OrmSession,
    *,
    user: User,
    tenant: Tenant,
    membership: Membership | None,
    now: datetime | None = None,
) -> Access | None:
    """None means the caller has no access (callers answer 404, never 403)."""
    if user.is_platform_staff:
        role = (
            org_role_of(membership.role, membership.org_role)
            if membership is not None
            else "platform_staff"
        )
        return Access(org_role=role, permissions=STAFF_PERMISSIONS, location_ids=None)
    if membership is not None:
        role = org_role_of(membership.role, membership.org_role)
        scope: frozenset[UUID] | None = None
        if membership.location_scope == "limited":
            scope = member_location_ids(db, tenant.id, user.id)
        return Access(org_role=role, permissions=ROLE_PERMISSIONS[role], location_ids=scope)
    grant = active_grant_for(db, user_id=user.id, tenant_id=tenant.id, now=now)
    if grant is None:
        return None
    return Access(
        org_role=grant.role_cap,
        permissions=agency_permissions(grant.role_cap),
        location_ids=grant.location_ids,
        via_agency=grant.agency_id,
        via_agency_name=grant.agency_name,
    )
