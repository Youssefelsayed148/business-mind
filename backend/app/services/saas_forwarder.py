"""Outbox + delivery loop for events Many forwards to the SaaS (M-02).

Contract: section 6 and delta A7/A13. Events are stored in saas_forward_events
and sent in seq order per ordering key. Network errors, 5xx and 429 are
retried with exponential backoff and jitter (Retry-After honoured) for up to
24 h with the same event_id; any other 4xx fails the event permanently. There
is never an AI fallback: a failing SaaS only queues and marks the channel
degraded.

A15: a 401 is also retried (secret rotation makes the two sides disagree for a
while). It uses the normal backoff inside the 24 h budget, marks the channel
degraded with saas_last_forward_status=auth_rejected and keeps the payload.
Every other 4xx stays permanent.
"""

import json
import logging
import random
import uuid
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.whatsapp_account import WhatsappAccount
from app.services import saas_delegation_service as delegation
from app.services.saas_signing import sign_headers

logger = logging.getLogger(__name__)

EVENTS_PATH = "/api/channels/manyosiris/events"
RETRY_BUDGET = timedelta(hours=24)
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 30 * 60
# Retention (F-02). A failed event keeps its payload so an operator can replay
# it; the message text is cleared after FAILED_PAYLOAD_RETENTION. Terminal
# rows and the outbound idempotency records go after TERMINAL_ROW_RETENTION
# (the contract minimum for the latter is 7 days).
FAILED_PAYLOAD_RETENTION = timedelta(days=7)
TERMINAL_ROW_RETENTION = timedelta(days=30)
OUTBOUND_RETENTION = timedelta(days=30)
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 15.0

CHANNEL_MODELS = {
    "instagram": InstagramAccount,
    "whatsapp": WhatsappAccount,
    "facebook": FacebookPage,
}
# Value of `channel` in the payload. The contract names the channels
# "WhatsApp number / Messenger page / Instagram account" without spelling the
# enum; keep the mapping in this one place.
CONTRACT_CHANNEL = {"instagram": "instagram", "whatsapp": "whatsapp", "facebook": "messenger"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=False,
    )


