from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import distinct, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.meta.whatsapp_client import WhatsappClient, WhatsappMessageResult
from app.integrations.meta.whatsapp_ids import normalize_wa_id
from app.models.message import Message
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.services import whatsapp_token_service
from app.services.whatsapp_consent_service import is_marketing_allowed


@dataclass(frozen=True)
class SendDecision:
    allowed: bool
    reason_code: str | None = None
    deferrable: bool = False


@dataclass(frozen=True)
class OutreachSendResult:
    sent: bool
    reason_code: str | None
    message_id: UUID | None = None
    provider_message_id: str | None = None
    deferrable: bool = False


_DELIVERED_MESSAGE_STATUSES = {"sending", "sent", "delivered", "read"}
_FINISHED_RECIPIENT_STATUSES = {"sent", "delivered", "read"}
TERMINAL_REFUSAL_REASONS = frozenset(
    {
        "contact_opted_out",
        "marketing_consent_required",
        "transactional_attestation_required",
        "invalid_wa_id",
        "account_mismatch",
        "workspace_mismatch",
        "outreach_scope_mismatch",
        "template_not_approved",
        "template_paused",
        "template_category_unsupported",
        "already_sent_in_campaign",
    }
)
DEFERRABLE_REFUSAL_REASONS = frozenset(
    {
        "outreach_disabled",
        "outreach_paused",
        "health_unknown",
        "health_stale",
        "quality_red",
        "account_disconnected",
        "daily_cap_reached",
        "campaign_not_running",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _recipient_for(
    db: Session, campaign: WhatsappCampaign | None, contact: WhatsappContact
) -> WhatsappCampaignRecipient | None:
    if campaign is None:
        return None
    return (
        db.query(WhatsappCampaignRecipient)
        .filter(
            WhatsappCampaignRecipient.campaign_id == campaign.id,
            WhatsappCampaignRecipient.contact_id == contact.id,
        )
        .first()
    )


def _refuse(
    db: Session,
    *,
    campaign: WhatsappCampaign | None,
    contact: WhatsappContact,
    reason: str,
) -> SendDecision:
    if reason not in TERMINAL_REFUSAL_REASONS | DEFERRABLE_REFUSAL_REASONS:
        raise ValueError(f"Unclassified outreach refusal reason: {reason}")
    deferrable = reason in DEFERRABLE_REFUSAL_REASONS
    recipient = _recipient_for(db, campaign, contact)
    if recipient is not None:
        if deferrable and recipient.status in {"queued", "pending", "sending"}:
            recipient.status = "pending"
            recipient.error_code = None
            recipient.error_message = None
        elif not deferrable and recipient.status in {"queued", "pending", "sending"}:
            recipient.status = "skipped_not_eligible"
            recipient.error_code = reason
            recipient.error_message = None
            if campaign is not None:
                campaign.skipped_count += 1
        db.flush()
    return SendDecision(False, reason, deferrable=deferrable)


def _daily_recipient_count(db: Session, account: WhatsappAccount, now: datetime) -> int:
    db.flush()
    return int(
        db.query(func.count(distinct(WhatsappCampaignRecipient.contact_id)))
        .join(Message, Message.id == WhatsappCampaignRecipient.message_id)
        .join(WhatsappCampaign, WhatsappCampaign.id == WhatsappCampaignRecipient.campaign_id)
        .filter(
            WhatsappCampaign.whatsapp_account_id == account.id,
            or_(
                Message.status.in_(_DELIVERED_MESSAGE_STATUSES),
                Message.error_code == "outcome_unknown",
            ),
            Message.created_at >= now - timedelta(hours=24),
        )
        .scalar()
        or 0
    )


def check_can_send(
    db: Session,
    *,
    contact: WhatsappContact,
    template: WhatsappTemplate,
    account: WhatsappAccount,
    campaign: WhatsappCampaign | None = None,
    now: datetime | None = None,
) -> SendDecision:
    """The fail-closed policy choke point for every business-initiated send."""
    now = now or _utcnow()
    checks: list[tuple[bool, str]] = [
        (settings.WHATSAPP_OUTREACH_ENABLED, "outreach_disabled"),
        (normalize_wa_id(contact.wa_id) == contact.wa_id, "invalid_wa_id"),
        (contact.whatsapp_account_id == account.id, "account_mismatch"),
        (contact.workspace_id == account.workspace_id, "workspace_mismatch"),
        (
            template.whatsapp_account_id == account.id
            and template.workspace_id == account.workspace_id
            and (campaign is None or (
                campaign.whatsapp_account_id == account.id
                and campaign.workspace_id == account.workspace_id
                and campaign.template_id == template.id
            )),
            "outreach_scope_mismatch",
        ),
        (campaign is None or campaign.status == "running", "campaign_not_running"),
        (account.status == "connected", "account_disconnected"),
        (not account.outreach_paused, "outreach_paused"),
        (account.health_checked_at is not None, "health_unknown"),
        (
            account.health_checked_at is not None
            and account.health_checked_at >= now - timedelta(minutes=settings.WHATSAPP_HEALTH_STALE_MINUTES),
            "health_stale",
        ),
        (account.quality_rating is not None, "health_unknown"),
        (account.quality_rating != "RED", "quality_red"),
        (contact.marketing_consent != "opted_out", "contact_opted_out"),
    ]
    for passed, reason in checks:
        if not passed:
            return _refuse(db, campaign=campaign, contact=contact, reason=reason)

    if campaign is not None and template.category == "authentication":
        return _refuse(
            db, campaign=campaign, contact=contact, reason="template_category_unsupported"
        )
    if template.category == "marketing" and not is_marketing_allowed(contact, account, now=now):
        return _refuse(db, campaign=campaign, contact=contact, reason="marketing_consent_required")
    if (
        template.category == "utility"
        and contact.marketing_consent == "unknown"
        and not account.transactional_utility_attested
    ):
        return _refuse(
            db, campaign=campaign, contact=contact, reason="transactional_attestation_required"
        )
    if template.status != "approved":
        reason = "template_paused" if template.status in {"paused", "disabled"} else "template_not_approved"
        return _refuse(db, campaign=campaign, contact=contact, reason=reason)
    if _daily_recipient_count(db, account, now) >= account.outreach_daily_cap:
        return _refuse(db, campaign=campaign, contact=contact, reason="daily_cap_reached")
    recipient = _recipient_for(db, campaign, contact)
    if recipient is not None and (
        recipient.status in _FINISHED_RECIPIENT_STATUSES
        or (
            recipient.message_id is not None
            and db.query(Message.id)
            .filter(
                Message.id == recipient.message_id,
                Message.status.in_(_DELIVERED_MESSAGE_STATUSES),
            )
            .first()
            is not None
        )
    ):
        return _refuse(db, campaign=campaign, contact=contact, reason="already_sent_in_campaign")
    return SendDecision(True)


def claim_pending_recipient(db: Session, recipient_id: UUID | str) -> UUID | None:
    """Atomically give one worker ownership of a pending campaign recipient."""
    return db.execute(
        update(WhatsappCampaignRecipient)
        .where(
            WhatsappCampaignRecipient.id == recipient_id,
            WhatsappCampaignRecipient.status == "pending",
        )
        .values(status="sending", error_code=None, error_message=None)
        .returning(WhatsappCampaignRecipient.id)
    ).scalar_one_or_none()


def send_outreach_message(
    db: Session,
    *,
    recipient_id: UUID | str,
    components: list[dict],
    access_token: str | None = None,
    client: WhatsappClient | None = None,
) -> OutreachSendResult:
    """Reserve under an account row lock, commit, then make the HTTP call."""
    recipient = db.get(WhatsappCampaignRecipient, recipient_id)
    if recipient is None:
        return OutreachSendResult(False, "recipient_not_found")
    campaign = db.get(WhatsappCampaign, recipient.campaign_id)
    if campaign is None:
        return OutreachSendResult(False, "campaign_not_found")
    account = db.execute(
        select(WhatsappAccount)
        .where(WhatsappAccount.id == campaign.whatsapp_account_id)
        .with_for_update()
    ).scalar_one()
    contact = db.get(WhatsappContact, recipient.contact_id)
    template = db.get(WhatsappTemplate, campaign.template_id)
    if contact is None or template is None:
        return OutreachSendResult(False, "outreach_record_missing")
    if claim_pending_recipient(db, recipient.id) is None:
        db.refresh(recipient)
        reason = (
            "already_sent_in_campaign"
            if recipient.status in {"sending", "sent", "delivered", "read"}
            else "recipient_already_claimed"
        )
        return OutreachSendResult(False, reason)
    db.refresh(recipient)

    decision = check_can_send(
        db, contact=contact, template=template, account=account, campaign=campaign
    )
    if not decision.allowed:
        db.commit()
        return OutreachSendResult(
            False, decision.reason_code, deferrable=decision.deferrable
        )

    message = Message(
        lead_id=contact.lead_id,
        whatsapp_campaign_id=campaign.id,
        whatsapp_template_id=template.id,
        direction="outbound",
        message_type="whatsapp_template",
        status="sending",
        retryable=False,
    )
    db.add(message)
    db.flush()
    recipient.message_id = message.id
    # Durability boundary: this commit must happen before send_template_message.
    db.commit()

    token = access_token or whatsapp_token_service.get_decrypted_token(db, account.id)
    if not token:
        message.status = "failed"
        message.error_code = "access_token_missing"
        recipient.status = "failed"
        recipient.error_code = "access_token_missing"
        db.commit()
        return OutreachSendResult(False, "access_token_missing", message.id)

    owns_client = client is None
    client = client or WhatsappClient()
    try:
        result: WhatsappMessageResult = client.send_template_message(
            token,
            account.phone_number_id,
            contact.wa_id,
            template.name,
            template.language,
            components,
        )
    finally:
        if owns_client:
            client.close()

    if result.success:
        message.status = "sent"
        message.provider_message_id = result.provider_message_id
        recipient.status = "sent"
        recipient.provider_message_id = result.provider_message_id
        recipient.sent_at = _utcnow()
        campaign.sent_count += 1
        reason = None
    else:
        api_error = bool(
            result.meta_error_code is not None
            or (
                isinstance(result.raw_response, dict)
                and isinstance(result.raw_response.get("error"), dict)
            )
        )
        unknown = not api_error
        reason = "outcome_unknown" if unknown else (result.error_code or "send_failed")
        message.status = "failed"
        message.error_code = reason
        message.error_message = result.error_message
        message.retryable = bool(result.retryable and not unknown)
        recipient.status = "failed"
        recipient.error_code = reason
        recipient.error_message = result.error_message
        campaign.failed_count += 1
    db.commit()
    return OutreachSendResult(
        result.success, reason, message.id, result.provider_message_id
    )


def reap_stale_sending_messages(
    db: Session, *, older_than_minutes: int = 15, now: datetime | None = None
) -> int:
    cutoff = (now or _utcnow()) - timedelta(minutes=older_than_minutes)
    messages = (
        db.query(Message)
        .filter(
            Message.whatsapp_campaign_id.isnot(None),
            Message.status == "sending",
            Message.created_at < cutoff,
        )
        .with_for_update(skip_locked=True)
        .all()
    )
    for message in messages:
        message.status = "failed"
        message.error_code = "outcome_unknown"
        message.error_message = "Send did not reach a recorded outcome"
        message.retryable = False
        recipient = (
            db.query(WhatsappCampaignRecipient)
            .filter(WhatsappCampaignRecipient.message_id == message.id)
            .first()
        )
        if recipient is not None:
            recipient.status = "failed"
            recipient.error_code = "outcome_unknown"
            recipient.error_message = message.error_message
            campaign = db.get(WhatsappCampaign, recipient.campaign_id)
            if campaign is not None:
                campaign.failed_count += 1
    db.flush()
    return len(messages)


def retryable_failed_recipients(
    db: Session, *, campaign_id: UUID | str
) -> list[WhatsappCampaignRecipient]:
    return (
        db.query(WhatsappCampaignRecipient)
        .filter(
            WhatsappCampaignRecipient.campaign_id == campaign_id,
            WhatsappCampaignRecipient.status == "failed",
            WhatsappCampaignRecipient.error_code != "outcome_unknown",
        )
        .all()
    )


def should_pause_campaign(db: Session, campaign: WhatsappCampaign) -> bool:
    db.flush()
    sample_size = max(1, settings.WHATSAPP_CAMPAIGN_BREAKER_WINDOW)
    rows = (
        db.query(WhatsappCampaignRecipient.status)
        .outerjoin(Message, Message.id == WhatsappCampaignRecipient.message_id)
        .filter(
            WhatsappCampaignRecipient.campaign_id == campaign.id,
            WhatsappCampaignRecipient.status.in_({"sent", "delivered", "read", "failed"}),
        )
        .order_by(
            func.coalesce(WhatsappCampaignRecipient.sent_at, Message.created_at)
            .desc()
            .nullslast()
        )
        .limit(sample_size)
        .all()
    )
    if len(rows) < sample_size:
        return False
    failure_share = sum(status == "failed" for (status,) in rows) / len(rows)
    if failure_share > settings.WHATSAPP_CAMPAIGN_BREAKER_FAILURE_THRESHOLD:
        campaign.status = "paused"
        db.flush()
        return True
    return False
