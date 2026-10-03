from __future__ import annotations

import json
import logging
import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.meta.whatsapp_management_client import WhatsappManagementClient
from app.models.message import Message
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.services.outreach_service import (
    refuse_campaign_recipient,
    reap_stale_sending_messages,
    send_outreach_message,
    should_pause_campaign,
)
from app.services.whatsapp_consent_service import is_marketing_allowed
from app.services.whatsapp_template_service import (
    render_template_components,
    sync_templates,
    template_placeholder_indexes,
    validate_for_campaign,
)
from app.services.whatsapp_token_service import get_decrypted_token
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)

_redis_client: Redis | None = None
_NEVER_RETRY_META_CODES = frozenset({131048, 131049})
_ACCOUNT_DEFERRALS = frozenset(
    {
        "account_disconnected",
        "daily_cap_reached",
        "health_stale",
        "health_unknown",
        "outreach_paused",
        "quality_red",
    }
)
_BUCKET_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local capacity = tonumber(ARGV[1])
local refill_per_ms = capacity / 60000
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_ms')
local tokens = tonumber(values[1]) or capacity
local updated_ms = tonumber(values[2]) or now_ms
tokens = math.min(capacity, tokens + math.max(0, now_ms - updated_ms) * refill_per_ms)
local allowed = 0
local wait_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait_ms = math.ceil((1 - tokens) / refill_per_ms)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_ms', now_ms)
redis.call('PEXPIRE', KEYS[1], 120000)
return {allowed, wait_ms}
"""


class VariableMappingError(ValueError):
    pass


@dataclass(frozen=True)
class BucketResult:
    allowed: bool
    retry_after_seconds: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _bucket_key(account_id: UUID | str) -> str:
    return f"whatsapp:outreach:bucket:{account_id}"


def _account_defer_key(account_id: UUID | str) -> str:
    return f"whatsapp:outreach:defer:account:{account_id}"


def _campaign_defer_key(campaign_id: UUID | str) -> str:
    return f"whatsapp:outreach:defer:campaign:{campaign_id}"


def _dispatch_heartbeat_key(campaign_id: UUID | str) -> str:
    return f"whatsapp:outreach:dispatch:{campaign_id}"


def _watchdog_lock_key(campaign_id: UUID | str) -> str:
    return f"whatsapp:outreach:watchdog:{campaign_id}"


def _deferred_dispatch_key(campaign_id: UUID | str) -> str:
    return f"whatsapp:outreach:deferred-dispatch:{campaign_id}"


def retryable_meta_codes() -> set[int]:
    configured: set[int] = set()
    for value in settings.WHATSAPP_RETRYABLE_META_CODES.split(","):
        value = value.strip()
        if value.isdigit():
            configured.add(int(value))
    return configured - _NEVER_RETRY_META_CODES


def dispatch_countdowns(throttle_per_minute: int) -> list[float]:
    """Return one bounded broker countdown per recipient in a dispatch batch."""
    visibility = max(1, settings.WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS)
    window = max(0, settings.WHATSAPP_DISPATCH_MAX_BATCH_WINDOW_SECONDS)
    if window >= visibility / 2:
        raise ValueError("whatsapp_dispatch_window_must_be_under_half_visibility_timeout")
    spacing = 60.0 / max(1, throttle_per_minute)
    window_limited_count = math.floor(window / spacing) + 1
    count = max(1, min(settings.WHATSAPP_DISPATCH_BATCH_SIZE, window_limited_count))
    return [round(index * spacing, 3) for index in range(count)]


def acquire_account_token(account_id: UUID | str, throttle_per_minute: int) -> BucketResult:
    allowed, wait_ms = _redis().eval(
        _BUCKET_SCRIPT,
        1,
        _bucket_key(account_id),
        max(1, throttle_per_minute),
    )
    return BucketResult(bool(int(allowed)), max(1, math.ceil(int(wait_ms) / 1000)) if wait_ms else 0)


def _bounded_ttl(seconds: int) -> int:
    return max(1, min(seconds, settings.WHATSAPP_DEFER_GATE_MAX_TTL_SECONDS))


def _set_defer_gate(*, account_id=None, campaign_id=None, reason: str, seconds: int) -> None:
    key = _account_defer_key(account_id) if account_id is not None else _campaign_defer_key(campaign_id)
    _redis().setex(key, _bounded_ttl(seconds), reason)


def clear_whatsapp_defer_gate(*, account_id=None, campaign_id=None) -> None:
    """Clear bounded gates after health recovery or an explicit future resume."""
    keys = []
    if account_id is not None:
        keys.append(_account_defer_key(account_id))
    if campaign_id is not None:
        keys.append(_campaign_defer_key(campaign_id))
    if keys:
        _redis().delete(*keys)


def _defer_ttl(account_id, campaign_id) -> int:
    ttls = [
        int(_redis().ttl(_account_defer_key(account_id))),
        int(_redis().ttl(_campaign_defer_key(campaign_id))),
    ]
    return max([ttl for ttl in ttls if ttl > 0], default=0)


def _mark_dispatch(campaign_id, seconds: int | None = None) -> None:
    ttl = max(
        settings.WHATSAPP_DISPATCH_WATCHDOG_SECONDS,
        (seconds or 0) + settings.WHATSAPP_DISPATCH_WATCHDOG_SECONDS,
    )
    _redis().setex(_dispatch_heartbeat_key(campaign_id), ttl, "1")


def _has_recent_dispatch(campaign_id) -> bool:
    return bool(_redis().get(_dispatch_heartbeat_key(campaign_id)))


def _mapping_by_index(mapping: dict) -> dict[int, object]:
    try:
        return {int(key): value for key, value in mapping.items()}
    except (AttributeError, TypeError, ValueError) as exc:
        raise VariableMappingError("variable_mapping_must_be_an_object_with_numeric_keys") from exc


def validate_campaign_variable_mapping(
    campaign: WhatsappCampaign,
    template: WhatsappTemplate,
) -> None:
    expected = template_placeholder_indexes(template)
    mapping = _mapping_by_index(campaign.variable_mapping or {})
    if set(mapping) != expected:
        raise VariableMappingError(
            f"variable_mapping_placeholders_mismatch: expected={sorted(expected)} actual={sorted(mapping)}"
        )
    for index, specification in mapping.items():
        if not isinstance(specification, dict):
            value = specification
        elif specification.get("source") == "literal":
            value = specification.get("value")
        elif specification.get("source") == "contact.display_name":
            continue
        else:
            raise VariableMappingError(f"variable_{index}_source_unsupported")
        if value is None or (isinstance(value, str) and not value.strip()):
            raise VariableMappingError(f"variable_{index}_unresolved")


def resolve_campaign_variables(
    campaign: WhatsappCampaign,
    template: WhatsappTemplate,
    contact: WhatsappContact,
) -> dict[int, object]:
    validate_campaign_variable_mapping(campaign, template)
    mapping = _mapping_by_index(campaign.variable_mapping or {})
    resolved: dict[int, object] = {}
    for index, specification in mapping.items():
        if not isinstance(specification, dict):
            value = specification
        else:
            source = specification.get("source")
            if source == "literal":
                value = specification.get("value")
            elif source == "contact.display_name":
                value = contact.display_name or specification.get("fallback")
            else:
                raise VariableMappingError(f"variable_{index}_source_unsupported")
        if value is None or (isinstance(value, str) and not value.strip()):
            raise VariableMappingError(f"variable_{index}_unresolved")
        resolved[index] = value
    return resolved


def _daily_cap_retry_seconds(db, account_id) -> int:
    cutoff = _utcnow() - timedelta(hours=24)
    oldest = (
        db.query(func.min(Message.created_at))
        .join(WhatsappCampaign, WhatsappCampaign.id == Message.whatsapp_campaign_id)
        .filter(
            WhatsappCampaign.whatsapp_account_id == account_id,
            Message.created_at >= cutoff,
            or_(
                Message.status.in_({"sending", "sent", "delivered", "read"}),
                Message.error_code == "outcome_unknown",
            ),
        )
        .scalar()
    )
    if oldest is None:
        return settings.WHATSAPP_DEFER_GATE_TTL_SECONDS
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    return _bounded_ttl(max(1, math.ceil((oldest + timedelta(hours=24) - _utcnow()).total_seconds()) + 1))


def _schedule_dispatch(campaign_id, countdown: int) -> None:
    dispatch_whatsapp_campaign.apply_async(args=[str(campaign_id)], countdown=max(1, countdown))


def _schedule_deferred_dispatch_once(campaign_id, countdown: int) -> bool:
    """Coalesce one batch's deferrals into a single idempotent redispatch."""
    try:
        acquired = _redis().set(
            _deferred_dispatch_key(campaign_id),
            "1",
            nx=True,
            ex=60,
        )
    except RedisError:
        acquired = True
    if acquired:
        _schedule_dispatch(campaign_id, countdown)
    return bool(acquired)


