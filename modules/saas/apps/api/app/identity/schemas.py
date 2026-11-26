"""Request and response bodies for the identity-v2 routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.schemas import PASSWORD_MIN_LENGTH

OrgRoleName = Literal["owner", "admin", "manager", "agent", "viewer"]
GrantCapName = Literal["admin", "manager", "agent", "viewer"]
INVITATION_DAYS = 7


class TeamInviteRequest(BaseModel):
    """No location field: location-limited assignment is not available yet (decision 2)."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    role: OrgRoleName = "viewer"
    expiry_days: int = Field(default=INVITATION_DAYS, ge=1, le=INVITATION_DAYS)


class TeamInviteResponse(BaseModel):
    message: str
    # Console mail backend only (no provider yet, decision D4): the inviter delivers it.
    link_path: str | None = None


class TeamRoleChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: OrgRoleName


class TeamMemberOut(BaseModel):
    user_id: UUID
    email: str
    role: OrgRoleName
    status: str
    location_scope: str
    joined_at: datetime


class AcceptNewAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=200)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=200)


class GrantCreateRequest(BaseModel):
    """No location field for the same reason as invitations."""

    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    role_cap: GrantCapName
    expires_at: datetime | None = None


class GrantAssigneeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
