"""State changes for confirmed WhatsApp webhook payloads."""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.meta.whatsapp_ids import mask_wa_id, normalize_wa_id
from app.integrations.meta.whatsapp_webhooks import (
    ParsedWhatsappMessageEvent,
    ParsedWhatsappPhoneQualityEvent,
    ParsedWhatsappStatusEvent,
    ParsedWhatsappTemplateStatusEvent,
    whatsapp_phone_quality_event_key,
    whatsapp_status_event_key,
    whatsapp_template_status_event_key,
)
from app.models.lead import Lead
from app.models.message import Message
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.services.whatsapp_consent_service import apply_keyword_consent, record_consent_event
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.services.processed_event_service import check_and_mark_processed
from app.utils.db import is_unique_violation


logger = logging.getLogger(__name__)

DEFAULT_OPT_OUT_KEYWORDS = frozenset(
    {"stop", "unsubscribe", "توقف", "إلغاء الاشتراك", "الغاء الاشتراك"}
)
DEFAULT_OPT_IN_KEYWORDS = frozenset({"start", "ابدأ"})
_MAX_KEYWORD_LENGTH = 64
_TEMPLATE_STATUSES = frozenset(
    {"draft", "pending", "approved", "rejected", "paused", "disabled"}
)
_RETRYABLE_META_CODES = frozenset({"130429", "131048"})
_DELIVERY_STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}


@dataclass(frozen=True)
class InboundWhatsappResult:
    account: WhatsappAccount
    lead: Lead
    contact: WhatsappContact
    consent_action: str | None


