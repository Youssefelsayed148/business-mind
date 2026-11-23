"""Channel health for the SaaS (contract 4.3 / 5.2, M-05).

Everything is derived from state Many already keeps: the channel's own
status, its token rows and the shared webhook_health record. No Meta call is
made here. `current_health` is pure with respect to that state, so the push
(channel.status events) and the pull (GET .../health) always agree.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.facebook_token import FacebookToken
from app.models.meta_token import MetaToken
from app.models.webhook_health import WebhookHealth
from app.models.whatsapp_token import WhatsappToken
from app.services import saas_inbound
from app.services.saas_forwarder import CHANNEL_MODELS, enqueue_event

logger = logging.getLogger(__name__)

# The contract asks for a heartbeat at least every 6 h; sweeping a bit early
# keeps a delayed beat tick from breaking that.
HEARTBEAT_INTERVAL = timedelta(hours=5)
TOKEN_EXPIRING_WINDOW = timedelta(days=7)
# Same threshold the existing /webhooks/health endpoint calls an alert.
WEBHOOK_FAILURE_THRESHOLD = 3

TOKEN_MODELS = {
    "instagram": (MetaToken, "instagram_account_id"),
    "whatsapp": (WhatsappToken, "whatsapp_account_id"),
    "facebook": (FacebookToken, "facebook_page_id"),
}
STATUSES = {"connected", "token_expiring", "token_expired", "webhook_unhealthy", "disconnected"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime) -> str:
    return _aware(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_token(db: Session, platform: str, channel):
    model, fk = TOKEN_MODELS[platform]
    return (
        db.query(model)
        .filter(getattr(model, fk) == channel.id)
        .order_by(model.created_at.desc())
        .first()
    )


def current_health(db: Session, platform: str, channel, now: datetime | None = None) -> dict:
    """{"status", "detail"?, "expires_at"?} for one channel."""
    now = now or _now()
    if channel.status != "connected":
        return {"status": "disconnected", "detail": "channel is not connected"}

    token = _latest_token(db, platform, channel)
    expires_at = _aware(token.expires_at) if token is not None else None
    if token is None or token.status == "expired" or (expires_at is not None and expires_at <= now):
        result = {"status": "token_expired", "detail": "no valid access token"}
        if expires_at is not None:
            result["expires_at"] = _iso(expires_at)
        return result

    # The webhook record is per provider ("meta"), not per channel, so this
    # reflects Meta delivery to this app as a whole.
    record = db.query(WebhookHealth).filter(WebhookHealth.provider == "meta").first()
    if record is not None and (record.consecutive_failures or 0) >= WEBHOOK_FAILURE_THRESHOLD:
        return {"status": "webhook_unhealthy", "detail": "webhook processing is failing"}

    expiring = token.status == "expiring_soon" or (
        expires_at is not None and expires_at <= now + TOKEN_EXPIRING_WINDOW
    )
    if expiring:
        result = {"status": "token_expiring", "detail": "access token is close to expiry"}
        if expires_at is not None:
            result["expires_at"] = _iso(expires_at)
        return result
    return {"status": "connected"}


def health_body(db: Session, platform: str, channel, now: datetime | None = None) -> dict:
    """Response of GET /saas/connections/{id}/health."""
    now = now or _now()
    body = current_health(db, platform, channel, now)
    body["checked_at"] = _iso(now)
    return body


def _emit(db: Session, platform: str, channel, health: dict, now: datetime) -> bool:
    event_id = f"ch:{uuid.uuid4().hex}"
    payload = {
        "version": 1,
        "event_id": event_id,
        "event_type": "channel.status",
        "connection_id": channel.saas_connection_id,
        "occurred_at": _iso(now),
        "status": health["status"],
    }
    if health.get("detail"):
        payload["detail"] = health["detail"][:200]
    if health.get("expires_at"):
        payload["expires_at"] = health["expires_at"]
    # Own ordering key: health events are ordered among themselves, and never
    # sit behind a stuck conversation.
    key = f"channel:{platform}:{channel.id}"
    return enqueue_event(
        db,
        platform=platform,
        channel=channel,
        ordering_key=key,
        event_id=event_id,
        event_type="channel.status",
        payload=payload,
        now=now,
    )


def sync_channel(
    db: Session, platform: str, channel, *, now: datetime | None = None, force: bool = False, kick: bool = True
) -> bool:
    """Push channel.status if the derived status changed since the last push,
    or the heartbeat is due (or `force`). Commits. Returns True if queued."""
    if not channel.saas_delegation_enabled or not channel.saas_connection_id:
        return False
    now = now or _now()
    health = current_health(db, platform, channel, now)
    last_at = _aware(channel.saas_last_health_at)
    due = (
        force
        or channel.saas_last_health_status != health["status"]
        or last_at is None
        or now - last_at >= HEARTBEAT_INTERVAL
    )
    if not due:
        return False
    queued = _emit(db, platform, channel, health, now)
    channel.saas_last_health_status = health["status"]
    channel.saas_last_health_at = now
    db.commit()
    if queued and kick:
        saas_inbound._kick(f"channel:{platform}:{channel.id}")
    return queued


def sync_all(db: Session, *, now: datetime | None = None) -> int:
    queued = 0
    for platform, model in CHANNEL_MODELS.items():
        for channel in db.query(model).filter(model.saas_delegation_enabled.is_(True)).all():
            try:
                if sync_channel(db, platform, channel, now=now):
                    queued += 1
            except Exception:
                db.rollback()
                logger.exception(
                    "channel.status sync failed", extra={"platform": platform, "channel_id": str(channel.id)}
                )
    return queued