@celery_app.task(name="app.workers.whatsapp_tasks.start_whatsapp_campaign")
def start_whatsapp_campaign(campaign_id: str) -> dict:
    db = SessionLocal()
    try:
        campaign = db.execute(
            select(WhatsappCampaign)
            .where(WhatsappCampaign.id == campaign_id)
            .with_for_update()
        ).scalar_one_or_none()
        if campaign is None:
            raise ValueError("whatsapp_campaign_not_found")
        if campaign.status == "running":
            return {"campaign_id": str(campaign.id), "status": campaign.status, "changed": False}
        if campaign.status not in {"draft", "scheduled"}:
            raise ValueError(f"whatsapp_campaign_cannot_start_from_{campaign.status}")
        now = _utcnow()
        if campaign.status == "scheduled" and campaign.scheduled_at and campaign.scheduled_at > now:
            delay = max(1, math.ceil((campaign.scheduled_at - now).total_seconds()))
            start_whatsapp_campaign.apply_async(args=[str(campaign.id)], countdown=delay)
            return {"campaign_id": str(campaign.id), "status": "scheduled", "changed": False}

        account = db.get(WhatsappAccount, campaign.whatsapp_account_id)
        template = db.get(WhatsappTemplate, campaign.template_id)
        if account is None or template is None:
            raise ValueError("whatsapp_campaign_account_or_template_missing")
        validate_for_campaign(template)
        try:
            validate_campaign_variable_mapping(campaign, template)
        except VariableMappingError as exc:
            raise ValueError(f"whatsapp_campaign_variable_mapping_invalid:{exc}") from exc
        contacts = (
            db.query(WhatsappContact)
            .filter(WhatsappContact.whatsapp_account_id == account.id)
            .order_by(WhatsappContact.id)
            .all()
        )
        audience = [
            contact
            for contact in contacts
            if contact.marketing_consent != "opted_out" and is_marketing_allowed(contact, account, now=now)
        ]
        existing_recipients = {
            recipient.contact_id: recipient
            for recipient in db.query(WhatsappCampaignRecipient)
            .filter(WhatsappCampaignRecipient.campaign_id == campaign.id)
            .all()
        }
        for contact in audience:
            status = "pending"
            error_code = None
            try:
                resolve_campaign_variables(campaign, template, contact)
            except VariableMappingError:
                status = "skipped_not_eligible"
                error_code = "variable_unresolved"
            recipient = existing_recipients.get(contact.id)
            if recipient is None:
                recipient = WhatsappCampaignRecipient(
                    campaign_id=campaign.id,
                    contact_id=contact.id,
                    status=status,
                    error_code=error_code,
                )
                db.add(recipient)
            elif recipient.status in {"pending", "skipped_not_eligible"}:
                recipient.status = status
                recipient.error_code = error_code
                recipient.error_message = None
        db.flush()
        campaign.total_recipients = db.query(WhatsappCampaignRecipient).filter_by(campaign_id=campaign.id).count()
        campaign.skipped_count = (
            db.query(WhatsappCampaignRecipient)
            .filter(
                WhatsappCampaignRecipient.campaign_id == campaign.id,
                WhatsappCampaignRecipient.status == "skipped_not_eligible",
            )
            .count()
        )
        campaign.status = "running"
        campaign.completed_at = None
        db.commit()
        dispatch_whatsapp_campaign.delay(str(campaign.id))
        return {"campaign_id": str(campaign.id), "status": "running", "changed": True}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.whatsapp_tasks.resume_whatsapp_campaign_dispatch")