def enqueue_event(
    db: Session,
    *,
    platform: str,
    channel,
    ordering_key: str,
    event_id: str,
    event_type: str,
    payload: dict,
    now: datetime | None = None,
) -> bool:
    """Insert an outbox row (idempotent on event_id). Does not commit.
    Returns True if a new row was stored."""
    stmt = (
        pg_insert(SaasForwardEvent)
        .values(
            id=uuid.uuid4(),
            event_id=event_id,
            ordering_key=ordering_key,
            platform=platform,
            channel_id=channel.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempts=0,
            next_attempt_at=now or _now(),
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(SaasForwardEvent.id)
    )
    return db.execute(stmt).first() is not None


def drop_pending(db: Session, *, platform: str, channel_id, reason: str = "delegation_disabled") -> int:
    """Drop every queued, unsent event of a channel (contract A13). Does not
    commit."""
    rows = (
        db.query(SaasForwardEvent)
        .filter(
            SaasForwardEvent.platform == platform,
            SaasForwardEvent.channel_id == channel_id,
            SaasForwardEvent.status == "pending",
        )
        .all()
    )
    for row in rows:
        _finish(row, "dropped", reason)
    if rows:
        logger.info(
            "Dropped queued SaaS forwards",
            extra={"platform": platform, "channel_id": str(channel_id), "count": len(rows), "reason": reason},
        )
    return len(rows)


def _finish(row: SaasForwardEvent, status: str, error: str | None = None, now: datetime | None = None) -> None:
    row.status = status
    row.last_error = (error or None) and error[:200]
    row.completed_at = now or _now()
    row.next_attempt_at = None
    if status != "failed":
        # Failed rows keep their payload for replay until purge_expired().
        row.payload = {}


def count_failed(db: Session, *, platform: str, channel_id) -> tuple[int, int]:
    """(failed events, failed events that can still be replayed because their
    payload has not been cleared yet) for one channel."""
    base = db.query(func.count(SaasForwardEvent.id)).filter(
        SaasForwardEvent.platform == platform,
        SaasForwardEvent.channel_id == channel_id,
        SaasForwardEvent.status == "failed",
    )
    failed = base.scalar() or 0
    replayable = base.filter(SaasForwardEvent.payload != {}).scalar() or 0
    return failed, replayable


def requeue_failed(db: Session, *, platform: str, channel_id, now: datetime | None = None) -> int:
    """Put the failed events of a channel that still have a payload back in
    the queue with the same event_id. Does not commit; the per-minute sweep
    picks them up. The 24 h budget restarts (it is measured from created_at),
    and seq order keeps them ahead of later pending events of the same
    conversation."""
    now = now or _now()
    rows = (
        db.query(SaasForwardEvent)
        .filter(
            SaasForwardEvent.platform == platform,
            SaasForwardEvent.channel_id == channel_id,
            SaasForwardEvent.status == "failed",
            SaasForwardEvent.payload != {},
        )
        .all()
    )
    for row in rows:
        row.status = "pending"
        row.attempts = 0
        row.last_error = None
        row.completed_at = None
        row.created_at = now
        row.next_attempt_at = now
    return len(rows)


@dataclass
class PurgeResult:
    payloads_cleared: int = 0
    events_deleted: int = 0
    outbound_deleted: int = 0


def purge_expired(db: Session, *, now: datetime | None = None) -> PurgeResult:
    """Retention sweep. Commits.

    (a) clear the payload of failed events older than 7 days,
    (b) delete terminal (sent/dropped/failed) events older than 30 days,
    (c) delete saas_outbound_messages older than 30 days.
    Pending rows are never touched.
    """
    now = now or _now()
    result = PurgeResult()
    result.payloads_cleared = (
        db.query(SaasForwardEvent)
        .filter(
            SaasForwardEvent.status == "failed",
            SaasForwardEvent.completed_at < now - FAILED_PAYLOAD_RETENTION,
            SaasForwardEvent.payload != {},
        )
        .update({SaasForwardEvent.payload: {}}, synchronize_session=False)
    )
    result.events_deleted = (
        db.query(SaasForwardEvent)
        .filter(
            SaasForwardEvent.status.in_(("sent", "dropped", "failed")),
            SaasForwardEvent.completed_at < now - TERMINAL_ROW_RETENTION,
        )
        .delete(synchronize_session=False)
    )
    result.outbound_deleted = (
        db.query(SaasOutboundMessage)
        .filter(SaasOutboundMessage.created_at < now - OUTBOUND_RETENTION)
        .delete(synchronize_session=False)
    )
    db.commit()
    return result


def backoff_seconds(attempts: int, rng: random.Random | None = None) -> float:
    """Exponential backoff with jitter: half fixed, half random."""
    rng = rng or random
    ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)))
    return ceiling / 2 + rng.uniform(0, ceiling / 2)


