"""Identity tables (Phase 3, migrations 0032 and 0033).

Locations belong to one tenant. An agency is its own entity and never a
tenant: nothing links an agency to a client except an ``agency_grants`` row
(docs/IDENTITY-DESIGN.md section 4.3).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

LOCATION_STATUS_VALUES = ("active", "archived")
AGENCY_STATUS_VALUES = ("active", "suspended")
AGENCY_ROLE_VALUES = ("agency_admin", "agency_member")
GRANT_ROLE_CAPS = ("admin", "manager", "agent", "viewer")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_locations_status"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_locations_name"),
        UniqueConstraint("tenant_id", "id", name="uq_locations_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_locations_tenant_name"),
    )


class MembershipLocation(Base):
    __tablename__ = "membership_locations"

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    location_id: Mapped[UUID] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "user_id", "location_id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_membership_locations_member",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_membership_locations_location",
            ondelete="CASCADE",
        ),
    )


class Agency(Base):
    __tablename__ = "agencies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("status IN ('active','suspended')", name="ck_agencies_status"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_agencies_name"),
    )


class AgencyMembership(Base):
    __tablename__ = "agency_memberships"

    agency_id: Mapped[UUID] = mapped_column(
        ForeignKey("agencies.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="agency_member", server_default=text("'agency_member'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('agency_admin','agency_member')", name="ck_agency_memberships_role"
        ),
        Index("ix_agency_memberships_user", "user_id"),
    )


class AgencyGrant(Base):
    __tablename__ = "agency_grants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(
        ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    role_cap: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default=text("'active'")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "role_cap IN ('admin','manager','agent','viewer')", name="ck_agency_grants_role_cap"
        ),
        CheckConstraint("status IN ('active','revoked')", name="ck_agency_grants_status"),
        CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_agency_grants_revoked"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_agency_grants_id_tenant"),
        Index(
            "uq_agency_grants_active",
            "agency_id",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_agency_grants_tenant", "tenant_id"),
    )


class AgencyGrantAssignee(Base):
    __tablename__ = "agency_grant_assignees"

    grant_id: Mapped[UUID] = mapped_column(
        ForeignKey("agency_grants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_agency_grant_assignees_user", "user_id"),)


class AgencyGrantLocation(Base):
    __tablename__ = "agency_grant_locations"

    grant_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    location_id: Mapped[UUID] = mapped_column(nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("grant_id", "location_id"),
        ForeignKeyConstraint(
            ["grant_id", "tenant_id"],
            ["agency_grants.id", "agency_grants.tenant_id"],
            name="fk_agency_grant_locations_grant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_agency_grant_locations_location",
            ondelete="CASCADE",
        ),
    )


class UserMfa(Base):
    __tablename__ = "user_mfa"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class UserRecoveryCode(Base):
    __tablename__ = "user_recovery_codes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_user_recovery_codes_user", "user_id"),)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_password_reset_tokens_user", "user_id"),)