def whatsapp_event_time(value: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(float(value or ""), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def normalize_keyword(value: str) -> str | None:
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized or len(normalized) > _MAX_KEYWORD_LENGTH:
        return None
    return normalized


def _keyword_set(override: list | None, defaults: frozenset[str]) -> set[str]:
    values = override if override is not None else defaults
    return {
        normalized
        for value in values
        if isinstance(value, str) and (normalized := normalize_keyword(value)) is not None
    }


def _message_event_key(event: ParsedWhatsappMessageEvent, wa_id: str) -> str:
    if event.message_id:
        return f"whatsapp_message:{event.message_id}"
    raw = "|".join((wa_id, event.timestamp or "", event.message_type, event.text))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"whatsapp_message_fallback:{digest}"


def _find_lead(db: Session, account: WhatsappAccount, wa_id: str) -> Lead | None:
    return (
        db.query(Lead)
        .filter(
            Lead.workspace_id == account.workspace_id,
            Lead.whatsapp_account_id == account.id,
            func.regexp_replace(Lead.ig_user_id, r"\D", "", "g") == wa_id,
        )
        .order_by(Lead.created_at.asc(), Lead.id.asc())
        .first()
    )


def _get_or_create_lead(
    db: Session,
    account: WhatsappAccount,
    event: ParsedWhatsappMessageEvent,
    wa_id: str,
    event_time: datetime,
) -> tuple[Lead | None, bool]:
    lead = _find_lead(db, account, wa_id)
    if lead is not None:
        if lead.last_seen_at is None or event_time > lead.last_seen_at:
            lead.last_seen_at = event_time
        if event.sender_profile_name:
            lead.ig_username = event.sender_profile_name
        return lead, False

    lead = Lead(
        workspace_id=account.workspace_id,
        platform="whatsapp",
        whatsapp_account_id=account.id,
        instagram_account_id=None,
        ig_user_id=wa_id,
        ig_username=event.sender_profile_name,
        last_seen_at=event_time,
        lead_source="cold_dm",
        status="new",
    )
    try:
        with db.begin_nested():
            db.add(lead)
            db.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc):
            raise
        return _find_lead(db, account, wa_id), False
    return lead, True


def _get_or_create_contact(
    db: Session,
    account: WhatsappAccount,
    lead: Lead,
    event: ParsedWhatsappMessageEvent,
    wa_id: str,
    event_time: datetime,
) -> WhatsappContact | None:
    contact = (
        db.query(WhatsappContact)
        .filter(
            WhatsappContact.whatsapp_account_id == account.id,
            WhatsappContact.wa_id == wa_id,
        )
        .first()
    )
    if contact is None:
        contact = WhatsappContact(
            workspace_id=account.workspace_id,
            whatsapp_account_id=account.id,
            wa_id=wa_id,
            display_name=event.sender_profile_name,
            lead_id=lead.id,
            marketing_consent="unknown",
            last_inbound_at=event_time,
        )
        try:
            with db.begin_nested():
                db.add(contact)
                db.flush()
        except IntegrityError as exc:
            if not is_unique_violation(exc):
                raise
            contact = (
                db.query(WhatsappContact)
                .filter(
                    WhatsappContact.whatsapp_account_id == account.id,
                    WhatsappContact.wa_id == wa_id,
                )
                .first()
            )
    if contact is None:
        return None
    contact.lead_id = contact.lead_id or lead.id
    if event.sender_profile_name:
        contact.display_name = event.sender_profile_name
    if contact.last_inbound_at is None or event_time > contact.last_inbound_at:
        contact.last_inbound_at = event_time
    return contact


def _apply_consent(
    db: Session,
    *,
    account: WhatsappAccount,
    contact: WhatsappContact,
    event: ParsedWhatsappMessageEvent,
    event_time: datetime,
) -> str | None:
    keyword = normalize_keyword(event.text)
    opt_out = _keyword_set(account.opt_out_keywords, DEFAULT_OPT_OUT_KEYWORDS)
    has_configured_opt_in = account.opt_in_keywords is not None
    opt_in = _keyword_set(account.opt_in_keywords, DEFAULT_OPT_IN_KEYWORDS)

    if event.referral is not None:
        expires_at = event_time + timedelta(hours=72)
        if (
            contact.free_entry_point_expires_at is None
            or expires_at > contact.free_entry_point_expires_at
        ):
            contact.free_entry_point_expires_at = expires_at
        record_consent_event(
            db,
            contact,
            event_type="import",
            source="click_to_whatsapp",
            evidence={
                "message_id": event.message_id,
                "source_id": event.referral.data.get("source_id"),
                "source_url": event.referral.data.get("source_url"),
                "temporary_window_only": True,
            },
        )

    action = apply_keyword_consent(
        db, contact=contact, keyword=keyword, opt_in=opt_in, opt_out=opt_out,
        configured_opt_in=has_configured_opt_in, event_time=event_time,
        message_id=event.message_id,
    )
    if action is not None:
        return action

    if event.referral is not None:
        return "ctwa_referral"
    return None


def process_inbound_whatsapp_event(
    db: Session, event: ParsedWhatsappMessageEvent
) -> InboundWhatsappResult | None:
    wa_id = normalize_wa_id(event.sender_wa_id)
    masked_wa_id = mask_wa_id(event.sender_wa_id)
    if wa_id is None:
        logger.warning(
            "Inbound WhatsApp message skipped: invalid WA ID",
            extra={"sender_wa_id": masked_wa_id},
        )
        return None

    if not check_and_mark_processed(
        db,
        event_key=_message_event_key(event, wa_id),
        event_type="whatsapp_message",
        metadata={"sender_wa_id": masked_wa_id, "message_type": event.message_type},
    ):
        logger.debug(
            "Inbound WhatsApp message skipped: duplicate webhook delivery",
            extra={"sender_wa_id": masked_wa_id},
        )
        return None

    account = (
        db.query(WhatsappAccount)
        .filter(WhatsappAccount.phone_number_id == event.phone_number_id)
        .first()
    )
    if account is None:
        logger.warning(
            "Inbound WhatsApp message skipped: account not found",
            extra={"phone_number_id": event.phone_number_id},
        )
        db.commit()
        return None

    event_time = whatsapp_event_time(event.timestamp)
    lead, created = _get_or_create_lead(db, account, event, wa_id, event_time)
    if lead is None:
        logger.error(
            "Inbound WhatsApp identity skipped after concurrent lead creation",
            extra={"sender_wa_id": masked_wa_id},
        )
        db.commit()
        return None
    contact = _get_or_create_contact(db, account, lead, event, wa_id, event_time)
    if contact is None:
        logger.error(
            "Inbound WhatsApp identity skipped after concurrent contact creation",
            extra={"sender_wa_id": masked_wa_id},
        )
        db.commit()
        return None

    consent_action = _apply_consent(
        db,
        account=account,
        contact=contact,
        event=event,
        event_time=event_time,
    )
    db.commit()
    db.refresh(lead)
    db.refresh(contact)
    if created:
        logger.info(
            "WhatsApp lead created",
            extra={"lead_id": str(lead.id), "sender_wa_id": masked_wa_id},
        )
    return InboundWhatsappResult(account, lead, contact, consent_action)


def _stored_status_time(
    message: Message, recipient: WhatsappCampaignRecipient | None
) -> datetime | None:
    values = [message.delivered_at, message.read_at]
    if recipient is not None:
        values.append(recipient.sent_at)
    return max((value for value in values if value is not None), default=None)


def _status_error(event: ParsedWhatsappStatusEvent) -> tuple[str | None, str | None]:
    if not event.errors:
        return None, None
    error = event.errors[0]
    code = str(error["code"]) if error.get("code") is not None else None
    error_data = error.get("error_data")
    details = error_data.get("details") if isinstance(error_data, dict) else None
    message = details or error.get("message") or error.get("title")
    return code, str(message) if message is not None else None


def _increment(campaign: WhatsappCampaign | None, field: str) -> None:
    if campaign is not None:
        setattr(campaign, field, (getattr(campaign, field) or 0) + 1)


def process_whatsapp_status_events(
    db: Session, events: list[ParsedWhatsappStatusEvent]
) -> None:
    for event in events:
        if not check_and_mark_processed(
            db,
            event_key=whatsapp_status_event_key(event),
            event_type="whatsapp_message_status",
            metadata={
                "provider_message_id": event.provider_message_id,
                "status": event.status,
                "recipient_wa_id": mask_wa_id(event.recipient_wa_id),
            },
        ):
            continue
        message = (
            db.query(Message)
            .filter(Message.provider_message_id == event.provider_message_id)
            .first()
        )
        if message is None:
            logger.info(
                "WhatsApp status ignored: message not found",
                extra={
                    "provider_message_id": event.provider_message_id,
                    "recipient_wa_id": mask_wa_id(event.recipient_wa_id),
                },
            )
            db.commit()
            continue

        recipient = (
            db.query(WhatsappCampaignRecipient)
            .filter(
                or_(
                    WhatsappCampaignRecipient.provider_message_id
                    == event.provider_message_id,
                    WhatsappCampaignRecipient.message_id == message.id,
                )
            )
            .first()
        )
        event_time = whatsapp_event_time(event.timestamp)
        stored_time = _stored_status_time(message, recipient)
        if event.status in _DELIVERY_STATUS_RANK:
            current_rank = max(
                _DELIVERY_STATUS_RANK.get(message.status, 0),
                _DELIVERY_STATUS_RANK.get(
                    recipient.status if recipient is not None else "", 0
                ),
            )
            if (
                (stored_time is not None and event_time < stored_time)
                or _DELIVERY_STATUS_RANK[event.status] < current_rank
            ):
                db.commit()
                continue

        campaign = (
            db.query(WhatsappCampaign)
            .filter(WhatsappCampaign.id == recipient.campaign_id)
            .first()
            if recipient is not None
            else None
        )
        old_recipient_status = recipient.status if recipient is not None else None
        message.status = event.status

        if event.status == "sent":
            if recipient is not None and old_recipient_status in {"queued", "pending", "sending"}:
                recipient.status = "sent"
                recipient.sent_at = event_time
                _increment(campaign, "sent_count")
        elif event.status == "delivered":
            message.delivered_at = event_time
            if recipient is not None and old_recipient_status != "read":
                if old_recipient_status in {"queued", "pending", "sending"}:
                    _increment(campaign, "sent_count")
                if old_recipient_status not in {"delivered", "read"}:
                    _increment(campaign, "delivered_count")
                recipient.status = "delivered"
                recipient.sent_at = recipient.sent_at or event_time
        elif event.status == "read":
            message.delivered_at = message.delivered_at or event_time
            message.read_at = event_time
            if recipient is not None and old_recipient_status != "read":
                if old_recipient_status in {"queued", "pending", "sending"}:
                    _increment(campaign, "sent_count")
                if old_recipient_status not in {"delivered", "read"}:
                    _increment(campaign, "delivered_count")
                _increment(campaign, "read_count")
                recipient.status = "read"
                recipient.sent_at = recipient.sent_at or event_time
        elif event.status in {"failed", "deleted"}:
            code, error_message = _status_error(event)
            message.error_code = code or ("deleted" if event.status == "deleted" else None)
            message.error_message = error_message
            message.retryable = code in _RETRYABLE_META_CODES
            if recipient is not None and old_recipient_status != "failed":
                recipient.status = "failed"
                recipient.error_code = message.error_code
                recipient.error_message = error_message
                _increment(campaign, "failed_count")
        db.commit()


def process_whatsapp_template_status_events(
    db: Session, events: list[ParsedWhatsappTemplateStatusEvent]
) -> None:
    for event in events:
        if not check_and_mark_processed(
            db,
            event_key=whatsapp_template_status_event_key(event),
            event_type="whatsapp_template_status",
            metadata={"template_id": event.message_template_id, "event": event.event},
        ):
            continue
        query = db.query(WhatsappTemplate)
        if event.message_template_id:
            template = query.filter(
                WhatsappTemplate.meta_template_id == event.message_template_id
            ).first()
        else:
            query = query.join(
                WhatsappAccount,
                WhatsappAccount.id == WhatsappTemplate.whatsapp_account_id,
            ).filter(
                WhatsappTemplate.name == event.message_template_name,
                WhatsappAccount.whatsapp_business_account_id
                == event.whatsapp_business_account_id,
            )
            if event.message_template_language:
                query = query.filter(
                    WhatsappTemplate.language == event.message_template_language
                )
            template = query.first()
        status = event.event.casefold()
        if template is not None and status in _TEMPLATE_STATUSES:
            template.status = status
            template.rejection_reason = event.reason
            template.last_synced_at = whatsapp_event_time(event.timestamp)
        db.commit()


def process_whatsapp_phone_quality_events(
    db: Session, events: list[ParsedWhatsappPhoneQualityEvent]
) -> None:
    for event in events:
        if not check_and_mark_processed(
            db,
            event_key=whatsapp_phone_quality_event_key(event),
            event_type="whatsapp_phone_quality",
            metadata={
                "display_phone_number": mask_wa_id(event.display_phone_number),
                "event": event.event,
            },
        ):
            continue
        normalized = normalize_wa_id(event.display_phone_number)
        query = db.query(WhatsappAccount)
        if event.whatsapp_business_account_id:
            query = query.filter(
                WhatsappAccount.whatsapp_business_account_id
                == event.whatsapp_business_account_id
            )
        if normalized:
            query = query.filter(
                func.regexp_replace(
                    func.coalesce(WhatsappAccount.display_phone_number, ""),
                    r"\D",
                    "",
                    "g",
                )
                == normalized
            )
        else:
            query = query.filter(False)
        account = query.first()
        if account is not None:
            if event.current_limit is not None:
                account.messaging_limit_tier = event.current_limit
            if event.event.upper() in {"FLAGGED", "DOWNGRADE"}:
                if not account.outreach_paused:
                    account.outreach_paused_at = datetime.now(timezone.utc)
                account.outreach_paused = True
                account.outreach_paused_reason = "phone_number_flagged"
        db.commit()
