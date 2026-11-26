"""Reset, MFA and session routes (identity v2; flag off answers 404)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.auth import cookies
from app.auth.schemas import PASSWORD_MIN_LENGTH, OkResponse
from app.auth.security import hash_token
from app.core.audit import record_audit
from app.core.config import Settings, get_settings
from app.core.ratelimit import client_ip
from app.db.models import Session, User
from app.db.session import get_session
from app.identity import mfa as mfa_service
from app.identity import reset as reset_service
from app.identity.gate import IdentityV2On
from app.identity.sessions import revoke_user_sessions

router = APIRouter(prefix="/api/v1/auth", tags=["identity"])

DbSession = Annotated[OrmSession, Depends(get_session)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
CurrentUser = Annotated[User, Depends(cookies.get_current_user)]
CsrfOk = Annotated[None, Depends(cookies.require_csrf)]


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=200)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=200)


class RevokeAllRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep_current: bool = True


class MfaCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=6, max_length=32)


class MessageResponse(BaseModel):
    message: str


class SessionOut(BaseModel):
    id: UUID
    created_at: datetime
    last_seen_at: datetime | None
    user_agent: str | None
    current: bool


class MfaEnrollOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaConfirmOut(BaseModel):
    recovery_codes: list[str]


@router.post("/password-reset/request", response_model=MessageResponse, status_code=202)
def password_reset_request(
    _on: IdentityV2On,
    body: PasswordResetRequest,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
) -> MessageResponse:
    """The same answer for every address."""
    reset_service.request_reset(db, settings, email=body.email, ip=client_ip(request))
    return MessageResponse(message=reset_service.REQUEST_MESSAGE)


@router.post("/password-reset/confirm", response_model=OkResponse)
def password_reset_confirm(
    _on: IdentityV2On,
    body: PasswordResetConfirm,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
) -> OkResponse:
    reset_service.confirm_reset(
        db, settings, token=body.token, new_password=body.new_password, ip=client_ip(request)
    )
    return OkResponse()


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    _on: IdentityV2On,
    request: Request,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
) -> list[SessionOut]:
    presented = cookies.read_session_token(request, settings)
    current_hash = hash_token(presented) if presented else None
    rows = db.scalars(
        select(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .order_by(Session.created_at.desc())
    )
    return [
        SessionOut(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            user_agent=row.user_agent,
            current=row.token_hash == current_hash,
        )
        for row in rows
        if row.expires_at > datetime.now(row.expires_at.tzinfo)
    ]


@router.post("/sessions/revoke-all")
def revoke_all_sessions(
    _on: IdentityV2On,
    body: RevokeAllRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    _csrf: CsrfOk,
) -> dict[str, int]:
    """Log out everywhere, keeping or dropping the session that asked."""
    presented = cookies.read_session_token(request, settings)
    keep = hash_token(presented) if presented and body.keep_current else None
    revoked = revoke_user_sessions(db, user.id, except_token_hash=keep)
    record_audit(
        db,
        action="auth.sessions_revoked",
        tenant_id=None,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
        metadata={"count": revoked, "kept_current": keep is not None},
    )
    db.commit()
    if keep is None:
        cookies.clear_session_cookie(response, settings)
    return {"revoked": revoked}


@router.get("/mfa")
def mfa_status(
    _on: IdentityV2On, db: DbSession, settings: CurrentSettings, user: CurrentUser
) -> dict[str, object]:
    return mfa_service.status(db, settings, user)


@router.post("/mfa/enroll", response_model=MfaEnrollOut)
def mfa_enroll(
    _on: IdentityV2On,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    _csrf: CsrfOk,
) -> MfaEnrollOut:
    secret, uri = mfa_service.begin_enrollment(db, settings, user)
    return MfaEnrollOut(secret=secret, otpauth_uri=uri)


@router.post("/mfa/confirm", response_model=MfaConfirmOut)
def mfa_confirm(
    _on: IdentityV2On,
    body: MfaCodeRequest,
    db: DbSession,
    settings: CurrentSettings,
    user: CurrentUser,
    _csrf: CsrfOk,
) -> MfaConfirmOut:
    """Shows the recovery codes once; only their hashes are kept."""
    return MfaConfirmOut(
        recovery_codes=mfa_service.confirm_enrollment(db, settings, user, body.code)
    )
