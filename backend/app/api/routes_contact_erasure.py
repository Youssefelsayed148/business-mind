"""Workspace-admin customer erasure; remote acceptance is never completion."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.authz import WorkspaceContext, require_workspace_role
from app.core.config import settings
from app.db.session import get_db
from app.models.saas_forward_event import SaasForwardEvent
from app.services import contact_erasure
from app.services.audit_service import write_audit_log
from app.services.rate_limit_service import enforce_user_rate_limit
from app.services.saas_forwarder import CHANNEL_MODELS

router = APIRouter(prefix="/privacy/contact-erasure", tags=["privacy"])
Platform = Literal["instagram", "facebook", "whatsapp"]
Admin = Depends(require_workspace_role("owner", "admin"))


class ErasureRequest(BaseModel):
    request_id: UUID
    external_contact_id: str = Field(min_length=1, max_length=255)

    @field_validator("external_contact_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if value != value.strip() or not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Identity must be nonblank without surrounding whitespace or control characters")
        return value


def _channel(db: Session, platform: str, channel_id: UUID, ctx: WorkspaceContext):
    model = CHANNEL_MODELS[platform]
    channel = db.query(model).filter(model.id == channel_id, model.workspace_id == ctx.workspace_id).first()
    if channel is None:
        raise HTTPException(404, "Channel not found")
    return channel


def _event(db: Session, platform: str, channel_id: UUID, event_id: UUID) -> SaasForwardEvent:
    event = db.query(SaasForwardEvent).filter(
        SaasForwardEvent.platform == platform, SaasForwardEvent.channel_id == channel_id,
        SaasForwardEvent.event_type == "contact.erasure", SaasForwardEvent.event_id == str(event_id),
    ).first()
    if event is None:
        raise HTTPException(404, "Erasure not found")
    return event


def _limit(ctx: WorkspaceContext) -> None:
    enforce_user_rate_limit(ctx.user, "contact_erasure", settings.ACCOUNT_MUTATION_USER_LIMIT,
                            settings.ACCOUNT_MUTATION_USER_WINDOW_SECONDS, "Too many privacy requests")


@router.post("/{platform}/{channel_id}", status_code=202)
def erase_customer(platform: Platform, channel_id: UUID, body: ErasureRequest,
                   db: Session = Depends(get_db), ctx: WorkspaceContext = Admin):
    channel = _channel(db, platform, channel_id, ctx)
    _limit(ctx)
    try:
        result = contact_erasure.erase_contact(
            db, workspace_id=ctx.workspace_id, platform=platform, channel=channel,
            external_contact_id=body.external_contact_id, request_id=body.request_id,
        )
        if not result["duplicate"]:
            write_audit_log(db, "contact_erasure_local", "Local customer erasure committed; remote completion requires verification",
                            actor=ctx.user, entity_type="privacy_request", entity_id=UUID(result["event_id"]),
                            metadata={"platform": platform, "remote_status": result["remote_status"], "counts": result["counts"]}, commit=False)
        db.commit()
        return result
    except Exception:
        db.rollback()
        # Do not log customer identities, bodies, or exception values.
        raise HTTPException(500, "Erasure was not committed; retry using the same request_id") from None


@router.get("/{platform}/{channel_id}/{event_id}")
def erasure_status(platform: Platform, channel_id: UUID, event_id: UUID,
                    db: Session = Depends(get_db), ctx: WorkspaceContext = Admin):
    _channel(db, platform, channel_id, ctx)
    event = _event(db, platform, channel_id, event_id)
    return {"event_id": event.event_id, "local_status": "erased", "remote_status": contact_erasure.remote_status(event),
            "operator_action_required": event.status in ("failed", "dropped")}


@router.post("/{platform}/{channel_id}/{event_id}/retry", status_code=202)
def retry_customer_erasure(platform: Platform, channel_id: UUID, event_id: UUID,
                            db: Session = Depends(get_db), ctx: WorkspaceContext = Admin):
    channel = _channel(db, platform, channel_id, ctx)
    event = _event(db, platform, channel_id, event_id)
    _limit(ctx)
    try:
        contact_erasure.retry_erasure(db, event, channel)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    write_audit_log(db, "contact_erasure_retried", "Customer erasure forwarding explicitly retried",
                    actor=ctx.user, entity_type="privacy_request", entity_id=event_id, commit=False)
    db.commit()
    return {"event_id": event.event_id, "local_status": "erased", "remote_status": "queued"}