def resume_whatsapp_campaign_dispatch(campaign_id: str) -> dict:
    """Phase 5 resume hook: clear bounded gates after its audited DB transition."""
    db = SessionLocal()
    try:
        campaign = db.get(WhatsappCampaign, campaign_id)
        if campaign is None or campaign.status != "running":
            return {"resumed": False}
        try:
            clear_whatsapp_defer_gate(
                account_id=campaign.whatsapp_account_id,
                campaign_id=campaign.id,
            )
        except RedisError:
            pass
        dispatch_whatsapp_campaign.delay(str(campaign.id))
        return {"resumed": True}
    finally:
        db.close()


@celery_app.task(name="app.workers.whatsapp_tasks.dispatch_whatsapp_campaign")
def dispatch_whatsapp_campaign(campaign_id: str) -> dict:
    db = SessionLocal()
    try:
        campaign = db.get(WhatsappCampaign, campaign_id)
        if campaign is None or campaign.status != "running":
            return {"dispatched": 0, "rescheduled": False}
        account = db.get(WhatsappAccount, campaign.whatsapp_account_id)
        if account is None:
            return {"dispatched": 0, "rescheduled": False}
        try:
            gate_ttl = _defer_ttl(account.id, campaign.id)
        except RedisError:
            gate_ttl = settings.WHATSAPP_DISPATCH_BACKOFF_SECONDS
        if not settings.WHATSAPP_OUTREACH_ENABLED or account.outreach_paused:
            gate_ttl = max(gate_ttl, settings.WHATSAPP_DISPATCH_BACKOFF_SECONDS)
            try:
                _set_defer_gate(
                    account_id=account.id,
                    reason="outreach_paused" if account.outreach_paused else "outreach_disabled",
                    seconds=gate_ttl,
                )
            except RedisError:
                pass
        if gate_ttl:
            _schedule_dispatch(campaign.id, gate_ttl)
            try:
                _mark_dispatch(campaign.id, gate_ttl)
            except RedisError:
                pass
            return {"dispatched": 0, "rescheduled": True, "countdown": gate_ttl}

        countdowns = dispatch_countdowns(campaign.throttle_per_minute)
        recipient_ids = [
            row[0]
            for row in db.query(WhatsappCampaignRecipient.id)
            .filter(
                WhatsappCampaignRecipient.campaign_id == campaign.id,
                WhatsappCampaignRecipient.status == "pending",
            )
            .order_by(WhatsappCampaignRecipient.id)
            .limit(len(countdowns))
            .all()
        ]
        for recipient_id, countdown in zip(recipient_ids, countdowns):
            send_whatsapp_campaign_message.apply_async(
                args=[str(recipient_id)], countdown=countdown
            )
        pending = db.query(WhatsappCampaignRecipient.id).filter(
            WhatsappCampaignRecipient.campaign_id == campaign.id,
            WhatsappCampaignRecipient.status == "pending",
        ).first()
        rescheduled = pending is not None
        next_delay = max(
            settings.WHATSAPP_DISPATCH_TICK_SECONDS,
            math.ceil(countdowns[len(recipient_ids) - 1]) + 1 if recipient_ids else 1,
        )
        if rescheduled:
            _schedule_dispatch(campaign.id, next_delay)
        try:
            _mark_dispatch(campaign.id, next_delay if rescheduled else None)
        except RedisError:
            pass
        return {"dispatched": len(recipient_ids), "rescheduled": rescheduled, "countdown": next_delay}
    finally:
        db.close()


