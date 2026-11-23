import logging
from datetime import datetime, timedelta, timezone

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.webhook_event import WebhookEvent
from app.services.log_service import log_action
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# routes_webhooks stores the event as "pending" and then enqueues it; if the
# enqueue fails the row stays "pending" forever. Sweep those after a grace
# period, within a bounded window and batch.
STALE_AFTER = timedelta(minutes=5)
MAX_AGE = timedelta(hours=24)
BATCH_SIZE = 100
# Each event is re-enqueued / alerted at most once; the marker outlives MAX_AGE.
_MARKER_TTL_SECONDS = int((MAX_AGE + timedelta(hours=1)).total_seconds())

_redis_client: Redis | None = None


def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _first_time(key: str) -> bool:
    return bool(_redis().set(key, "1", nx=True, ex=_MARKER_TTL_SECONDS))


@celery_app.task(name="app.workers.webhook_recovery_tasks.sweep_webhook_events")
def sweep_webhook_events() -> dict:
    from app.workers.tasks import process_webhook_event

    counts = {"requeued": 0, "enqueue_failed": 0, "failed_alerted": 0}
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        try:
            _redis().ping()
        except RedisError:
            logger.exception("Webhook recovery sweep skipped: Redis unavailable")
            return counts

        stale = (
            db.query(WebhookEvent)
            .filter(
                WebhookEvent.processing_status == "pending",
                WebhookEvent.created_at <= now - STALE_AFTER,
                WebhookEvent.created_at >= now - MAX_AGE,
            )
            .order_by(WebhookEvent.created_at.asc())
            .limit(BATCH_SIZE)
            .all()
        )
        for event in stale:
            event_id = str(event.id)
            if not _first_time(f"webhook_recovery:requeued:{event_id}"):
                continue
            try:
                process_webhook_event.delay(event_id)
                counts["requeued"] += 1
                logger.info("Re-enqueued stale webhook event", extra={"event_id": event_id})
            except Exception:
                counts["enqueue_failed"] += 1
                logger.exception("Failed to re-enqueue stale webhook event", extra={"event_id": event_id})
                # Let the next sweep try again.
                try:
                    _redis().delete(f"webhook_recovery:requeued:{event_id}")
                except RedisError:
                    pass

        # Failed events are not re-run: their dedupe keys are already consumed, so
        # a rerun would skip the work. Make them visible instead.
        failed = (
            db.query(WebhookEvent)
            .filter(
                WebhookEvent.processing_status == "failed",
                WebhookEvent.updated_at >= now - MAX_AGE,
            )
            .order_by(WebhookEvent.updated_at.asc())
            .limit(BATCH_SIZE)
            .all()
        )
        for event in failed:
            event_id = str(event.id)
            if not _first_time(f"webhook_recovery:failed:{event_id}"):
                continue
            counts["failed_alerted"] += 1
            logger.warning(
                "Webhook event failed processing and will not be retried",
                extra={"event_id": event_id, "event_type": event.event_type},
            )
            log_action(
                db,
                "webhook_event_failed",
                details={"event_id": event_id, "event_type": event.event_type},
            )
    finally:
        db.close()
    return counts
