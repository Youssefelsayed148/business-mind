"""Request and response bodies for the identity-v2 routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.schemas import PASSWORD_MIN_LENGTH

OrgRoleName = Literal["owner", "admin", "manager", "agent", "viewer"]
LocationScopeName = Literal["all", "limited"]
GrantCapName = Literal["admin", "manager", "agent", "viewer"]
INVITATION_DAYS = 7


class TeamInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    role: OrgRoleName = "viewer"
    expiry_days: int = Field(default=INVITATION_DAYS, ge=1, le=INVITATION_DAYS)
    # ``limited`` needs at least one location; ``all`` takes none (design 4.2).
    location_scope: LocationScopeName = "all"
    location_ids: list[UUID] = Field(default_factory=list, max_length=100)


class TeamInviteResponse(BaseModel):
    message: str
    # Console mail backend only (no provider yet, decision D4): the inviter delivers it.
    link_path: str | None = None


class TeamRoleChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: OrgRoleName
    # Omit both to leave the member's location scope unchanged.
    location_scope: LocationScopeName | None = None
    location_ids: list[UUID] = Field(default_factory=list, max_length=100)


class TeamMemberOut(BaseModel):
    user_id: UUID
    email: str
    role: OrgRoleName
    status: str
    location_scope: str
    location_ids: list[UUID] = Field(default_factory=list)
    joined_at: datetime


class AcceptNewAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=200)


class GrantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    role_cap: GrantCapName
    expires_at: datetime | None = None
    # Empty means every location; otherwise the grant is limited to these (design 4.2).
    location_ids: list[UUID] = Field(default_factory=list, max_length=100)


class GrantAssigneeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