def _retry_after(response: httpx.Response, now: datetime) -> float | None:
    """Seconds to wait per Retry-After: delta-seconds or an HTTP-date.
    Uncapped here; the caller bounds it by the remaining 24 h budget."""
    value = (response.headers.get("Retry-After") or "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - now).total_seconds())


@dataclass
class ProcessResult:
    sent: int = 0
    failed: int = 0
    dropped: int = 0
    retry_in: float | None = None  # seconds until the head should be retried


def _record(channel, status: str, *, degraded: bool | None = None, now: datetime) -> None:
    channel.saas_last_forward_status = status
    channel.saas_last_forward_at = now
    if degraded is not None:
        channel.saas_degraded = degraded


def process_ordering_key(
    db: Session,
    ordering_key: str,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> ProcessResult:
    """Send the pending events of one ordering key in order until one has to
    wait. The caller serialises calls per key (advisory lock in the task)."""
    result = ProcessResult()
    owns_client = client is None
    client = client or new_http_client()
    try:
        while True:
            current = now or _now()
            head = (
                db.query(SaasForwardEvent)
                .filter(SaasForwardEvent.ordering_key == ordering_key, SaasForwardEvent.status == "pending")
                .order_by(SaasForwardEvent.seq)
                .first()
            )
            if head is None:
                return result
            channel = db.get(CHANNEL_MODELS[head.platform], head.channel_id)
            if _expired(head, current):
                # Section 6: nothing is sent or waited on past the 24 h budget.
                _finish(head, "failed", "retry_budget_exhausted (expired before send)", current)
                if channel is not None:
                    _record(channel, "retry_budget_exhausted", degraded=True, now=current)
                db.commit()
                result.failed += 1
                continue
            if channel is None or not channel.saas_delegation_enabled:
                # A13: switched off (or gone) -> never send queued events.
                drop_pending(db, platform=head.platform, channel_id=head.channel_id)
                db.commit()
                result.dropped += 1
                continue

            if head.next_attempt_at and head.next_attempt_at > current:
                result.retry_in = (head.next_attempt_at - current).total_seconds()
                return result

            outcome = _attempt(db, head, channel, client, current, rng)
            db.commit()
            if outcome == "sent":
                result.sent += 1
            elif outcome == "failed":
                result.failed += 1
            else:
                result.retry_in = (head.next_attempt_at - current).total_seconds()
                return result
    finally:
        if owns_client:
            client.close()


def _expired(row: SaasForwardEvent, current: datetime) -> bool:
    return current - (row.created_at or current) >= RETRY_BUDGET


def _attempt(db, row: SaasForwardEvent, channel, client, current: datetime, rng) -> str:
    """One delivery attempt. Returns 'sent', 'failed' or 'retry'."""
    row.attempts += 1
    try:
        base_url = delegation.validate_base_url(channel.saas_base_url or "")
        secret, _previous = delegation.get_secrets(channel)
        if not secret or not channel.saas_connection_id:
            raise delegation.DelegationConfigError("incomplete delegation config")
    except delegation.DelegationConfigError as exc:
        # Misconfiguration will not fix itself between retries of one event.
        _finish(row, "failed", f"config_error: {exc}", current)
        _record(channel, "config_error", degraded=True, now=current)
        return "failed"

    body = json.dumps(row.payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = sign_headers(channel.saas_connection_id, secret, body)
    headers["Content-Type"] = "application/json"

    retry_after: float | None = None
    retry_status = "retrying"
    try:
        response = client.post(base_url + EVENTS_PATH, content=body, headers=headers)
    except httpx.HTTPError as exc:
        error = f"network_error: {type(exc).__name__}"
    else:
        code = response.status_code
        if 200 <= code < 300:
            _finish(row, "sent", None, current)
            _record(channel, f"sent_{code}", degraded=False, now=current)
            return "sent"
        if code >= 500 or code == 429:
            error = f"http_{code}"
            retry_after = _retry_after(response, current) if code in (429, 503) else None
        elif code == 401:
            # A15: retryable, the operator may still be entering the new secret.
            error = "http_401"
            retry_status = "auth_rejected"
        else:
            # Other 4xx (401 is handled above) and unfollowed 3xx are permanent.
            _finish(row, "failed", f"http_{code}", current)
            _record(channel, f"rejected_{code}", degraded=True, now=current)
            logger.warning(
                "SaaS rejected forwarded event",
                extra={"event_id": row.event_id, "status_code": code},
            )
            return "failed"

    created = row.created_at or current
    delay = max(backoff_seconds(row.attempts, rng), retry_after or 0.0)
    # Never wait past the deadline: the next pass then fails the row cleanly.
    deadline = created + RETRY_BUDGET
    row.next_attempt_at = min(current + timedelta(seconds=delay), deadline)
    row.last_error = error[:200]
    _record(channel, retry_status, degraded=True, now=current)
    return "retry"
