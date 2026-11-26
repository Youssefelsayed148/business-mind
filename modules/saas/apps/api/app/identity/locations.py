"""Location scope (design 4.2). Fail closed.

``location_ids is None`` means unrestricted (scope ``all``). A limited caller
sees only rows whose ``location_id`` is in the list; organization-wide rows
(``NULL``) are visible to unrestricted callers only.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, SQLColumnExpression, delete, exists, false, select, true
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    ChannelConnection,
    Conversation,
    Invitation,
    InvitationLocation,
    Location,
    Membership,
    MembershipLocation,
)


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


def conversation_location_filter(
    location_ids: frozenset[UUID] | None, conversation: Any = Conversation
) -> ColumnElement[bool]:
    """Conversations take the location of their channel connection (design 4.2).

    A conversation without a connection (website, playground) is organization-wide, so
    it is visible to unrestricted callers only.
    """
    if location_ids is None:
        return true()
    if not location_ids:
        return false()
    return exists().where(
        ChannelConnection.tenant_id == conversation.tenant_id,
        ChannelConnection.id == conversation.connection_id,
        ChannelConnection.location_id.in_(location_ids),
    )


def conversation_location_sql(
    alias: str, location_ids: frozenset[UUID] | None, key: str = "loc_ids"
) -> tuple[str, dict[str, Any]]:
    """The same rule as a raw-SQL fragment (starts with AND) plus its bind parameters."""
    if location_ids is None:
        return "", {}
    if not location_ids:
        return " AND false", {}
    sql = (
        " AND EXISTS (SELECT 1 FROM channel_connections lcx"
        f" WHERE lcx.tenant_id = {alias}.tenant_id"
        f" AND lcx.id = {alias}.connection_id"
        f" AND lcx.location_id = ANY(CAST(:{key} AS uuid[])))"
    )
    return sql, {key: sorted(str(item) for item in location_ids)}


def conversation_ref_location_sql(
    alias: str, column: str, location_ids: frozenset[UUID] | None, key: str = "loc_ids"
) -> tuple[str, dict[str, Any]]:
    """Rows pointing at a conversation (``alias.column``): visible only if that conversation is.

    A row with no conversation (NULL) is organization-wide, so limited callers do not see it.
    """
    if location_ids is None:
        return "", {}
    inner, params = conversation_location_sql("lcv", location_ids, key)
    sql = (
        f" AND {alias}.{column} IN (SELECT lcv.id FROM conversations lcv"
        f" WHERE lcv.tenant_id = {alias}.tenant_id{inner})"
    )
    return sql, params


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


def copy_invitation_scope(db: OrmSession, invitation: Invitation, membership: Membership) -> None:
    """An accepted invitation gives the membership exactly the scope it was sent with."""
    db.execute(
        delete(MembershipLocation).where(
            MembershipLocation.tenant_id == membership.tenant_id,
            MembershipLocation.user_id == membership.user_id,
        )
    )
    membership.location_scope = invitation.location_scope
    db.add(membership)
    db.flush()
    if invitation.location_scope == "limited":
        for location_id in db.scalars(
            select(InvitationLocation.location_id).where(
                InvitationLocation.invitation_id == invitation.id
            )
        ):
            db.add(
                MembershipLocation(
                    tenant_id=membership.tenant_id,
                    user_id=membership.user_id,
                    location_id=location_id,
                )
            )
