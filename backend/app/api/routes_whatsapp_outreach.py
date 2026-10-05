from __future__ import annotations

import math
import secrets
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.authz import (
    WorkspaceContext,
    require_workspace_any_permission,
    require_workspace_permission,
    require_workspace_role,
)
from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.whatsapp_ids import normalize_wa_id
from app.models.audit_log import AuditLog
from app.models.message import Message
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.services.audit_service import write_audit_log
from app.services.outreach_service import evaluate_can_send, send_outreach_message
from app.services.whatsapp_consent_service import (
    ConsentValidationError,
    MAX_IMPORT_BYTES,
    grant,
    import_contacts,
    revoke,
    record_consent_event,
)
from app.services.whatsapp_template_service import (
    TemplateInUseError,
    TemplateValidationError,
    create_draft,
    delete_template_by_name,
    render_template_components,
    submit,
    sync_templates,
)
from app.services.whatsapp_token_service import get_decrypted_token
from app.workers.whatsapp_tasks import (
    VariableMappingError,
    dispatch_whatsapp_campaign,
    resolve_campaign_variables,
    resume_whatsapp_campaign_dispatch,
    start_whatsapp_campaign,
    poll_whatsapp_account_health,
    validate_campaign_variable_mapping,
)


router = APIRouter(prefix="/whatsapp")
public_router = APIRouter(prefix="/public/whatsapp")
_redis_client: Redis | None = None
_TERMINAL = {"completed", "cancelled", "failed"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat() if value else None


def _account(db: Session, account_id: UUID, workspace_id: UUID) -> WhatsappAccount:
    row = db.query(WhatsappAccount).filter_by(id=account_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(404, "Account not found")
    return row


def _contact(db: Session, contact_id: UUID, workspace_id: UUID) -> WhatsappContact:
    row = db.query(WhatsappContact).filter_by(id=contact_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(404, "Contact not found")
    return row


def _template(db: Session, template_id: UUID, workspace_id: UUID) -> WhatsappTemplate:
    row = db.query(WhatsappTemplate).filter_by(id=template_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(404, "Template not found")
    return row


def _campaign(db: Session, campaign_id: UUID, workspace_id: UUID) -> WhatsappCampaign:
    row = db.query(WhatsappCampaign).filter_by(id=campaign_id, workspace_id=workspace_id).first()
    if row is None:
        raise HTTPException(404, "Campaign not found")
    return row


def _contact_json(row: WhatsappContact) -> dict:
    return {
        "id": str(row.id), "workspace_id": str(row.workspace_id),
        "whatsapp_account_id": str(row.whatsapp_account_id), "wa_id": row.wa_id,
        "display_name": row.display_name, "marketing_consent": row.marketing_consent,
        "consent_source": row.consent_source, "consent_at": _iso(row.consent_at),
        "opted_out_at": _iso(row.opted_out_at), "created_at": _iso(row.created_at),
    }


def _template_json(row: WhatsappTemplate) -> dict:
    return {
        "id": str(row.id), "workspace_id": str(row.workspace_id),
        "whatsapp_account_id": str(row.whatsapp_account_id), "name": row.name,
        "language": row.language, "category": row.category, "status": row.status,
        "components": row.components, "meta_template_id": row.meta_template_id,
        "rejection_reason": row.rejection_reason, "quality_score": row.quality_score,
        "last_synced_at": _iso(row.last_synced_at), "created_at": _iso(row.created_at),
    }


def _campaign_json(row: WhatsappCampaign) -> dict:
    return {
        "id": str(row.id), "workspace_id": str(row.workspace_id),
        "whatsapp_account_id": str(row.whatsapp_account_id), "template_id": str(row.template_id),
        "name": row.name, "status": row.status, "scheduled_at": _iso(row.scheduled_at),
        "completed_at": _iso(row.completed_at), "throttle_per_minute": row.throttle_per_minute,
        "variable_mapping": row.variable_mapping, "total_recipients": row.total_recipients,
        "sent_count": row.sent_count, "delivered_count": row.delivered_count,
        "read_count": row.read_count, "failed_count": row.failed_count,
        "skipped_count": row.skipped_count, "created_at": _iso(row.created_at),
    }


def _conflict(code: str, message: str | None = None) -> None:
    raise HTTPException(409, {"code": code, "message": message or code.replace("_", " ")})


def _health_reason(account: WhatsappAccount, now: datetime | None = None) -> str | None:
    now = now or _now()
    if not settings.WHATSAPP_OUTREACH_ENABLED:
        return "outreach_disabled"
    if account.status != "connected":
        return "account_disconnected"
    if account.health_checked_at is None:
        return "health_unknown"
    checked = account.health_checked_at
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    if checked < now - timedelta(minutes=settings.WHATSAPP_HEALTH_STALE_MINUTES):
        return "health_stale"
    if account.quality_rating == "RED":
        return "quality_red"
    if account.outreach_paused:
        return "outreach_paused"
    return None


class ProofPayload(BaseModel):
    proof: str = Field(min_length=1, max_length=4000)


@router.get("/contacts")
def list_contacts(account_id: UUID | None = None, consent: str | None = None,
                  search: str | None = None, cursor: UUID | None = None,
                  limit: int = Query(default=50, ge=1, le=200),
                  db: Session = Depends(get_db),
                  ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    query = db.query(WhatsappContact).filter(WhatsappContact.workspace_id == ctx.workspace_id)
    if account_id:
        _account(db, account_id, ctx.workspace_id)
        query = query.filter(WhatsappContact.whatsapp_account_id == account_id)
    if consent:
        query = query.filter(WhatsappContact.marketing_consent == consent)
    if search:
        query = query.filter(or_(WhatsappContact.wa_id.ilike(f"%{search}%"),
                                 WhatsappContact.display_name.ilike(f"%{search}%")))
    if cursor:
        query = query.filter(WhatsappContact.id > cursor)
    rows = query.order_by(WhatsappContact.id).limit(limit + 1).all()
    return {"items": [_contact_json(row) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None}


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: UUID, db: Session = Depends(get_db),
                ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    row = _contact(db, contact_id, ctx.workspace_id)
    result = _contact_json(row)
    events = db.query(WhatsappConsentEvent).filter_by(
        contact_id=row.id, workspace_id=ctx.workspace_id).order_by(
        WhatsappConsentEvent.created_at.desc()).all()
    result["consent_history"] = [{"id": str(event.id), "event_type": event.event_type,
        "source": event.source, "evidence": event.evidence,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "created_at": _iso(event.created_at)} for event in events]
    return result


@router.post("/contacts/import", status_code=201)
async def import_contact_csv(account_id: UUID = Form(...), attestation: str = Form(...),
                             file: UploadFile = File(...), db: Session = Depends(get_db),
                             ctx: WorkspaceContext = Depends(require_workspace_permission("manage_contacts"))):
    account = _account(db, account_id, ctx.workspace_id)
    data = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        result = import_contacts(db, account=account, csv_data=data,
            filename=file.filename or "contacts.csv", actor=ctx.user,
            attestation_text=attestation)
    except ConsentValidationError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return result.__dict__


@router.post("/contacts/{contact_id}/grant")
def grant_contact(contact_id: UUID, payload: ProofPayload, db: Session = Depends(get_db),
                  ctx: WorkspaceContext = Depends(require_workspace_permission("manage_contacts"))):
    row = _contact(db, contact_id, ctx.workspace_id)
    try:
        grant(db, contact=row, actor=ctx.user, evidence={"proof": payload.proof})
    except ConsentValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit(); db.refresh(row)
    return _contact_json(row)


@router.post("/contacts/{contact_id}/revoke")
def revoke_contact(contact_id: UUID, payload: ProofPayload, db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_permission("manage_contacts"))):
    row = _contact(db, contact_id, ctx.workspace_id)
    revoke(db, contact=row, actor=ctx.user, evidence={"proof": payload.proof})
    db.commit(); db.refresh(row)
    return _contact_json(row)


class TemplateCreate(BaseModel):
    account_id: UUID
    name: str
    language: str
    category: str
    components: list[dict] = Field(default_factory=list)


class TemplatePatch(BaseModel):
    name: str | None = None
    language: str | None = None
    category: str | None = None
    components: list[dict] | None = None


@router.get("/templates")
def list_templates(account_id: UUID | None = None, template_status: str | None = None,
                   db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    query = db.query(WhatsappTemplate).filter_by(workspace_id=ctx.workspace_id)
    if account_id:
        _account(db, account_id, ctx.workspace_id)
        query = query.filter_by(whatsapp_account_id=account_id)
    if template_status: query = query.filter_by(status=template_status)
    return [_template_json(row) for row in query.order_by(WhatsappTemplate.created_at.desc()).all()]


@router.post("/templates", status_code=201)
def post_template(payload: TemplateCreate, db: Session = Depends(get_db),
                  ctx: WorkspaceContext = Depends(require_workspace_permission("manage_templates"))):
    account = _account(db, payload.account_id, ctx.workspace_id)
    try:
        row = create_draft(db, account=account, name=payload.name, language=payload.language,
                           category=payload.category, components=payload.components)
    except TemplateValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit(); db.refresh(row)
    return _template_json(row)


@router.get("/templates/{template_id}")
def get_template(template_id: UUID, db: Session = Depends(get_db),
                 ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    return _template_json(_template(db, template_id, ctx.workspace_id))


@router.patch("/templates/{template_id}")
def patch_template(template_id: UUID, payload: TemplatePatch, db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_permission("manage_templates"))):
    row = _template(db, template_id, ctx.workspace_id)
    if row.status not in {"draft", "rejected"}: _conflict("template_not_editable")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items(): setattr(row, key, value)
    from app.services.whatsapp_template_service import _validate
    try: _validate(row.name, row.category.lower(), row.components)
    except TemplateValidationError as exc: raise HTTPException(422, str(exc)) from exc
    row.category = row.category.lower(); row.status = "draft"
    db.commit(); db.refresh(row)
    return _template_json(row)


@router.delete("/templates/{template_id}")
def remove_template(template_id: UUID, db: Session = Depends(get_db),
                    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_templates"))):
    row = _template(db, template_id, ctx.workspace_id)
    account = _account(db, row.whatsapp_account_id, ctx.workspace_id)
    active_reference = db.query(WhatsappCampaign.id).filter(
        WhatsappCampaign.template_id == row.id,
        WhatsappCampaign.status.notin_(_TERMINAL),
    ).first()
    if active_reference:
        _conflict("template_in_use_by_active_campaign")
    if row.status in {"draft", "rejected"} and row.meta_template_id is None:
        row.status = "deleted"
        db.commit()
        return {"status": "deleted", "id": str(row.id)}
    token = get_decrypted_token(db, account.id)
    if not token: raise HTTPException(409, "WhatsApp access token is unavailable")
    try: result = delete_template_by_name(db, account=account, name=row.name, access_token=token)
    except TemplateInUseError as exc: raise HTTPException(409, str(exc)) from exc
    if not result.success: raise HTTPException(502, result.error_message or "Meta template deletion failed")
    db.commit()
    return {"status": "deleted", "id": str(row.id)}


@router.post("/templates/{template_id}/submit")
def submit_template(template_id: UUID, db: Session = Depends(get_db),
                    ctx: WorkspaceContext = Depends(require_workspace_permission("manage_templates"))):
    row = _template(db, template_id, ctx.workspace_id)
    if row.status not in {"draft", "rejected"}: _conflict("template_not_submittable")
    account = _account(db, row.whatsapp_account_id, ctx.workspace_id)
    token = get_decrypted_token(db, account.id)
    if not token: raise HTTPException(409, "WhatsApp access token is unavailable")
    try: result = submit(db, template=row, account=account, access_token=token)
    except TemplateValidationError as exc: raise HTTPException(422, str(exc)) from exc
    if not result.success: raise HTTPException(502, result.error_message or "Meta template submission failed")
    db.commit(); db.refresh(row)
    return _template_json(row)


@router.post("/accounts/{account_id}/templates/sync", status_code=202)
def sync_account_templates(account_id: UUID, db: Session = Depends(get_db),
                           ctx: WorkspaceContext = Depends(require_workspace_permission("manage_templates"))):
    account = _account(db, account_id, ctx.workspace_id)
    token = get_decrypted_token(db, account.id)
    if not token: raise HTTPException(409, "WhatsApp access token is unavailable")
    result = sync_templates(db, account=account, access_token=token)
    if not result.success: raise HTTPException(502, result.error_message or "Template sync failed")
    db.commit()
    return result.__dict__


class VariablesPayload(BaseModel):
    variables: list[object] | dict = Field(default_factory=list)


@router.post("/templates/{template_id}/preview")
def preview_template(template_id: UUID, payload: VariablesPayload, db: Session = Depends(get_db),
                     ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    row = _template(db, template_id, ctx.workspace_id)
    try: components = render_template_components(row, payload.variables)
    except TemplateValidationError as exc: raise HTTPException(422, str(exc)) from exc
    return {"components": components}


class TestSendPayload(VariablesPayload):
    contact_id: UUID


def _strict_daily_test_limit(workspace_id: UUID) -> None:
    global _redis_client
    try:
        _redis_client = _redis_client or Redis.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"whatsapp:test-send:{workspace_id}:{_now().date().isoformat()}"
        count = int(_redis_client.incr(key))
        if count == 1: _redis_client.expire(key, 172800)
    except RedisError as exc:
        raise HTTPException(503, "Test-send rate limiting is temporarily unavailable") from exc
    if count > settings.WHATSAPP_TEST_SEND_DAILY_LIMIT:
        raise HTTPException(429, "Workspace test-send daily limit reached")


@router.post("/templates/{template_id}/test-send")
def test_send(template_id: UUID, payload: TestSendPayload, db: Session = Depends(get_db),
              ctx: WorkspaceContext = Depends(require_workspace_permission("manage_templates"))):
    _strict_daily_test_limit(ctx.workspace_id)
    template = _template(db, template_id, ctx.workspace_id)
    contact = _contact(db, payload.contact_id, ctx.workspace_id)
    account = _account(db, template.whatsapp_account_id, ctx.workspace_id)
    proof = db.query(WhatsappConsentEvent).filter(
        WhatsappConsentEvent.contact_id == contact.id,
        WhatsappConsentEvent.source == "manual",
        WhatsappConsentEvent.actor_user_id.isnot(None),
        WhatsappConsentEvent.event_type.in_({"opt_in", "resubscribe"}),
    ).order_by(WhatsappConsentEvent.created_at.desc()).first()
    if contact.marketing_consent != "opted_in" or proof is None or not (
        proof.evidence.get("proof") or proof.evidence.get("note")):
        _conflict("manual_consent_proof_required")
    decision = evaluate_can_send(db, contact=contact, template=template, account=account)
    if not decision.allowed: _conflict(decision.reason_code or "send_refused")
    try: components = render_template_components(template, payload.variables)
    except TemplateValidationError as exc: raise HTTPException(422, str(exc)) from exc
    campaign = WhatsappCampaign(workspace_id=ctx.workspace_id, whatsapp_account_id=account.id,
        template_id=template.id, name=f"Test send {datetime.now().isoformat()}", status="running",
        variable_mapping={}, created_by=ctx.user.id, total_recipients=1)
    db.add(campaign); db.flush()
    recipient = WhatsappCampaignRecipient(campaign_id=campaign.id, contact_id=contact.id, status="pending")
    db.add(recipient); db.commit()
    campaign_id = campaign.id
    recipient_id = recipient.id
    result = None
    send_error = None
    try:
        result = send_outreach_message(db, recipient_id=recipient.id, components=components)
    except Exception as exc:
        send_error = exc
        if not db.is_active:
            db.rollback()
    finally:
        # Always make the one-off campaign terminal so the watchdog can never
        # dispatch a leftover recipient after a refusal or exception.
        campaign = db.get(WhatsappCampaign, campaign_id)
        recipient = db.get(WhatsappCampaignRecipient, recipient_id)
        if result is not None and result.sent:
            campaign.status = "completed"
        else:
            campaign.status = "failed"
            recipient.status = "failed" if send_error is not None else "skipped_not_eligible"
            recipient.error_code = (
                "test_send_exception" if send_error is not None
                else (result.reason_code or "test_send_refused")
            )
        campaign.completed_at = _now()
        db.commit()
    if send_error is not None:
        raise send_error
    return {"accepted": result.sent, "reason_code": result.reason_code,
            "message_id": str(result.message_id) if result.message_id else None}


class CampaignCreate(BaseModel):
    account_id: UUID
    template_id: UUID
    name: str = Field(min_length=1, max_length=255)
    scheduled_at: datetime | None = None
    throttle_per_minute: int = Field(default=30, ge=1, le=1000)
    variable_mapping: dict = Field(default_factory=dict)


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    scheduled_at: datetime | None = None
    throttle_per_minute: int | None = Field(default=None, ge=1, le=1000)
    variable_mapping: dict | None = None
    template_id: UUID | None = None


@router.get("/campaigns")
def list_whatsapp_campaigns(account_id: UUID | None = None, campaign_status: str | None = None,
                            db: Session = Depends(get_db),
                            ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    query = db.query(WhatsappCampaign).filter_by(workspace_id=ctx.workspace_id)
    if account_id:
        _account(db, account_id, ctx.workspace_id)
        query = query.filter_by(whatsapp_account_id=account_id)
    if campaign_status: query = query.filter_by(status=campaign_status)
    return [_campaign_json(row) for row in query.order_by(WhatsappCampaign.created_at.desc()).all()]


@router.post("/campaigns", status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db),
                    ctx: WorkspaceContext = Depends(require_workspace_permission("run_campaigns"))):
    account = _account(db, payload.account_id, ctx.workspace_id)
    template = _template(db, payload.template_id, ctx.workspace_id)
    if template.whatsapp_account_id != account.id: _conflict("outreach_scope_mismatch")
    row = WhatsappCampaign(workspace_id=ctx.workspace_id, whatsapp_account_id=account.id,
        template_id=template.id, name=payload.name,
        status="scheduled" if payload.scheduled_at else "draft", scheduled_at=payload.scheduled_at,
        throttle_per_minute=payload.throttle_per_minute, variable_mapping=payload.variable_mapping,
        created_by=ctx.user.id)
    db.add(row); db.commit(); db.refresh(row)
    return _campaign_json(row)


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: UUID, db: Session = Depends(get_db),
                 ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    return _campaign_json(_campaign(db, campaign_id, ctx.workspace_id))


@router.patch("/campaigns/{campaign_id}")
def patch_campaign(campaign_id: UUID, payload: CampaignPatch, db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_permission("run_campaigns"))):
    row = _campaign(db, campaign_id, ctx.workspace_id)
    if row.status != "draft": _conflict("campaign_not_editable")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(row, key, value)
    if row.template_id:
        template = _template(db, row.template_id, ctx.workspace_id)
        if template.whatsapp_account_id != row.whatsapp_account_id: _conflict("outreach_scope_mismatch")
    db.commit(); db.refresh(row)
    return _campaign_json(row)


class DryRunPayload(BaseModel):
    variable_mapping: dict | None = None


@router.post("/campaigns/{campaign_id}/dry-run")
def dry_run(campaign_id: UUID, payload: DryRunPayload | None = None,
            db: Session = Depends(get_db),
            ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    campaign = _campaign(db, campaign_id, ctx.workspace_id)
    account = _account(db, campaign.whatsapp_account_id, ctx.workspace_id)
    template = _template(db, campaign.template_id, ctx.workspace_id)
    contacts = db.query(WhatsappContact).filter_by(
        workspace_id=ctx.workspace_id, whatsapp_account_id=account.id).all()
    terminal, deferrable = Counter(), Counter()
    eligible = []
    mapping_owner = SimpleNamespace(
        variable_mapping=(payload.variable_mapping if payload and payload.variable_mapping is not None
                          else campaign.variable_mapping)
    )
    for contact in contacts:
        decision = evaluate_can_send(db, contact=contact, template=template, account=account,
            campaign=campaign, enforce_campaign_status=False, enforce_daily_cap=False)
        if not decision.allowed and not decision.deferrable:
            terminal[decision.reason_code] += 1
            continue
        try:
            resolve_campaign_variables(mapping_owner, template, contact)
        except VariableMappingError:
            terminal["variable_unresolved"] += 1
            continue
        if decision.allowed: eligible.append(contact)
        else: deferrable[decision.reason_code] += 1
    used = db.query(func.count(func.distinct(WhatsappCampaignRecipient.contact_id))).join(
        Message, Message.id == WhatsappCampaignRecipient.message_id).join(
        WhatsappCampaign, WhatsappCampaign.id == WhatsappCampaignRecipient.campaign_id).filter(
        WhatsappCampaign.whatsapp_account_id == account.id,
        Message.created_at >= _now() - timedelta(hours=24),
        or_(Message.status.in_({"sending", "sent", "delivered", "read"}),
            Message.error_code == "outcome_unknown")).scalar() or 0
    sendable_total = len(eligible) + sum(deferrable.values())
    remaining_today = max(0, account.outreach_daily_cap - int(used))
    cap_blocked = max(0, len(eligible) - remaining_today)
    if cap_blocked: deferrable["daily_cap_reached"] += cap_blocked
    immediately_eligible = len(eligible) - cap_blocked
    days = math.ceil((sendable_total + int(used)) / account.outreach_daily_cap) if sendable_total else 0
    return {"eligible": immediately_eligible, "terminal_skips": {"count": sum(terminal.values()),
        "reasons": dict(terminal)}, "deferrable_blocks": {"count": sum(deferrable.values()),
        "reasons": dict(deferrable)}, "estimated_days_to_finish": days,
        "daily_cap": account.outreach_daily_cap, "used_in_rolling_24h": int(used)}


def _audit_transition(db, campaign, ctx, old, new, note=None):
    write_audit_log(db, "whatsapp_campaign_status_changed", f"Campaign {old} -> {new}",
        actor=ctx.user, entity_type="whatsapp_campaign", entity_id=campaign.id,
        entity_name=campaign.name, metadata={"workspace_id": str(ctx.workspace_id),
        "old": old, "new": new, "note": note}, commit=False)


@router.post("/campaigns/{campaign_id}/start", status_code=202)
def start_campaign(campaign_id: UUID, db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_permission("run_campaigns"))):
    campaign = _campaign(db, campaign_id, ctx.workspace_id)
    if campaign.status not in {"draft", "scheduled"}: _conflict("illegal_campaign_transition")
    account = _account(db, campaign.whatsapp_account_id, ctx.workspace_id)
    template = _template(db, campaign.template_id, ctx.workspace_id)
    if template.status != "approved": _conflict("template_not_approved")
    if template.category == "authentication": _conflict("template_category_unsupported")
    try:
        validate_campaign_variable_mapping(campaign, template)
    except VariableMappingError as exc:
        _conflict("variable_mapping_invalid", str(exc))
    reason = _health_reason(account)
    if reason: _conflict(reason)
    # The worker owns audience freezing and the draft/scheduled -> running transition.
    start_whatsapp_campaign.delay(str(campaign.id))
    return {**_campaign_json(campaign), "dispatch_queued": True}


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: UUID, db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_permission("run_campaigns"))):
    campaign = _campaign(db, campaign_id, ctx.workspace_id)
    if campaign.status != "running": _conflict("illegal_campaign_transition")
    old = campaign.status; campaign.status = "paused"; _audit_transition(db, campaign, ctx, old, "paused")
    db.commit(); db.refresh(campaign)
    return _campaign_json(campaign)


class ResumePayload(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: UUID, payload: ResumePayload, db: Session = Depends(get_db),
                    ctx: WorkspaceContext = Depends(require_workspace_permission("run_campaigns"))):
    campaign = _campaign(db, campaign_id, ctx.workspace_id)
    if campaign.status != "paused": _conflict("illegal_campaign_transition")
    account = _account(db, campaign.whatsapp_account_id, ctx.workspace_id)
    # Resume always re-checks freshness and quality; a note cannot override stale/RED health.
    reason = _health_reason(account)
    if reason and reason != "outreach_paused": _conflict(reason)
    if account.health_checked_at is None: _conflict("health_unknown")
    checked = account.health_checked_at
    if checked.tzinfo is None: checked = checked.replace(tzinfo=timezone.utc)
    if checked < _now() - timedelta(minutes=settings.WHATSAPP_HEALTH_STALE_MINUTES): _conflict("health_stale")
    if account.quality_rating == "RED": _conflict("quality_red")
    paused_at = account.outreach_paused_at
    if paused_at is None and not account.outreach_paused:
        # Operator/circuit-breaker campaign pauses do not pause the account.
        # Require a poll newer than the campaign transition in that case.
        paused_at = campaign.updated_at
    if paused_at is None:
        _conflict("health_unconfirmed")
    if paused_at.tzinfo is None: paused_at = paused_at.replace(tzinfo=timezone.utc)
    if checked <= paused_at:
        _conflict("health_unconfirmed")
    old = campaign.status; campaign.status = "running"; campaign.completed_at = None
    account.outreach_paused = False; account.outreach_paused_reason = None
    account.outreach_paused_at = None
    _audit_transition(db, campaign, ctx, old, "running", payload.note)
    db.commit(); db.refresh(campaign)
    # Deliberately after the audited transaction commits.
    resume_whatsapp_campaign_dispatch.delay(str(campaign.id))
    return _campaign_json(campaign)


@router.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: UUID, db: Session = Depends(get_db),
                    ctx: WorkspaceContext = Depends(require_workspace_permission("run_campaigns"))):
    campaign = _campaign(db, campaign_id, ctx.workspace_id)
    if campaign.status not in {"draft", "scheduled", "running", "paused"}: _conflict("illegal_campaign_transition")
    old = campaign.status; campaign.status = "cancelled"
    _audit_transition(db, campaign, ctx, old, "cancelled")
    # Pending recipient rows intentionally remain untouched. Dispatch and rollup only select running campaigns.
    db.commit(); db.refresh(campaign)
    return _campaign_json(campaign)


@router.get("/campaigns/{campaign_id}/stats")
def campaign_stats(campaign_id: UUID, db: Session = Depends(get_db),
                   ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    campaign = _campaign(db, campaign_id, ctx.workspace_id)
    grouped = db.query(WhatsappCampaignRecipient.status, func.count(WhatsappCampaignRecipient.id)).filter_by(
        campaign_id=campaign.id).group_by(WhatsappCampaignRecipient.status).all()
    reasons = dict(db.query(WhatsappCampaignRecipient.error_code, func.count(WhatsappCampaignRecipient.id)).filter(
        WhatsappCampaignRecipient.campaign_id == campaign.id,
        WhatsappCampaignRecipient.error_code.isnot(None)).group_by(
        WhatsappCampaignRecipient.error_code).all())
    return {"campaign": _campaign_json(campaign), "recipient_statuses": dict(grouped),
            "reasons": reasons, "row_count": sum(value for _, value in grouped)}


class OutreachSettings(BaseModel):
    ctwa_counts_as_consent: bool | None = None
    transactional_utility_attested: bool | None = None
    opt_out_keywords: list[str] | None = None
    opt_in_keywords: list[str] | None = None
    outreach_daily_cap: int | None = Field(default=None, ge=1, le=100000)


@router.get("/accounts/{account_id}/outreach-health")
def outreach_health(account_id: UUID, db: Session = Depends(get_db),
                    ctx: WorkspaceContext = Depends(require_workspace_role("owner", "admin"))):
    account = _account(db, account_id, ctx.workspace_id)
    age = (_now() - account.health_checked_at).total_seconds() if account.health_checked_at else None
    used = db.query(func.count(func.distinct(WhatsappCampaignRecipient.contact_id))).join(
        Message, Message.id == WhatsappCampaignRecipient.message_id).join(
        WhatsappCampaign, WhatsappCampaign.id == WhatsappCampaignRecipient.campaign_id).filter(
        WhatsappCampaign.whatsapp_account_id == account.id,
        Message.created_at >= _now() - timedelta(hours=24),
        or_(Message.status.in_({"sending", "sent", "delivered", "read"}),
            Message.error_code == "outcome_unknown")).scalar() or 0
    return {"quality_rating": account.quality_rating, "messaging_limit_tier": account.messaging_limit_tier,
        "outreach_paused": account.outreach_paused, "outreach_paused_reason": account.outreach_paused_reason,
        "outreach_paused_at": _iso(account.outreach_paused_at),
        "health_checked_at": _iso(account.health_checked_at), "health_age_seconds": age,
        "sent_recipient_count_24h": int(used), "daily_cap": account.outreach_daily_cap,
        "outreach_enabled": settings.WHATSAPP_OUTREACH_ENABLED,
        "ctwa_counts_as_consent": account.ctwa_counts_as_consent,
        "transactional_utility_attested": account.transactional_utility_attested,
        "opt_in_keywords": account.opt_in_keywords,
        "opt_out_keywords": account.opt_out_keywords,
        "outreach_daily_cap": account.outreach_daily_cap}


def _strict_health_refresh_limit(account_id: UUID) -> None:
    global _redis_client
    try:
        _redis_client = _redis_client or Redis.from_url(settings.REDIS_URL, decode_responses=True)
        acquired = _redis_client.set(
            f"whatsapp:health-refresh:{account_id}", "1", nx=True, ex=60
        )
    except RedisError as exc:
        raise HTTPException(503, "Health refresh is temporarily unavailable") from exc
    if not acquired:
        raise HTTPException(429, "Health was refreshed recently. Please wait a minute.")


@router.post("/accounts/{account_id}/health-refresh", status_code=202)
def refresh_account_health(
    account_id: UUID,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(
        require_workspace_any_permission("run_campaigns", "manage_contacts")
    ),
):
    _account(db, account_id, ctx.workspace_id)
    _strict_health_refresh_limit(account_id)
    poll_whatsapp_account_health.delay(str(account_id))
    return {"accepted": True, "account_id": str(account_id)}


@router.patch("/accounts/{account_id}/outreach-settings")
def update_outreach_settings(account_id: UUID, payload: OutreachSettings,
                             db: Session = Depends(get_db),
                             ctx: WorkspaceContext = Depends(require_workspace_permission("manage_contacts"))):
    account = _account(db, account_id, ctx.workspace_id)
    values = payload.model_dump(exclude_unset=True)
    for key in ("opt_in_keywords", "opt_out_keywords"):
        if key in values and values[key] is not None:
            cleaned = [value.strip().upper() for value in values[key] if value.strip()]
            if len(cleaned) != len(set(cleaned)): raise HTTPException(422, f"{key} contains duplicates")
            values[key] = cleaned
    old = {key: getattr(account, key) for key in values}
    for key, value in values.items(): setattr(account, key, value)
    write_audit_log(db, "whatsapp_outreach_settings_updated", "WhatsApp outreach settings updated",
        actor=ctx.user, entity_type="whatsapp_account", entity_id=account.id,
        entity_name=account.display_phone_number or account.phone_number_id,
        metadata={"workspace_id": str(ctx.workspace_id), "old": old, "new": values}, commit=False)
    db.commit(); db.refresh(account)
    return {key: getattr(account, key) for key in OutreachSettings.model_fields}


class OptInLinkPayload(BaseModel):
    rotate: bool = False


@router.post("/accounts/{account_id}/opt-in-link")
def opt_in_link(account_id: UUID, payload: OptInLinkPayload | None = None,
                db: Session = Depends(get_db),
                ctx: WorkspaceContext = Depends(require_workspace_permission("manage_contacts"))):
    account = _account(db, account_id, ctx.workspace_id)
    if not account.opt_in_keywords:
        _conflict("opt_in_keyword_required", "Configure at least one opt-in keyword before enabling the public opt-in link.")
    rotate = bool(payload and payload.rotate)
    if rotate:
        account.opt_in_link_salt = uuid.uuid4(); db.commit(); db.refresh(account)
    expires = _now() + timedelta(seconds=settings.WHATSAPP_OPT_IN_LINK_TTL_SECONDS)
    token = jwt.encode({"workspace_id": str(ctx.workspace_id), "account_id": str(account.id),
        "salt": str(account.opt_in_link_salt), "aud": "whatsapp_opt_in", "exp": expires},
        settings.APP_SECRET_KEY, algorithm="HS256")
    dashboard_base_url = settings.DASHBOARD_BASE_URL or settings.APP_BASE_URL
    return {"url": f"{dashboard_base_url.rstrip('/')}/opt-in/{token}",
            "expires_at": expires.isoformat(), "rotated": rotate,
            "older_links_revoked": rotate}


class PublicOptInPayload(BaseModel):
    phone: str


def _strict_public_limit(request: Request, account_id: UUID) -> None:
    global _redis_client
    try:
        _redis_client = _redis_client or Redis.from_url(settings.REDIS_URL, decode_responses=True)
        ip = request.client.host if request.client else "unknown"
        for key, limit in ((f"whatsapp:public-opt-in:ip:{ip}", settings.WHATSAPP_PUBLIC_OPT_IN_IP_LIMIT),
                           (f"whatsapp:public-opt-in:account:{account_id}", settings.WHATSAPP_PUBLIC_OPT_IN_ACCOUNT_LIMIT)):
            count = int(_redis_client.incr(key))
            if count == 1: _redis_client.expire(key, settings.WHATSAPP_PUBLIC_OPT_IN_WINDOW_SECONDS)
            if count > limit: raise HTTPException(429, "Too many opt-in requests. Please try again later.")
    except RedisError as exc:
        raise HTTPException(503, "Opt-in service is temporarily unavailable") from exc


def _public_opt_in_permission(signed_token: str) -> dict:
    """Authorize a public capability without requiring a workspace login."""
    try:
        return jwt.decode(signed_token, settings.APP_SECRET_KEY, algorithms=["HS256"],
                          audience="whatsapp_opt_in", options={"require": ["exp", "aud"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(404, "Opt-in link is invalid or expired") from exc


@public_router.post("/opt-in/{signed_token}", status_code=202,
                    dependencies=[Depends(_public_opt_in_permission)])
def public_opt_in(signed_token: str, payload: PublicOptInPayload, request: Request,
                  db: Session = Depends(get_db)):
    try:
        claims = _public_opt_in_permission(signed_token)
        account_id, workspace_id = UUID(claims["account_id"]), UUID(claims["workspace_id"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(404, "Opt-in link is invalid or expired") from exc
    account = db.query(WhatsappAccount).filter_by(id=account_id, workspace_id=workspace_id).first()
    if account is None or not secrets.compare_digest(str(account.opt_in_link_salt), str(claims.get("salt", ""))):
        raise HTTPException(404, "Opt-in link is invalid or expired")
    if not account.opt_in_keywords:
        _conflict("opt_in_keyword_required", "This opt-in link is disabled until an administrator configures an opt-in keyword.")
    _strict_public_limit(request, account.id)
    raw = payload.phone.strip(); wa_id = normalize_wa_id(raw)
    if wa_id is None or not raw.startswith("+") or raw[1:] != wa_id:
        raise HTTPException(422, "phone must be explicit international +E.164 format")
    contact = db.query(WhatsappContact).filter_by(whatsapp_account_id=account.id, wa_id=wa_id).first()
    if contact is None:
        contact = WhatsappContact(workspace_id=workspace_id, whatsapp_account_id=account.id,
                                  wa_id=wa_id, marketing_consent="unknown")
        db.add(contact); db.flush()
    evidence = {"ip": request.client.host if request.client else "unknown",
        "request_host": request.url.netloc,
        "request_path": "/public/whatsapp/opt-in/{token}",
        "user_agent": request.headers.get("user-agent"),
        "submitted_at": _now().isoformat(), "workspace_id": str(workspace_id),
        "account_id": str(account.id), "token_salt": str(account.opt_in_link_salt)}
    record_consent_event(db, contact, event_type="opt_in_unverified", source="web_form", evidence=evidence)
    db.commit()
    keyword = account.opt_in_keywords[0]
    business = normalize_wa_id(account.display_phone_number)
    click_url = f"https://wa.me/{business}?text={quote(keyword)}" if business else None
    # Identical response for a newly-created or already-known contact.
    return {"accepted": True, "message": "Open WhatsApp and send the prepared message to confirm opt-in.",
            "click_to_chat_url": click_url}
