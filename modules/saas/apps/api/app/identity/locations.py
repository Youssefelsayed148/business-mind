"""Location scope (design 4.2). Fail closed.

``location_ids is None`` means unrestricted (scope ``all``). A limited caller
sees only rows whose ``location_id`` is in the list; organization-wide rows
(``NULL``) are visible to unrestricted callers only.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, SQLColumnExpression, false, select, true
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Location, MembershipLocation


def member_location_ids(db: OrmSession, tenant_id: UUID, user_id: UUID) -> frozenset[UUID]:
    rows = db.execute(
        select(MembershipLocation.location_id).where(
            MembershipLocation.tenant_id == tenant_id, MembershipLocation.user_id == user_id
        )
    ).scalars()
    return frozenset(rows)


def location_allowed(location_ids: frozenset[UUID] | None, row_location_id: UUID | None) -> bool:
    if location_ids is None:
        return True
    return row_location_id is not None and row_location_id in location_ids


def location_filter(
    column: SQLColumnExpression[Any], location_ids: frozenset[UUID] | None
) -> ColumnElement[bool]:
    """A WHERE clause restricting ``column`` to the caller's locations."""
    if location_ids is None:
        return true()
    if not location_ids:
        return false()
    return column.in_(location_ids)


def narrower(
    first: frozenset[UUID] | None, second: frozenset[UUID] | None
) -> frozenset[UUID] | None:
    """Intersection of two scopes where None means unrestricted."""
    if first is None:
        return second
    if second is None:
        return first
    return first & second


def validate_locations_in_tenant(
    db: OrmSession, tenant_id: UUID, location_ids: Iterable[UUID]
) -> frozenset[UUID]:
    """Every id must be an active location of this tenant, else ValueError (callers map to 404)."""
    wanted = frozenset(location_ids)
    if not wanted:
        return wanted
    found = frozenset(
        db.execute(
            select(Location.id).where(
                Location.tenant_id == tenant_id,
                Location.id.in_(wanted),
                Location.status == "active",
            )
        ).scalars()
    )
    if found != wanted:
        raise ValueError("unknown location for this organization")
    return found