def _retry_delay(attempt_number: int) -> int:
    base = max(1, settings.WHATSAPP_SEND_RETRY_BASE_SECONDS)
    maximum = max(base, settings.WHATSAPP_SEND_RETRY_MAX_SECONDS)
    return min(maximum, (base * (2 ** max(0, attempt_number - 1))) + random.randint(0, base))


@celery_app.task(bind=True, name="app.workers.whatsapp_tasks.send_whatsapp_campaign_message")
def send_whatsapp_campaign_message(self, recipient_id: str) -> dict:
    db = SessionLocal()
    try:
        recipient = db.get(WhatsappCampaignRecipient, recipient_id)
        if recipient is None or recipient.status != "pending":
            return {"sent": False, "reason": "recipient_not_pending"}
        campaign = db.get(WhatsappCampaign, recipient.campaign_id)
        if campaign is None:
            return {"sent": False, "reason": "campaign_not_found"}
        account = db.get(WhatsappAccount, campaign.whatsapp_account_id)
        contact = db.get(WhatsappContact, recipient.contact_id)
        template = db.get(WhatsappTemplate, campaign.template_id)
        if account is None or contact is None or template is None:
            return {"sent": False, "reason": "outreach_record_missing"}

        try:
            gate_ttl = _defer_ttl(account.id, campaign.id)
        except RedisError:
            gate_ttl = settings.WHATSAPP_DISPATCH_BACKOFF_SECONDS
        if gate_ttl:
            send_whatsapp_campaign_message.apply_async(args=[recipient_id], countdown=gate_ttl)
            return {"sent": False, "reason": "deferred", "countdown": gate_ttl}

        try:
            variables = resolve_campaign_variables(campaign, template, contact)
            components = render_template_components(template, variables)
        except Exception as exc:
            refuse_campaign_recipient(
                db,
                campaign=campaign,
                contact=contact,
                reason="variable_unresolved",
            )
            db.commit()
            logger.warning(
                "WhatsApp campaign variables unresolved",
                extra={"campaign_id": str(campaign.id), "recipient_id": str(recipient.id), "error": str(exc)},
            )
            return {"sent": False, "reason": "variable_unresolved"}

        try:
            bucket = acquire_account_token(account.id, campaign.throttle_per_minute)
        except RedisError:
            send_whatsapp_campaign_message.apply_async(
                args=[recipient_id], countdown=settings.WHATSAPP_DISPATCH_BACKOFF_SECONDS
            )
            return {"sent": False, "reason": "redis_unavailable"}
        if not bucket.allowed:
            send_whatsapp_campaign_message.apply_async(
                args=[recipient_id], countdown=bucket.retry_after_seconds
            )
            return {"sent": False, "reason": "throttled", "countdown": bucket.retry_after_seconds}

        result = send_outreach_message(db, recipient_id=recipient.id, components=components)
        db.expire_all()
        campaign = db.get(WhatsappCampaign, campaign.id)
        recipient = db.get(WhatsappCampaignRecipient, recipient.id)
        if campaign is not None:
            should_pause_campaign(db, campaign)

        if result.deferrable and campaign is not None:
            seconds = (
                _daily_cap_retry_seconds(db, account.id)
                if result.reason_code == "daily_cap_reached"
                else settings.WHATSAPP_DEFER_GATE_TTL_SECONDS
            )
            try:
                if result.reason_code in _ACCOUNT_DEFERRALS:
                    _set_defer_gate(account_id=account.id, reason=result.reason_code or "deferred", seconds=seconds)
                else:
                    _set_defer_gate(campaign_id=campaign.id, reason=result.reason_code or "deferred", seconds=seconds)
            except RedisError:
                pass
            db.commit()
            _schedule_deferred_dispatch_once(campaign.id, seconds)
            return {"sent": False, "reason": result.reason_code, "deferred": True}

        if result.meta_error_code == 131048 and campaign is not None:
            try:
                _set_defer_gate(
                    account_id=account.id,
                    reason="131048",
                    seconds=settings.WHATSAPP_DEFER_GATE_TTL_SECONDS,
                )
            except RedisError:
                pass

        attempt_number = int(getattr(self.request, "retries", 0)) + 1
        can_retry = (
            not result.sent
            and result.retryable
            and result.reason_code != "outcome_unknown"
            and result.meta_error_code not in _NEVER_RETRY_META_CODES
            and result.meta_error_code in retryable_meta_codes()
            and attempt_number < settings.WHATSAPP_SEND_MAX_ATTEMPTS
            and recipient is not None
            and recipient.status != "sent"
        )
        if can_retry:
            recipient.status = "pending"
            recipient.error_code = None
            recipient.error_message = None
            db.commit()
            raise self.retry(
                countdown=_retry_delay(attempt_number),
                max_retries=max(0, settings.WHATSAPP_SEND_MAX_ATTEMPTS - 1),
            )
        db.commit()
        return {"sent": result.sent, "reason": result.reason_code}
    finally:
        db.close()


