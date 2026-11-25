"""Agency grants (design 4.3, option A2).

An agency is its own entity and never a tenant. Nothing links an agency to a
client except an ``agency_grants`` row, and a person acts inside a client only
when assigned to that grant. Only the client's real Owner creates or revokes a
grant (platform staff cannot, by default).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.core.audit import record_audit
from app.core.errors import ApiError
from app.db.base import utcnow
from app.db.models import (
    Agency,
    AgencyGrant,
    AgencyGrantAssignee,
    AgencyGrantLocation,
    AgencyMembership,
    User,
)
from app.identity.locations import validate_locations_in_tenant
from app.identity.roles import GRANT_ROLE_CAPS

if TYPE_CHECKING:
    from app.core.tenancy import TenantContext

# Narrowest first: if one person reaches a client through two agencies, the
# lowest cap wins (never the broadest).
_CAP_RANK = {"viewer": 0, "agent": 1, "manager": 2, "admin": 3}


@dataclass(frozen=True)
class ActiveGrant:
    grant_id: UUID
    agency_id: UUID
    agency_name: str
    role_cap: str
    location_ids: frozenset[UUID] | None  # None = all locations


def _not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Resource not found.")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def active_grant_for(
    db: OrmSession, *, user_id: UUID, tenant_id: UUID, now: datetime | None = None
) -> ActiveGrant | None:
    """The grant under which this person may act in this tenant right now, if any.

    All of these must hold: the grant is active and unexpired, the agency is
    active, the person belongs to the agency, and the person is assigned to
    the grant. Expiry is checked here, so it applies at every request.
    """
    moment = now or utcnow()
    rows = db.execute(
        select(AgencyGrant, Agency)
        .join(Agency, Agency.id == AgencyGrant.agency_id)
        .join(
            AgencyGrantAssignee,
            (AgencyGrantAssignee.grant_id == AgencyGrant.id)
            & (AgencyGrantAssignee.user_id == user_id),
        )
        .join(
            AgencyMembership,
            (AgencyMembership.agency_id == AgencyGrant.agency_id)
            & (AgencyMembership.user_id == user_id),
        )
        .where(
            AgencyGrant.tenant_id == tenant_id,
            AgencyGrant.status == "active",
            Agency.status == "active",
        )
    ).all()
    candidates = [
        (grant, agency)
        for grant, agency in rows
        if grant.expires_at is None or _aware(grant.expires_at) > _aware(moment)
    ]
    if not candidates:
        return None
    grant, agency = min(candidates, key=lambda pair: _CAP_RANK[pair[0].role_cap])
    location_ids = frozenset(
        db.execute(
            select(AgencyGrantLocation.location_id).where(AgencyGrantLocation.grant_id == grant.id)
        ).scalars()
    )
    return ActiveGrant(
        grant_id=grant.id,
        agency_id=agency.id,
        agency_name=agency.name,
        role_cap=grant.role_cap,
        location_ids=location_ids or None,
    )


def create_agency(db: OrmSession, *, actor: User, name: str) -> Agency:
    """Platform staff create agencies (design 4.3)."""
    if not actor.is_platform_staff:
        raise ApiError(403, "FORBIDDEN", "Only platform staff can create agencies.")
    agency = Agency(name=name.strip())
    db.add(agency)
    db.flush()
    record_audit(
        db,
        action="agency.created",
        tenant_id=None,
        actor_user_id=actor.id,
        target_type="agency",
        target_id=str(agency.id),
    )
    return agency


def add_agency_member(
    db: OrmSession, *, actor: User, agency_id: UUID, user_id: UUID, role: str = "agency_member"
) -> AgencyMembership:
    """Staff, or an admin of that same agency, may add its people."""
    agency = db.get(Agency, agency_id)
    if agency is None:
        raise _not_found()
    if not actor.is_platform_staff and not _is_agency_admin(db, agency_id, actor.id):
        raise _not_found()  # do not reveal the agency to outsiders
    if role not in ("agency_admin", "agency_member"):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid agency role.")
    if db.get(User, user_id) is None:
        raise _not_found()
    existing = db.get(AgencyMembership, (agency_id, user_id))
    if existing is not None:
        existing.role = role
        return existing
    membership = AgencyMembership(agency_id=agency_id, user_id=user_id, role=role)
    db.add(membership)
    db.flush()
    return membership


def _is_agency_admin(db: OrmSession, agency_id: UUID, user_id: UUID) -> bool:
    membership = db.get(AgencyMembership, (agency_id, user_id))
    return membership is not None and membership.role == "agency_admin"


def create_grant(
    ctx: "TenantContext",
    *,
    agency_id: UUID,
    role_cap: str,
    location_ids: Iterable[UUID] = (),
    expires_at: datetime | None = None,
) -> AgencyGrant:
    """Only the client's real Owner (never staff, never an agency person)."""
    _require_client_owner(ctx)
    if role_cap not in GRANT_ROLE_CAPS:
        raise ApiError(422, "VALIDATION_ERROR", "A grant role cap must be below Owner.")
    if expires_at is not None and _aware(expires_at) <= _aware(utcnow()):
        raise ApiError(422, "VALIDATION_ERROR", "A grant cannot expire in the past.")
    agency = ctx.db.get(Agency, agency_id)
    if agency is None or agency.status != "active":
        raise _not_found()
    try:
        scoped = validate_locations_in_tenant(ctx.db, ctx.tenant_id, location_ids)
    except ValueError:
        raise _not_found() from None
    grant = AgencyGrant(
        agency_id=agency_id,
        tenant_id=ctx.tenant_id,
        role_cap=role_cap,
        expires_at=expires_at,
        granted_by_user_id=ctx.user.id,
    )
    ctx.db.add(grant)
    try:
        ctx.db.flush()
    except IntegrityError:
        ctx.db.rollback()
        raise ApiError(409, "CONFLICT", "This agency already has an active grant.") from None
    for location_id in scoped:
        ctx.db.add(
            AgencyGrantLocation(grant_id=grant.id, tenant_id=ctx.tenant_id, location_id=location_id)
        )
    record_audit(
        ctx.db,
        action="agency.grant_created",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user.id,
        target_type="agency_grant",
        target_id=str(grant.id),
        metadata={
            "agency_id": str(agency_id),
            "role_cap": role_cap,
            "locations": sorted(str(i) for i in scoped),
        },
    )
    return grant