def _tier_rank(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.upper()
    if "UNLIMITED" in normalized:
        return 10**12
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KM]?)", normalized.replace("_", ""))
    if not match:
        return None
    multiplier = {"": 1, "K": 1000, "M": 1_000_000}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


@celery_app.task(name="app.workers.whatsapp_tasks.poll_whatsapp_account_health")
def poll_whatsapp_account_health() -> dict:
    listing = SessionLocal()
    try:
        account_ids = [
            row[0]
            for row in listing.query(WhatsappAccount.id)
            .filter(WhatsappAccount.status == "connected")
            .all()
        ]
    finally:
        listing.close()
    succeeded = paused = 0
    for account_id in account_ids:
        db = SessionLocal()
        client = None
        try:
            account = db.get(WhatsappAccount, account_id)
            if account is None or account.status != "connected":
                continue
            token = get_decrypted_token(db, account.id)
            if not token:
                continue
            client = WhatsappManagementClient()
            result = client.get_phone_number_health(
                token, account.whatsapp_business_account_id or ""
            )
            if not result.success:
                continue
            row = next(
                (item for item in (result.data or []) if item.id == account.phone_number_id),
                None,
            )
            if row is None:
                continue
            old_rank = _tier_rank(account.messaging_limit_tier)
            new_rank = _tier_rank(row.messaging_limit_tier)
            tier_dropped = old_rank is not None and new_rank is not None and new_rank < old_rank
            quality = row.quality_rating.upper() if row.quality_rating else account.quality_rating
            if row.quality_rating is not None:
                account.quality_rating = quality
            if row.messaging_limit_tier is not None:
                account.messaging_limit_tier = row.messaging_limit_tier
            account.health_checked_at = _utcnow()
            if quality == "RED" or tier_dropped:
                account.outreach_paused = True
                account.outreach_paused_reason = (
                    "quality_red" if quality == "RED" else "messaging_limit_tier_dropped"
                )
                db.query(WhatsappCampaign).filter(
                    WhatsappCampaign.whatsapp_account_id == account.id,
                    WhatsappCampaign.status == "running",
                ).update({WhatsappCampaign.status: "paused"}, synchronize_session=False)
                paused += 1
            db.commit()
            succeeded += 1
            try:
                clear_whatsapp_defer_gate(account_id=account.id)
            except RedisError:
                pass
        except Exception:
            db.rollback()
            logger.exception("WhatsApp health poll failed", extra={"account_id": str(account_id)})
        finally:
            if client is not None:
                client.close()
            db.close()
    return {"succeeded": succeeded, "paused": paused}