def assign_grantee(db: OrmSession, *, actor: User, grant_id: UUID, user_id: UUID) -> None:
    """An admin of the grant's agency chooses which of its own people use the grant."""
    grant = db.get(AgencyGrant, grant_id)
    if grant is None or grant.status != "active":
        raise _not_found()
    if not _is_agency_admin(db, grant.agency_id, actor.id):
        raise _not_found()
    if db.get(AgencyMembership, (grant.agency_id, user_id)) is None:
        raise ApiError(422, "VALIDATION_ERROR", "The person must belong to the agency.")
    if db.get(AgencyGrantAssignee, (grant_id, user_id)) is None:
        db.add(AgencyGrantAssignee(grant_id=grant_id, user_id=user_id))
        db.flush()
        record_audit(
            db,
            action="agency.grant_assigned",
            tenant_id=grant.tenant_id,
            actor_user_id=actor.id,
            target_type="agency_grant",
            target_id=str(grant_id),
            metadata={"agency_id": str(grant.agency_id), "assignee": str(user_id)},
        )


def revoke_grant(ctx: "TenantContext", *, grant_id: UUID) -> None:
    """Immediate in the SaaS: the next request of every assignee loses access."""
    _require_client_owner(ctx)
    grant = ctx.db.get(AgencyGrant, grant_id)
    if grant is None or grant.tenant_id != ctx.tenant_id:
        raise _not_found()
    if grant.status == "revoked":
        return
    grant.status = "revoked"
    grant.revoked_at = utcnow()
    grant.revoked_by_user_id = ctx.user.id
    record_audit(
        ctx.db,
        action="agency.grant_revoked",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user.id,
        target_type="agency_grant",
        target_id=str(grant_id),
        metadata={"agency_id": str(grant.agency_id)},
    )


def list_grants(ctx: "TenantContext") -> list[dict[str, object]]:
    """The 'Access granted to others' view: Owner and Admin may read it."""
    ctx.require_permission("agency.view")
    if ctx.via_agency is not None:
        raise ApiError(403, "FORBIDDEN", "Not available to agency access.")
    grants = (
        ctx.db.execute(
            select(AgencyGrant, Agency)
            .join(Agency, Agency.id == AgencyGrant.agency_id)
            .where(AgencyGrant.tenant_id == ctx.tenant_id)
            .order_by(AgencyGrant.granted_at)
        )
        .tuples()
        .all()
    )
    result: list[dict[str, object]] = []
    for grant, agency in grants:
        assignees = sorted(
            str(u)
            for u in ctx.db.execute(
                select(AgencyGrantAssignee.user_id).where(AgencyGrantAssignee.grant_id == grant.id)
            ).scalars()
        )
        locations = sorted(
            str(i)
            for i in ctx.db.execute(
                select(AgencyGrantLocation.location_id).where(
                    AgencyGrantLocation.grant_id == grant.id
                )
            ).scalars()
        )
        result.append(
            {
                "id": str(grant.id),
                "agency_id": str(agency.id),
                "agency_name": agency.name,
                "role_cap": grant.role_cap,
                "status": grant.status,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                "assignees": assignees,
                "location_ids": locations,
            }
        )
    return result


def _require_client_owner(ctx: "TenantContext") -> None:
    """A real Owner membership of this organization; staff and agency people are refused."""
    ctx.require_permission("agency.manage")
    if ctx.via_agency is not None or ctx.membership is None or ctx.effective_org_role != "owner":
        raise ApiError(403, "FORBIDDEN", "Only an Owner of the organization can manage grants.")