@celery_app.task(name="app.workers.whatsapp_tasks.sync_whatsapp_templates")
def sync_whatsapp_templates() -> dict:
    listing = SessionLocal()
    try:
        account_ids = [
            row[0]
            for row in listing.query(WhatsappAccount.id)
            .filter(WhatsappAccount.status == "connected")
            .all()
        ]
    finally:
        listing.close()
    succeeded = 0
    for account_id in account_ids:
        db = SessionLocal()
        try:
            account = db.get(WhatsappAccount, account_id)
            if account is None or account.status != "connected":
                continue
            token = get_decrypted_token(db, account.id)
            if not token:
                continue
            result = sync_templates(db, account=account, access_token=token)
            if result.success:
                db.commit()
                succeeded += 1
            else:
                db.rollback()
        except Exception:
            db.rollback()
            logger.exception("WhatsApp template sync failed", extra={"account_id": str(account_id)})
        finally:
            db.close()
    return {"succeeded": succeeded}


@celery_app.task(name="app.workers.whatsapp_tasks.reap_whatsapp_sending_messages")
def reap_whatsapp_sending_messages() -> dict:
    db = SessionLocal()
    try:
        reaped = reap_stale_sending_messages(db)
        db.commit()
        return {"reaped": reaped}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _watchdog_kick(campaign: WhatsappCampaign, account: WhatsappAccount) -> bool:
    try:
        if _has_recent_dispatch(campaign.id):
            return False
        acquired = _redis().set(
            _watchdog_lock_key(campaign.id),
            "1",
            nx=True,
            ex=settings.WHATSAPP_DISPATCH_WATCHDOG_SECONDS,
        )
        if not acquired:
            return False
        delay = (
            settings.WHATSAPP_DISPATCH_BACKOFF_SECONDS
            if not settings.WHATSAPP_OUTREACH_ENABLED or account.outreach_paused
            else 1
        )
        if delay > 1:
            _set_defer_gate(
                account_id=account.id,
                reason="outreach_paused" if account.outreach_paused else "outreach_disabled",
                seconds=delay,
            )
        _schedule_dispatch(campaign.id, delay)
        _mark_dispatch(campaign.id, delay)
        return True
    except RedisError:
        # The dispatcher is database-idempotent; a conservative kick is safer
        # than leaving a campaign stranded when watchdog Redis state is lost.
        _schedule_dispatch(campaign.id, settings.WHATSAPP_DISPATCH_BACKOFF_SECONDS)
        return True


@celery_app.task(name="app.workers.whatsapp_tasks.rollup_whatsapp_campaigns")
def rollup_whatsapp_campaigns() -> dict:
    db = SessionLocal()
    completed = kicked = 0
    try:
        campaigns = db.query(WhatsappCampaign).filter(WhatsappCampaign.status == "running").all()
        for campaign in campaigns:
            counts = dict(
                db.query(
                    WhatsappCampaignRecipient.status,
                    func.count(WhatsappCampaignRecipient.id),
                )
                .filter(WhatsappCampaignRecipient.campaign_id == campaign.id)
                .group_by(WhatsappCampaignRecipient.status)
                .all()
            )
            campaign.total_recipients = sum(counts.values())
            campaign.sent_count = sum(counts.get(value, 0) for value in ("sent", "delivered", "read"))
            campaign.delivered_count = sum(counts.get(value, 0) for value in ("delivered", "read"))
            campaign.read_count = counts.get("read", 0)
            campaign.failed_count = counts.get("failed", 0)
            campaign.skipped_count = sum(
                count for status, count in counts.items() if status.startswith("skipped_")
            )
            outstanding = sum(counts.get(value, 0) for value in ("queued", "pending", "sending"))
            if outstanding == 0:
                campaign.status = "completed"
                campaign.completed_at = _utcnow()
                completed += 1
                continue
            account = db.get(WhatsappAccount, campaign.whatsapp_account_id)
            if account is not None and counts.get("pending", 0) and _watchdog_kick(campaign, account):
                kicked += 1
        db.commit()
        return {"completed": completed, "kicked": kicked}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
